"""Shadow-clerk daemon: piper による英語の読み上げ（talk mode で ja 以外の文を読む）

VOICEVOX は英文を日本語なまりで読む。piper の VCTK モデルは、イングランド・スコットランド・アイルランド・
アメリカ・インドなど、なまりの違う 109 人の話者を持つ。いろいろな英語を聞き取る練習になるので、
既定では会話ごとに話者をランダムに選ぶ（ACCENTS の名前でなまりを絞れる）。発音の練習では、お手本は癖の少ない標準的な声（STANDARD_MODELS から会話ごとに
1 つ選ぶ）で読む（standard を真にする。初回にダウンロードする）。
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
STANDARD_MODELS = ("en_US-hfc_female-medium", "en_US-hfc_male-medium")  # 癖の少ないアメリカ英語。発音のお手本用
PIPER_DIR = os.path.join(DATA_DIR, "piper")
RANDOM_VOICE = "random"
# VCTK の話者を大まかななまりで分ける（コーパスの speaker-info の ACCENTS 欄から）。talk_piper_voice に名前を書くとその中から選ぶ
ACCENTS: dict[str, tuple[str, ...]] = {
    "british": tuple(f"p{n}" for n in (225, 226, 227, 228, 229, 230, 231, 232, 233, 236, 239, 240, 243, 244, 250, 253, 254,
                                       256, 257, 258, 259, 267, 268, 269, 270, 273, 274, 276, 277, 278, 279, 282, 286, 287)),
    "scottish": tuple(f"p{n}" for n in (234, 237, 241, 246, 247, 249, 252, 255, 260, 262, 263, 264, 265, 271, 272, 275,
                                        281, 284, 285)),
    "irish": tuple(f"p{n}" for n in (238, 245, 261, 266, 283, 288, 292, 293, 295, 298, 304, 313, 340, 351, 364)),
    "american": tuple(f"p{n}" for n in (294, 297, 299, 300, 301, 302, 303, 305, 306, 307, 308, 310, 311, 312, 316, 317, 318,
                                        329, 330, 333, 334, 339, 341, 343, 345, 360, 361, 362, 363)),
    "other": tuple(f"p{n}" for n in (248, 251, 314, 323, 326, 335, 336, 347, 374, 376)),  # インド・南アフリカ・豪州・NZ
}


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
        self._standard: Any = None
        self.standard_model = random.choice(STANDARD_MODELS)
        self._standard_lock = threading.Lock()
        self.standard = False  # 真なら標準的な声で読む（発音の練習）
        self._ready = threading.Thread(target=self._prepare, name="piper-load", daemon=True)
        self._ready.start()

    def _prepare(self) -> None:
        try:
            voice = self._load(PIPER_MODEL)
            speakers: dict[str, int] = voice.config.speaker_id_map
            group = [n for n in ACCENTS.get(self._wanted, ()) if n in speakers]
            name = self._wanted if self._wanted in speakers else random.choice(group or sorted(speakers))
            if self._wanted not in (RANDOM_VOICE, name) and not group:
                logger.warning("talk: piper の話者 %r が無いのでランダムに選びます", self._wanted)
            self._voice, self._speaker, self.speaker_name = voice, speakers[name], name
            accent = next((a for a, names in ACCENTS.items() if name in names), "?")
            logger.info("talk: 英語は piper の話者 %s（%s）で読みます", name, accent)
        except Exception as e:
            self._error = str(e)
            logger.warning("talk: piper を使えません: %s", e)

    def _load(self, model: str) -> Any:
        from piper import PiperVoice
        from piper.download_voices import download_voice
        path = os.path.join(self._dir, model + ".onnx")
        if not os.path.exists(path):
            logger.info("talk: piper のモデル %s をダウンロードします", model)
            os.makedirs(self._dir, exist_ok=True)
            download_voice(model, Path(self._dir))
        return PiperVoice.load(path)

    def _standard_voice(self) -> Any:
        with self._standard_lock:
            if self._standard is None:
                try:
                    self._standard = self._load(self.standard_model)
                except Exception as e:
                    raise TtsError(str(e)) from e
            return self._standard

    def check(self) -> None:
        pass

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        from piper import SynthesisConfig
        if self.standard:
            voice, speaker = self._standard_voice(), None
        else:
            self._ready.join()
            if self._voice is None:
                raise TtsError(self._error)
            voice, speaker = self._voice, self._speaker
        chunks = [c.audio_float_array for c in voice.synthesize(text, SynthesisConfig(speaker_id=speaker))]
        if not chunks:
            raise TtsError(f"piper: empty audio for {text!r}")
        return np.concatenate(chunks).astype(np.float32), int(voice.config.sample_rate)

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
