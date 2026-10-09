"""Shadow-clerk daemon: 用語置換・文字起こし"""
from __future__ import annotations
import logging
import os
import re
import sys
import threading
from typing import Any
import numpy as np
from shadow_clerk._daemon_constants import GLOSSARY_FILE, SAMPLE_RATE
from shadow_clerk._daemon_config import load_config

try:
    from shadow_clerk.llm_client import get_api_client, load_glossary, load_glossary_replacements, load_dotenv as llm_load_dotenv, _spell_check
    _HAS_LLM_CLIENT = True
except ImportError:
    _HAS_LLM_CLIENT = False

logger = logging.getLogger("shadow-clerk")


class GlossaryReplacer:
    """glossary.txt の reading → 言語列 によるテキスト置換。ファイル変更時・言語変更時は自動再読み込み。"""

    def __init__(self) -> None:
        self._path = GLOSSARY_FILE
        self._replacements: list[tuple[str, str]] = []
        self._mtime: float | None = None
        self._lang: str | None = None
        self._load(None)

    def _load(self, lang: str | None):
        try:
            mtime = os.path.getmtime(self._path)
            if mtime == self._mtime and lang == self._lang:
                return
            self._mtime = mtime
            self._lang = lang
            if _HAS_LLM_CLIENT:
                self._replacements = load_glossary_replacements(lang)
            else:
                self._replacements = []
            logger.info("glossary replacements 読み込み: %d 件 (lang=%s)", len(self._replacements), lang)
        except FileNotFoundError:
            if self._mtime is not None:
                self._replacements = []
                self._mtime = None
                logger.info("glossary.txt が削除されました")

    def apply(self, text: str, lang: str | None = None) -> str:
        self._load(lang)
        for reading, replacement in self._replacements:
            text = text.replace(reading, replacement)
        return text


# --- 文字起こし ---
# 本家 reazon-research/reazonspeech-k2-v2-ja-en は非公開になり、reazonspeech ライブラリの
# load_model(language="ja-en") は 401 で落ちる。sherpa-onnx 作者による転載から読む
K2_JA_EN_REPO = "csukuangfj/reazonspeech-k2-v2-ja-en"


def _load_k2_ja_en(device: str, precision: str) -> Any:
    """reazonspeech.k2.asr.load_model と同じ構成で日英モデルを読む（transcribe はライブラリのものが使える）"""
    import huggingface_hub as hf
    import sherpa_onnx
    from huggingface_hub.utils import LocalEntryNotFoundError
    enc, dec = {"fp32": ("", ""), "int8": (".int8", ".int8"), "int8-fp32": (".int8", "")}[precision]

    def fetch(name: str) -> str:
        try:
            return hf.hf_hub_download(K2_JA_EN_REPO, name, local_files_only=True)
        except LocalEntryNotFoundError:
            return hf.hf_hub_download(K2_JA_EN_REPO, name)

    return sherpa_onnx.OfflineRecognizer.from_transducer(
        tokens=fetch("tokens.txt"),
        encoder=fetch(f"encoder-epoch-35-avg-1{enc}.onnx"),
        decoder=fetch(f"decoder-epoch-35-avg-1{dec}.onnx"),
        joiner=fetch(f"joiner-epoch-35-avg-1{enc}.onnx"),
        num_threads=1, sample_rate=SAMPLE_RATE, feature_dim=80,
        decoding_method="greedy_search", provider=device,
    )


def _moonshine_languages() -> list[str]:
    try:
        from moonshine_voice import supported_languages
    except ImportError:
        return []
    return supported_languages()


