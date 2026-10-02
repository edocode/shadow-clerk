"""TTS パイプラインと VOICEVOX バックエンドの検証

実行: uv run python tests/test_tts.py
"""
from __future__ import annotations
import io
import json
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

from shadow_clerk._daemon_tts import TtsError, TtsPlayer, resample, split_sentences
from shadow_clerk._daemon_tts_voicevox import VoicevoxBackend
from shadow_clerk.domain import Language

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_split() -> None:
    got = split_sentences("こんにちは。調子はどう？\nいいね! 次へ")
    check("句点・疑問符・改行で分ける", got == ["こんにちは。", "調子はどう？", "いいね!", "次へ"], repr(got))
    check("空白だけは空", split_sentences("  \n ") == [])


def test_resample() -> None:
    pcm = np.linspace(-1, 1, 24000, dtype=np.float32)
    out = resample(pcm, 24000, 48000)
    check("長さが比率どおり", len(out) == 48000, str(len(out)))
    check("dtype は float32", out.dtype == np.float32)
    check("同じレートはそのまま", resample(pcm, 24000, 24000) is pcm)


class _FakeBackend:
    LANGUAGES = (Language.JA,)
    DEFAULT_LANGUAGE = Language.JA

    def __init__(self, fail_on: str = "") -> None:
        self.fail_on = fail_on

    def check(self) -> None:
        pass

    def credit(self) -> str:
        return "fake"

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        if text == self.fail_on:
            raise TtsError("boom")
        return np.full(10, len(text), dtype=np.float32), 24000


def test_player_order_and_errors() -> None:
    played: list[float] = []
    errors: list[str] = []
    p = TtsPlayer(_FakeBackend(fail_on="だめ。"), lambda pcm, sr: played.append(float(pcm[0])),
                  errors.append)
    p.speak("あ。だめ。いいい。")
    p.close(discard_pending=False)
    check("失敗した文を飛ばして順に再生する", played == [2.0, 4.0], repr(played))
    check("失敗を on_error に通知する", errors == ["boom"], repr(errors))


def _wav_bytes(samples: np.ndarray, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((samples * 32767).astype("<i2").tobytes())
    return buf.getvalue()


class _MockVoicevox(BaseHTTPRequestHandler):
    calls: list[str] = []

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _reply(self, body: bytes, ctype: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        u = urlparse(self.path)
        self.calls.append(f"GET {u.path}")
        if u.path == "/version":
            self._reply(b'"0.0.0"', "application/json")
        elif u.path == "/speakers":
            body = [{"name": "テスト話者", "styles": [{"id": 3, "name": "ノーマル"}]}]
            self._reply(json.dumps(body).encode(), "application/json")

    def do_POST(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        self.calls.append(f"POST {u.path} {q.get('text', [''])[0]} {q.get('speaker', [''])[0]}")
        if u.path == "/audio_query":
            self._reply(json.dumps({"q": q["text"][0]}).encode(), "application/json")
        elif u.path == "/synthesis":
            assert json.loads(body)["q"] == "テスト"
            self._reply(_wav_bytes(np.zeros(240, dtype=np.float32), 24000), "audio/wav")


def test_voicevox() -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockVoicevox)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        vv = VoicevoxBackend(url, 3)
        vv.check()
        pcm, sr = vv.synthesize("テスト")
        check("audio_query → synthesis の順に呼ぶ",
              _MockVoicevox.calls[-2:] == ["POST /audio_query テスト 3", "POST /synthesis  3"],
              repr(_MockVoicevox.calls))
        check("WAV を float32 にデコード", sr == 24000 and pcm.dtype == np.float32 and len(pcm) == 240)
        check("クレジットに話者名", vv.credit() == "VOICEVOX:テスト話者", vv.credit())
    finally:
        srv.shutdown()
        srv.server_close()
    try:
        VoicevoxBackend(url, 3, timeout=1).check()
        check("停止中のエンジンは TtsError", False)
    except TtsError:
        check("停止中のエンジンは TtsError", True)


if __name__ == "__main__":
    test_split()
    test_resample()
    test_player_order_and_errors()
    test_voicevox()
    sys.exit(0 if all(results) else 1)
