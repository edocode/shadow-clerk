"""Shadow-clerk daemon: 用語置換・文字起こし"""
from __future__ import annotations
import logging
import os
import re
import sys
import threading
from collections.abc import Callable
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


# --- モデル共有キャッシュ ---
# ReazonSpeech K2 (sherpa-onnx OfflineRecognizer) はデコードごとに create_stream() で
# 状態を作り、モデル本体は不変・設定非依存でスレッドセーフに並行デコードできる。
# main と interim が同一設定なら fp32 重み ~750MB の二重ロードを避けるため共有する。
# キーはロード結果を左右する要素すべて (backend / model_id / device / variant) を含み、
# 設定が異なれば従来どおり別々にロードされる。値は [model, refcount]。
_MODEL_CACHE: dict[tuple[str, str, str, str], list[Any]] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def _acquire_shared_model(key: tuple[str, str, str, str],
                          factory: Callable[[], Any]) -> tuple[Any, bool]:
    """共有モデルを取得し参照数を +1。戻り値は (model, キャッシュヒットか)。

    ロードはロックを保持したまま行う。起動時に数秒直列化するだけで済み、
    同時初回ロードで一時的に 2 個分のメモリを確保してしまう事故を防げる。
    """
    with _MODEL_CACHE_LOCK:
        entry = _MODEL_CACHE.get(key)
        if entry is None:
            _MODEL_CACHE[key] = entry = [factory(), 0]
            hit = False
        else:
            hit = True
        entry[1] += 1
        return entry[0], hit


def _release_shared_model(key: tuple[str, str, str, str]) -> None:
    """共有モデルの参照数を -1。0 になったらキャッシュから外す。"""
    with _MODEL_CACHE_LOCK:
        entry = _MODEL_CACHE.get(key)
        if entry is None:
            return
        entry[1] -= 1
        if entry[1] <= 0:
            del _MODEL_CACHE[key]
            logger.info("共有モデルを解放: %s", key)


# --- 文字起こし ---
class Transcriber:
    """faster-whisper / ReazonSpeech K2 による文字起こし"""

    def __init__(self, model_size: str = "small", language: str | None = None,
                 initial_prompt: str | None = None,
                 beam_size: int = 5, compute_type: str = "int8",
                 device: str = "cpu",
                 ja_asr_config_key: str = "japanese_asr_model",
                 label: str = "main") -> None:
        self.model_size = model_size
        self.language = language
        self.initial_prompt = initial_prompt
        self.beam_size = beam_size
        self.compute_type = compute_type
        self.device = device
        self.model: Any = None
        self._loaded_model_id: str | None = None
        self._backend: str = "whisper"  # "whisper" or "reazonspeech-k2"
        self._ja_asr_config_key = ja_asr_config_key
        self._label = label
        # _MODEL_CACHE から借りている場合のキー（未使用なら None）
        self._shared_key: tuple[str, str, str, str] | None = None
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
                return ("reazonspeech-k2", "reazonspeech-k2")
        return ("whisper", self.model_size)

    def load_model(self) -> None:
        with self._model_lock:
            self._load_model_locked()

    def _load_model_locked(self) -> None:
        backend, model_id = self._resolve_model_id()
        if self.model is not None and self._loaded_model_id == model_id and self._backend == backend:
            return
        # 別モデルに載せ替えるので、借りていた共有モデルは先に返却する
        self._release_shared_locked()
        if backend == "reazonspeech-k2":
            try:
                # sherpa-onnx-core の動的ライブラリ参照パスを追加
                import sherpa_onnx as _so
                _so_lib = os.path.join(os.path.dirname(_so.__file__), "lib")
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
            key = ("reazonspeech-k2", model_id, self.device, precision)
            self.model, hit = _acquire_shared_model(
                key, lambda: k2_load_model(device=self.device, precision=precision))
            self._shared_key = key
            if hit:
                logger.info("[%s] 共有済みの K2 モデルを再利用: %s", self._label, key)
            self._backend = "reazonspeech-k2"
        else:
            from faster_whisper import WhisperModel
            logger.info("[%s] Whisper モデル読み込み中: %s (device=%s, compute_type=%s) ...",
                         self._label, model_id, self.device, self.compute_type)
            self.model = WhisperModel(model_id, device=self.device, compute_type=self.compute_type)
            self._backend = "whisper"
        self._loaded_model_id = model_id
        logger.info("[%s] モデル読み込み完了: %s", self._label, model_id)

    def _release_shared_locked(self) -> None:
        if self._shared_key is not None:
            _release_shared_model(self._shared_key)
            self._shared_key = None

    def release(self) -> None:
        """この Transcriber を破棄する前に呼び、共有モデルの参照を返却する"""
        with self._model_lock:
            self._release_shared_locked()
            self.model = None
            self._loaded_model_id = None

    def reload_model(self, model_size: str) -> None:
        with self._model_lock:
            self.model_size = model_size
            self.model = None
            self._loaded_model_id = None
            self._backend = "whisper"
            self._load_model_locked()

    def ensure_model_for_language(self) -> None:
        with self._model_lock:
            if self.model is None:
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
            return self._transcribe_whisper(audio)

    def _transcribe_whisper(self, audio: np.ndarray) -> str:
        """Whisper バックエンドによる文字起こし"""
        # faster-whisper は float32 の numpy 配列を受け付ける
        audio_f32 = audio.astype(np.float32) / 32768.0

        segments, info = self.model.transcribe(
            audio_f32,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=False,  # 自前のVADを使用
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
        return ret.text.strip() if ret.text else ""