class Transcriber:
    """faster-whisper / ReazonSpeech K2 / Moonshine による文字起こし"""

    def __init__(self, model_size: str = "small", language: str | None = None,
                 initial_prompt: str | None = None,
                 beam_size: int = 5, compute_type: str = "int8",
                 device: str = "cpu",
                 ja_asr_config_key: str = "japanese_asr_model",
                 engine_config_key: str = "asr_engine",
                 label: str = "main") -> None:
        self.model_size = model_size
        self.language = language
        self.initial_prompt = initial_prompt
        self.beam_size = beam_size
        self.compute_type = compute_type
        self.device = device
        self.model: Any = None
        self._loaded_model_id: str | None = None
        self._backend: str = "whisper"  # "whisper" / "reazonspeech-k2" / "moonshine"
        self._ja_asr_config_key = ja_asr_config_key
        self._engine_config_key = engine_config_key
        self._label = label
        # transcribe 中のモデル差し替え（reload_model / ensure_model_for_language は
        # 別スレッドから呼ばれる）で model が None になる競合を防ぐ
        self._model_lock = threading.RLock()

    def _resolve_model_id(self) -> tuple[str, str]:
        """(backend, model_id) を返す"""
        config = load_config()
        if self.language == "ja":
            ja_asr = config.get(self._ja_asr_config_key, "default")
            if ja_asr == "kotoba-whisper":
                return ("whisper", config.get("kotoba_whisper_model",
                        "kotoba-tech/kotoba-whisper-v2.0-faster"))
            elif ja_asr == "reazonspeech-k2":
                return ("reazonspeech-k2", f"reazonspeech-k2-{config.get('reazonspeech_model') or 'ja'}")
        if self.language == "en":
            en_asr = config.get("english_asr_model", "default")
            if en_asr != "default":
                return ("whisper", en_asr)
        # Moonshine は言語指定が要る。自動検出・未対応言語・未インストールは Whisper
        if config.get(self._engine_config_key) == "moonshine" and self.language:
            if self.language in _moonshine_languages():
                return ("moonshine", f"moonshine-{self.language}")
            logger.warning("[%s] Moonshine は言語 %s に使えません (未対応か未インストール) — "
                           "Whisper を使います。", self._label, self.language)
        return ("whisper", self.model_size)

    def load_model(self) -> None:
        with self._model_lock:
            self._load_model_locked()

    def _load_model_locked(self) -> None:
        backend, model_id = self._resolve_model_id()
        if self.model is not None and self._loaded_model_id == model_id and self._backend == backend:
            return
        if backend == "reazonspeech-k2":
            try:
                # sherpa-onnx-core の動的ライブラリ参照パスを追加
                import sherpa_onnx as _so
                _so_lib = os.path.join(os.path.dirname(_so.__file__), "lib")
                if not os.path.isdir(_so_lib) and getattr(sys, "frozen", False):
                    # 凍結した実行ファイルでは __file__ が書庫の中を指すことがあり、
                    # その隣に lib は無い。PyInstaller が展開した先を見る
                    _so_lib = os.path.join(getattr(sys, "_MEIPASS", ""),
                                           "sherpa_onnx", "lib")
                import ctypes
                if sys.platform == "win32":
                    # Windows: DLL 検索ディレクトリを追加し、onnxruntime.dll を明示ロード
                    try:
                        os.add_dll_directory(_so_lib)
                    except (OSError, AttributeError):
                        pass
                    ctypes.cdll.LoadLibrary(os.path.join(_so_lib, "onnxruntime.dll"))
                else:
                    # Linux/macOS: LD_LIBRARY_PATH 経由で参照
                    _ld = os.environ.get("LD_LIBRARY_PATH", "")
                    if _so_lib not in _ld:
                        os.environ["LD_LIBRARY_PATH"] = f"{_so_lib}:{_ld}" if _ld else _so_lib
                        ctypes.cdll.LoadLibrary(os.path.join(_so_lib, "libonnxruntime.so"))
                from reazonspeech.k2.asr import load_model as k2_load_model
            except (ImportError, OSError) as e:
                logger.warning("reazonspeech-k2 の読み込みに失敗: %s — "
                               "Whisper にフォールバックします。", e)
                backend, model_id = "whisper", self.model_size
        if backend == "reazonspeech-k2":
            # ReazonSpeech k2 は ONNX 量子化バリアント(fp32/int8/int8-fp32)で
            # precision を指定する。fp16 は無効。device=cuda でも fp32 で動作
            # (sherpa-onnx の CUDA Execution Provider を使う)。
            precision = load_config().get("reazonspeech_precision") or "fp32"
            logger.info("[%s] ReazonSpeech K2 モデル読み込み中: %s (device=%s, precision=%s) ...",
                         self._label, model_id, self.device, precision)
            if model_id.endswith("-ja-en"):
                self.model = _load_k2_ja_en(self.device, precision)
            else:
                self.model = k2_load_model(device=self.device, precision=precision)
            self._backend = "reazonspeech-k2"
        elif backend == "moonshine":
            from moonshine_voice import Transcriber as MoonshineTranscriber, MoonshineError, get_model_for_language
            logger.info("[%s] Moonshine モデル読み込み中: %s ...", self._label, model_id)
            path, arch = get_model_for_language(self.language)
            self.model = MoonshineTranscriber(model_path=path, model_arch=arch)
            # initial_prompt 相当。バイアスはストリーミング系のモデルでしか効かない
            try:
                self.model.set_context(self.initial_prompt)
            except MoonshineError as e:
                logger.info("[%s] Moonshine の context 設定をスキップ: %s", self._label, e)
            self._backend = "moonshine"
        else:
            from faster_whisper import WhisperModel
            logger.info("[%s] Whisper モデル読み込み中: %s (device=%s, compute_type=%s) ...",
                         self._label, model_id, self.device, self.compute_type)
            self.model = WhisperModel(model_id, device=self.device, compute_type=self.compute_type)
            self._backend = "whisper"
        self._loaded_model_id = model_id
        logger.info("[%s] モデル読み込み完了: %s", self._label, model_id)

    def reload_model(self, model_size: str) -> None:
        with self._model_lock:
            self.model_size = model_size
            self.model = None
            self._loaded_model_id = None
            self._backend = "whisper"
            self._load_model_locked()

    def ensure_model_for_language(self) -> None:
        with self._model_lock:
            # model が None かつ _loaded_model_id も None の場合はロード未試行か前回失敗。
            # どちらも次の transcribe 呼び出しで再試行されるので早期リターン。
            # ただし _loaded_model_id が設定済みなら正常ロード済みなので切り替え判定する。
            if self.model is None and self._loaded_model_id is None:
                return
            backend, model_id = self._resolve_model_id()
            if self._loaded_model_id != model_id or self._backend != backend:
                logger.info("言語変更に伴いモデルを切り替え: %s -> %s", self._loaded_model_id, model_id)
                self.model = None
                self._loaded_model_id = None
                self._load_model_locked()

    # Whisper がよく出力するハルシネーション（無音時の誤認識）パターン
    HALLUCINATION_RE = re.compile(
        r"(字幕|ご視聴|ご覧いただき|ありがとうございました|チャンネル登録"
        r"|お疲れ様でした|よろしくお願いします"
        r"|Thank you for watching|Thanks for watching"
        r"|Please subscribe|See you next time"
        r"|Subtitles by|Amara\.org)",
        re.IGNORECASE,
    )

    def transcribe(self, audio: np.ndarray) -> str:
        """音声セグメントを文字起こし"""
        with self._model_lock:
            if self.model is None:
                self._load_model_locked()
            assert self.model is not None
            if self._backend == "reazonspeech-k2":
                return self._transcribe_k2(audio)
            if self._backend == "moonshine":
                return self._transcribe_moonshine(audio)
            return self._transcribe_whisper(audio)

    def _transcribe_whisper(self, audio: np.ndarray) -> str:
        """Whisper バックエンドによる文字起こし"""
        # faster-whisper は float32 の numpy 配列を受け付ける
        audio_f32 = audio.astype(np.float32) / 32768.0
        # 区間切りは自前の webrtcvad。Silero はその区間内の非音声を落とす——無いと
        # ノイズだけの区間で initial_prompt（ウェイクワード）をそのまま幻聴する
        config = load_config()
        vad = bool(config.get("whisper_vad_filter", True))
        segments, info = self.model.transcribe(
            audio_f32,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=vad,
            vad_parameters={"threshold": float(config.get("whisper_vad_threshold") or 0.35)} if vad else None,
            initial_prompt=self.initial_prompt,
        )

        text_parts = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            # no_speech_prob が高いセグメントはスキップ
            if seg.no_speech_prob > 0.6:
                logger.debug("ハルシネーション除去 (no_speech=%.2f): %s", seg.no_speech_prob, text)
                continue
            # 既知のハルシネーションパターンをフィルタ
            if self.HALLUCINATION_RE.search(text):
                logger.debug("ハルシネーション除去 (パターン): %s", text)
                continue
            text_parts.append(text)

        return " ".join(text_parts)

    def _transcribe_k2(self, audio: np.ndarray) -> str:
        """ReazonSpeech K2 バックエンドによる文字起こし"""
        from reazonspeech.k2.asr import transcribe as k2_transcribe, audio_from_numpy
        audio_f32 = audio.astype(np.float32) / 32768.0
        k2_audio = audio_from_numpy(audio_f32, SAMPLE_RATE)
        ret = k2_transcribe(self.model, k2_audio)
        text = ret.text.strip() if ret.text else ""
        # 日英モデルは英語を全部大文字で出す
        return text.lower() if (self._loaded_model_id or "").endswith("-ja-en") else text

    def _transcribe_moonshine(self, audio: np.ndarray) -> str:
        """Moonshine バックエンドによる文字起こし。自前で発話を区切った行が複数返る"""
        audio_f32 = audio.astype(np.float32) / 32768.0
        ret = self.model.transcribe_without_streaming(audio_f32.tolist(), SAMPLE_RATE)
        return " ".join(text for line in ret.lines if (text := line.text.strip()))
