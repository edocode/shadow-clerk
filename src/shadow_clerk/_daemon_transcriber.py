"""Shadow-clerk daemon: 用語置換・文字起こし"""

import logging
import os
import re
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

    def __init__(self):
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
class Transcriber:
    """faster-whisper / ReazonSpeech K2 による文字起こし"""

    def __init__(self, model_size: str = "small", language: str | None = None,
                 initial_prompt: str | None = None,
                 beam_size: int = 5, compute_type: str = "int8",
                 device: str = "cpu",
                 ja_asr_config_key: str = "japanese_asr_model"):
        self.model_size = model_size
        self.language = language
        self.initial_prompt = initial_prompt
        self.beam_size = beam_size
        self.compute_type = compute_type
        self.device = device
        self.model = None
        self._loaded_model_id: str | None = None
        self._backend: str = "whisper"  # "whisper" or "reazonspeech-k2"
        self._ja_asr_config_key = ja_asr_config_key

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

    def load_model(self):
        backend, model_id = self._resolve_model_id()
        if self.model is not None and self._loaded_model_id == model_id and self._backend == backend:
            return
        if backend == "reazonspeech-k2":
            try:
                # sherpa-onnx-core の libonnxruntime.so を参照するためパスを追加
                import sherpa_onnx as _so
                _so_lib = os.path.join(os.path.dirname(_so.__file__), "lib")
                _ld = os.environ.get("LD_LIBRARY_PATH", "")
                if _so_lib not in _ld:
                    os.environ["LD_LIBRARY_PATH"] = f"{_so_lib}:{_ld}" if _ld else _so_lib
                    import ctypes
                    ctypes.cdll.LoadLibrary(os.path.join(_so_lib, "libonnxruntime.so"))
                from reazonspeech.k2.asr import load_model as k2_load_model
            except (ImportError, OSError) as e:
                logger.warning("reazonspeech-k2 の読み込みに失敗: %s — "
                               "Whisper にフォールバックします。", e)
                backend, model_id = "whisper", self.model_size
        if backend == "reazonspeech-k2":
            precision = "fp32" if self.device == "cpu" else "fp16"
            logger.info("ReazonSpeech K2 モデル読み込み中: %s (device=%s, precision=%s) ...",
                         model_id, self.device, precision)
            self.model = k2_load_model(device=self.device, precision=precision)
            self._backend = "reazonspeech-k2"
        else:
            from faster_whisper import WhisperModel
            logger.info("Whisper モデル読み込み中: %s (device=%s, compute_type=%s) ...",
                         model_id, self.device, self.compute_type)
            self.model = WhisperModel(model_id, device=self.device, compute_type=self.compute_type)
            self._backend = "whisper"
        self._loaded_model_id = model_id
        logger.info("モデル読み込み完了: %s", model_id)

    def reload_model(self, model_size: str):
        self.model_size = model_size
        self.model = None
        self._loaded_model_id = None
        self._backend = "whisper"
        self.load_model()

    def ensure_model_for_language(self):
        if self.model is None:
            return
        backend, model_id = self._resolve_model_id()
        if self._loaded_model_id != model_id or self._backend != backend:
            logger.info("言語変更に伴いモデルを切り替え: %s -> %s", self._loaded_model_id, model_id)
            self.model = None
            self._loaded_model_id = None
            self.load_model()

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
        if self.model is None:
            self.load_model()
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
