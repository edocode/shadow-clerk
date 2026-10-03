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
from shadow_clerk.domain import Language, TalkVoice

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_split() -> None:
    got = split_sentences("こんにちは。調子はどう？\nいいね! 次へ")
    check("句点・疑問符・改行で分ける", got == ["こんにちは。", "調子はどう？", "いいね!", "次へ"], repr(got))
    check("空白だけは空", split_sentences("  \n ") == [])
    long = "これは句点のないとても長い文で、" * 6 + "最後まで続きます"
    parts = split_sentences(long)
    check("句点のない長い文は読点でも切る", len(parts) > 1 and all(len(x) <= 60 for x in parts)
          and "".join(parts) == long, repr(parts))
    check("短い文は読点で切らない", split_sentences("はい、そうです。") == ["はい、そうです。"])


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
    p = TtsPlayer(_FakeBackend(fail_on="だめ。"), lambda pcm, sr, stop: played.append(float(pcm[0])),
                  errors.append)
    p.speak("あ。だめ。いいい。")
    p.close(discard_pending=False)
    check("失敗した文を飛ばして順に再生する", played == [2.0, 4.0], repr(played))
    check("失敗を on_error に通知する", errors == ["boom"], repr(errors))


def test_on_played() -> None:
    import time
    played: list[tuple[str, float, float]] = []

    def play(pcm: np.ndarray, sr: int, stop: object) -> None:
        if float(pcm[0]) == 4.0:  # 4 文字の文だけ失敗させる
            raise RuntimeError("device gone")
        time.sleep(0.05)

    p = TtsPlayer(_FakeBackend(), play, lambda _m: None)
    p.set_on_played(lambda text, s, e: played.append((text, s, e)))
    t0 = time.time()
    p.speak("あ。かか。いいい。")  # _FakeBackend の PCM 値は文字数: 2, 3, 4 → 4 文字の「いいい。」だけ失敗する
    p.close(discard_pending=False)
    texts = [x[0] for x in played]
    check("鳴らし終えた文ごとに知らせる（失敗した文は除く）", texts == ["あ。", "かか。"], repr(texts))
    check("start <= end で、実際の再生時間を持つ", all(t0 <= s <= e and e - s >= 0.04 for _t, s, e in played), repr(played))

    plays: list[float] = []
    errors: list[str] = []
    p2 = TtsPlayer(_FakeBackend(), lambda pcm, sr, stop: plays.append(float(pcm[0])), errors.append)
    p2.set_on_played(lambda text, s, e: (_ for _ in ()).throw(ValueError("boom")))
    p2.speak("あ。いい。ううう。")
    p2.close(discard_pending=False)
    check("on_played の例外で再生スレッドは止まらない", plays == [2.0, 3.0, 4.0], repr(plays))
    check("on_played の例外は on_error に流さない", errors == [], repr(errors))


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
    synth_body: dict = {}

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
            _MockVoicevox.synth_body = json.loads(body)
            self._reply(_wav_bytes(np.zeros(240, dtype=np.float32), 24000), "audio/wav")


def test_voicevox() -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockVoicevox)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        voice = {"now": TalkVoice(speaker_id=3, speed=1.5, volume=0.5)}
        vv = VoicevoxBackend(url, lambda: voice["now"])
        vv.check()
        pcm, sr = vv.synthesize("テスト")
        check("audio_query → synthesis の順に呼ぶ",
              _MockVoicevox.calls[-2:] == ["POST /audio_query テスト 3", "POST /synthesis  3"],
              repr(_MockVoicevox.calls))
        check("WAV を float32 にデコード", sr == 24000 and pcm.dtype == np.float32 and len(pcm) == 240)
        check("クレジットに話者名", vv.credit() == "VOICEVOX:テスト話者", vv.credit())
        body = _MockVoicevox.synth_body
        check("audio_query の結果を引き継ぐ", body.get("q") == "テスト", repr(body))
        check("話速と音量を上書きする", body.get("speedScale") == 1.5 and body.get("volumeScale") == 0.5, repr(body))
        voice["now"] = TalkVoice(speaker_id=3, speed=0.8)
        vv.synthesize("テスト")
        check("声の設定は文ごとに読み直す", _MockVoicevox.synth_body.get("speedScale") == 0.8)
        check("話者一覧を「キャラ（スタイル）」で返す",
              vv.voices() == [{"id": 3, "name": "テスト話者（ノーマル）"}], repr(vv.voices()))
    finally:
        srv.shutdown()
        srv.server_close()
    try:
        VoicevoxBackend(url, TalkVoice, timeout=1).check()
        check("停止中のエンジンは TtsError", False)
    except TtsError:
        check("停止中のエンジンは TtsError", True)


