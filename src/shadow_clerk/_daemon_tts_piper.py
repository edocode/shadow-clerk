"""Shadow-clerk daemon: piper による英語の読み上げ（talk mode で ja 以外の文を読む）

VOICEVOX は英文を日本語なまりで読む。piper の VCTK モデルは、イングランド・スコットランド・アイルランド・
アメリカ・インドなど、なまりの違う 109 人の話者を持つ。いろいろな英語を聞き取る練習になるので、
既定では会話ごとに話者をランダムに選ぶ。
"""
from __future__ import annotations

import logging
import os
import random
import threading
from pathlib import Path
from typing import Any

import numpy as np

from shadow_clerk import DATA_DIR
from shadow_clerk._daemon_tts import TtsError
from shadow_clerk.domain import Language

logger = logging.getLogger("shadow-clerk")

PIPER_MODEL = "en_GB-vctk-medium"
PIPER_DIR = os.path.join(DATA_DIR, "piper")
RANDOM_VOICE = "random"


class PiperBackend:
    """モデルは別スレッドで用意する（初回はダウンロードする）。synthesize は用意ができるまで待つ"""

    LANGUAGES: tuple[Language, ...] = (Language.EN,)
    DEFAULT_LANGUAGE = Language.EN

    def __init__(self, voice: str = RANDOM_VOICE, model_dir: str = PIPER_DIR) -> None:
        self._wanted = voice.strip() or RANDOM_VOICE
        self._dir = model_dir
        self._voice: Any = None
        self._speaker: int | None = None
        self.speaker_name = ""
        self._error = ""
        self._ready = threading.Thread(target=self._prepare, name="piper-load", daemon=True)
        self._ready.start()

    def _prepare(self) -> None:
        try:
            from piper import PiperVoice
            from piper.download_voices import download_voice
            path = os.path.join(self._dir, PIPER_MODEL + ".onnx")
            if not os.path.exists(path):
                logger.info("talk: piper のモデル %s をダウンロードします", PIPER_MODEL)
                os.makedirs(self._dir, exist_ok=True)
                download_voice(PIPER_MODEL, Path(self._dir))
            voice = PiperVoice.load(path)
            speakers: dict[str, int] = voice.config.speaker_id_map
            name = self._wanted if self._wanted in speakers else random.choice(sorted(speakers))
            if self._wanted not in (RANDOM_VOICE, name):
                logger.warning("talk: piper の話者 %r が無いのでランダムに選びます", self._wanted)
            self._voice, self._speaker, self.speaker_name = voice, speakers[name], name
            logger.info("talk: 英語は piper の話者 %s で読みます", name)
        except Exception as e:
            self._error = str(e)
            logger.warning("talk: piper を使えません: %s", e)

    def check(self) -> None:
        pass

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        self._ready.join()
        if self._voice is None:
            raise TtsError(self._error)
        from piper import SynthesisConfig
        chunks = [c.audio_float_array for c in self._voice.synthesize(text, SynthesisConfig(speaker_id=self._speaker))]
        if not chunks:
            raise TtsError(f"piper: empty audio for {text!r}")
        return np.concatenate(chunks).astype(np.float32), int(self._voice.config.sample_rate)

    def credit(self) -> str:
        return "piper (VCTK)"

    def voices(self) -> list[dict[str, Any]]:
        return []


def make_foreign_backend(config: dict) -> PiperBackend | None:
    """piper が入っていなければ None（ja 以外の文はこれまでどおりブラウザで読む）"""
    try:
        import piper  # noqa: F401
    except ImportError:
        return None
    return PiperBackend(str(config.get("talk_piper_voice") or RANDOM_VOICE))
