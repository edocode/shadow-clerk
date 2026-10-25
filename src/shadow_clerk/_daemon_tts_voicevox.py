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
from collections.abc import Iterator
from importlib import resources
from typing import Any, Callable
from urllib.parse import urlencode

import numpy as np

from shadow_clerk._daemon_tts import TtsError
from shadow_clerk.domain import Language, TalkVoice
from shadow_clerk.i18n import t

logger = logging.getLogger("shadow-clerk")

_STREAM_CHUNK_BYTES = 2048


def _parse_wav_stream_header(resp: Any) -> tuple[int, int, int]:
    """resp から WAV ヘッダーを読み (sample_rate, channels, bits_per_sample) を返す"""
    def _read(n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = resp.read(n - len(buf))
            if not chunk:
                raise TtsError("ストリーミング合成: WAV ヘッダーが途切れました")
            buf += chunk
        return buf

    header = _read(12)
    if header[:4] != b"RIFF" or header[8:12] != b"WAVE":
        raise TtsError("ストリーミング合成: WAVE ヘッダーが不正です")
    sr = channels = bits = 0
    while True:
        chunk_hdr = _read(8)
        chunk_id = chunk_hdr[:4]
        chunk_size = int.from_bytes(chunk_hdr[4:], "little")
        if chunk_id == b"fmt ":
            fmt = _read(chunk_size)
            channels = int.from_bytes(fmt[2:4], "little")
            sr = int.from_bytes(fmt[4:8], "little")
            bits = int.from_bytes(fmt[14:16], "little")
            if chunk_size % 2:
                _read(1)
        elif chunk_id == b"data":
            if not sr:
                raise TtsError("ストリーミング合成: data チャンクより前に fmt が見つかりません")
            return sr, channels, bits
        else:
            _read(chunk_size + chunk_size % 2)


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

    def synthesize_stream(self, text: str) -> tuple[Iterator[np.ndarray], int]:
        """ストリーミング合成。WAV ヘッダー解析後すぐに返り、PCM float32 チャンクを yield するイテレータを返す。
        /streaming_synthesis エンドポイントが無い場合は TtsError を送出する。"""
        voice = self._voice()
        try:
            query = json.loads(self._request(
                "/audio_query?" + urlencode({"text": text, "speaker": voice.speaker_id}), b""))
        except ValueError as e:
            raise TtsError(str(e)) from e
        query.update(voice.query_overrides())

        url = f"{self._url}/streaming_synthesis?speaker={voice.speaker_id}"
        body = json.dumps(query, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self._timeout)
        except (urllib.error.URLError, OSError) as e:
            raise TtsError(t("talk.voicevox_unreachable", url=self._url, error=str(e))) from e

        try:
            sr, channels, bits = _parse_wav_stream_header(resp)
        except TtsError:
            resp.close()
            raise

        frame_bytes = bits // 8 * channels
        dtype = "<i2" if bits == 16 else "<i4"
        divisor = float(1 << (bits - 1))

        def _chunks() -> Iterator[np.ndarray]:
            buf = b""
            try:
                while raw := resp.read(_STREAM_CHUNK_BYTES):
                    buf += raw
                    n = len(buf) // frame_bytes * frame_bytes
                    if n:
                        frames = np.frombuffer(buf[:n], dtype=dtype)
                        buf = buf[n:]
                        yield frames[::channels].astype(np.float32) / divisor
            finally:
                resp.close()

        return _chunks(), sr

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