def test_play_errors_propagate() -> None:
    import shadow_clerk._daemon_tts as tts
    orig = tts._play_one

    def boom(pcm: np.ndarray, sr: int, device: int | None, should_stop: object) -> None:
        raise RuntimeError("device gone")

    tts._play_one = boom
    try:
        tts.play_on_devices([])(np.zeros(10, dtype=np.float32), 24000, lambda: False)
        check("再生スレッドの失敗を呼び出し側に返す", False)
    except RuntimeError as e:
        check("再生スレッドの失敗を呼び出し側に返す", str(e) == "device gone")
    finally:
        tts._play_one = orig


def test_close_discards_queued_audio() -> None:
    import time
    played: list[float] = []

    def slow_play(pcm: np.ndarray, sr: int, stop: object) -> None:
        time.sleep(0.3)
        played.append(float(pcm[0]))

    p = TtsPlayer(_FakeBackend(), slow_play, lambda _m: None)
    p.speak("あ。いい。ううう。ええええ。")
    time.sleep(0.1)
    t0 = time.monotonic()
    p.close()
    elapsed = time.monotonic() - t0
    check("停止で合成済みの音声も捨てる", len(played) <= 1, repr(played))
    check("停止は再生中の1文を待つだけ", elapsed < 0.6, f"{elapsed:.2f}s")


def test_interrupt() -> None:
    import time
    played: list[str] = []
    cut: list[float] = []

    def chunked_play(pcm: np.ndarray, sr: int, should_stop) -> None:
        for _ in range(10):
            if should_stop():
                cut.append(time.monotonic())
                return
            time.sleep(0.05)
        played.append(str(int(pcm[0])))

    p = TtsPlayer(_FakeBackend(), chunked_play, lambda _m: None)
    check("何も話していなければ空", p.interrupt() == "")
    p.speak("あ。いい。ううう。")
    time.sleep(0.15)
    t0 = time.monotonic()
    last = p.interrupt()
    time.sleep(0.3)
    check("止めた時点で話していた文を返す", last == "あ。", repr(last))
    check("再生中の文を途中で止める", cut and cut[0] - t0 < 0.1 and played == [], repr(played))
    p.speak("ええ。")
    p.close(discard_pending=False)
    check("止めたあとも次の文は話せる", played == ["3"], repr(played))


def test_is_busy() -> None:
    import time
    gate = threading.Event()

    def gated_play(pcm: np.ndarray, sr: int, should_stop) -> None:
        while not gate.is_set() and not should_stop():
            time.sleep(0.01)

    def wait_idle(p: TtsPlayer) -> bool:
        deadline = time.monotonic() + 2
        while p.is_busy() and time.monotonic() < deadline:
            time.sleep(0.01)
        return not p.is_busy()

    p = TtsPlayer(_FakeBackend(fail_on="だめ。"), gated_play, lambda _m: None)
    check("何も無ければ busy でない", not p.is_busy())
    p.speak("あ。いい。")
    check("積んだ直後から busy", p.is_busy())
    time.sleep(0.1)
    check("再生中は busy", p.is_busy())
    gate.set()
    check("話し終えたら busy でない", wait_idle(p))
    p.speak("だめ。")
    check("合成に失敗した文も数えて戻す", wait_idle(p))
    gate.clear()
    p.speak("あ。いい。ううう。")
    time.sleep(0.1)
    p.interrupt()
    check("止めたら busy でない", wait_idle(p))
    gate.set()
    p.close()


def test_refresh_waits_for_playback() -> None:
    import time
    from shadow_clerk import _daemon_audio
    th = threading.Thread(target=_daemon_audio.refresh_device_list, daemon=True)
    with _daemon_audio.PORTAUDIO_LOCK:
        th.start()
        time.sleep(0.3)
        check("再生中は PortAudio の再列挙を待たせる", th.is_alive())
    th.join(10)
    check("再生が終われば再列挙する", not th.is_alive())


if __name__ == "__main__":
    test_split()
    test_play_errors_propagate()
    test_close_discards_queued_audio()
    test_interrupt()
    test_is_busy()
    test_refresh_waits_for_playback()
    test_resample()
    test_player_order_and_errors()
    test_on_played()
    test_voicevox()
    sys.exit(0 if all(results) else 1)
