"""Shadow-clerk daemon: VOICEVOX エンジン（HTTP）の TTS バックエンド

エンジンは別プロセスで動かす。LGPL のエンジンはこのリポジトリに含めない。
"""
from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.request
import wave
from urllib.parse import urlencode

import numpy as np

from shadow_clerk._daemon_tts import TtsError
from shadow_clerk.domain import Language
from shadow_clerk.i18n import t

logger = logging.getLogger("shadow-clerk")


class VoicevoxBackend:
    LANGUAGES = (Language.JA,)
    DEFAULT_LANGUAGE = Language.JA

    def __init__(self, url: str, speaker_id: int, timeout: float = 15.0) -> None:
        self._url = url.rstrip("/")
        self._speaker = speaker_id
        self._timeout = timeout

    def _request(self, path: str, body: bytes | None = None) -> bytes:
        req = urllib.request.Request(f"{self._url}{path}", data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return resp.read()
        except (urllib.error.URLError, OSError) as e:
            raise TtsError(t("talk.voicevox_unreachable", url=self._url, error=str(e))) from e

    def check(self) -> None:
        self._request("/version")

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        query = self._request("/audio_query?" + urlencode({"text": text, "speaker": self._speaker}), b"")
        wav = self._request(f"/synthesis?speaker={self._speaker}", query)
        with wave.open(io.BytesIO(wav), "rb") as w:
            frames = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
            pcm = frames.reshape(-1, w.getnchannels())[:, 0].astype(np.float32) / 32768.0
            return pcm, w.getframerate()

    def credit(self) -> str:
        """利用規約が求めるクレジット表記（VOICEVOX:キャラ名）。取れなければ VOICEVOX だけ"""
        try:
            for sp in json.loads(self._request("/speakers")):
                if any(st.get("id") == self._speaker for st in sp.get("styles", [])):
                    return f"VOICEVOX:{sp['name']}"
        except (TtsError, ValueError, KeyError, TypeError) as e:
            logger.debug("talk: VOICEVOX の話者名を取れません: %s", e)
        return "VOICEVOX"
