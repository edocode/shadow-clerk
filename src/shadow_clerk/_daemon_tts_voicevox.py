"""Shadow-clerk daemon: VOICEVOX エンジン（HTTP）の TTS バックエンド

エンジンは別プロセスで動かす。LGPL のエンジンはこのリポジトリに含めない。
"""
from __future__ import annotations

import io
import json
import logging
import unicodedata
import urllib.error
import urllib.request
import wave
from importlib import resources
from typing import Any, Callable
from urllib.parse import urlencode

import numpy as np

from shadow_clerk._daemon_tts import TtsError
from shadow_clerk.domain import Language, TalkVoice
from shadow_clerk.i18n import t

logger = logging.getLogger("shadow-clerk")


def load_dict_preset() -> list[tuple[str, str, int]]:
    """同梱の読みのプリセット（表記, 読み, アクセント核）"""
    text = resources.files("shadow_clerk").joinpath("voicevox_dict.tsv").read_text(encoding="utf-8")
    return [(c[0], c[1], int(c[2])) for line in text.splitlines()
            if line.strip() and not line.startswith("#") and len(c := line.split("\t")) >= 3]


class VoicevoxBackend:
    LANGUAGES: tuple[Language, ...] = (Language.JA,)
    DEFAULT_LANGUAGE = Language.JA

    def __init__(self, url: str, voice: Callable[[], TalkVoice], timeout: float = 15.0) -> None:
        """voice は文ごとに呼ぶ。会話中に声の設定を変えても次の文から反映される"""
        self._url = url.rstrip("/")
        self._voice = voice
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
        self.sync_dict(load_dict_preset())

    def sync_dict(self, words: list[tuple[str, str, int]]) -> None:
        """エンジンのユーザー辞書に無い表記だけ足す。ユーザーが登録した読みは上書きしない。失敗しても読み上げは続ける"""
        try:
            have = {unicodedata.normalize("NFKC", w.get("surface", ""))
                    for w in json.loads(self._request("/user_dict")).values()}
            for surface, reading, accent in words:
                if unicodedata.normalize("NFKC", surface) not in have:
                    self._request("/user_dict_word?" + urlencode(
                        {"surface": surface, "pronunciation": reading, "accent_type": accent,
                         "word_type": "COMMON_NOUN", "priority": 8}), b"")
                    logger.info("talk: VOICEVOX の辞書に読みを足しました: %s → %s", surface, reading)
        except (TtsError, ValueError, AttributeError) as e:
            logger.warning("talk: VOICEVOX の辞書を更新できません: %s", e)

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        voice = self._voice()
        try:
            query = json.loads(self._request(
                "/audio_query?" + urlencode({"text": text, "speaker": voice.speaker_id}), b""))
        except ValueError as e:
            raise TtsError(str(e)) from e
        query.update(voice.query_overrides())
        wav = self._request(f"/synthesis?speaker={voice.speaker_id}",
                            json.dumps(query, ensure_ascii=False).encode("utf-8"))
        with wave.open(io.BytesIO(wav), "rb") as w:
            frames = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
            pcm = frames.reshape(-1, w.getnchannels())[:, 0].astype(np.float32) / 32768.0
            return pcm, w.getframerate()

    def voices(self) -> list[dict[str, Any]]:
        """話者とスタイルの一覧。届かなければ TtsError"""
        try:
            return [{"id": st["id"], "name": f"{sp['name']}（{st['name']}）"}
                    for sp in json.loads(self._request("/speakers")) for st in sp.get("styles", [])]
        except (ValueError, KeyError, TypeError) as e:
            raise TtsError(str(e)) from e

    def credit(self) -> str:
        """利用規約が求めるクレジット表記（VOICEVOX:キャラ名）。取れなければ VOICEVOX だけ"""
        speaker_id = self._voice().speaker_id
        try:
            for sp in json.loads(self._request("/speakers")):
                if any(st.get("id") == speaker_id for st in sp.get("styles", [])):
                    return f"VOICEVOX:{sp['name']}"
        except (TtsError, ValueError, KeyError, TypeError) as e:
            logger.debug("talk: VOICEVOX の話者名を取れません: %s", e)
        return "VOICEVOX"
