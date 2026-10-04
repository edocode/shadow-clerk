"""練習言語の文をブラウザで読む仕組み（SpeechTab / BrowserSpeech）の検証

実行: uv run python tests/test_talk_speech.py
ブラウザもダッシュボードも不要。SSE の送り口は偽物で、タブの done もここから返す。
"""
from __future__ import annotations
import json
import os
import sys
import threading
import time

import numpy as np

from shadow_clerk._daemon_talk import TalkDriver
from shadow_clerk._daemon_talk_speech import BrowserSpeech
from shadow_clerk._daemon_tts import TtsPlayer
from shadow_clerk.domain import Language, SpeechTab, Speaker, TranscriptLine, estimate_speech_sec

# talk mode の偽物（engine・経路・pw-cat）は TalkDriver の検証と同じものを使う
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_talk_driver import _CONFIG, _Engine, _Route, _Sink  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def _tab(tab: str, *langs: str) -> SpeechTab:
    return SpeechTab(tab, frozenset(Language(x) for x in langs))


class _Bus:
    """SSE の送り口の代役。送ったものを溜め、ack 秒後にタブの done を返す（None なら返さない＝タブが閉じた）"""

    def __init__(self, speech: BrowserSpeech, ack: float | None = 0.05, events: list[str] | None = None) -> None:
        self.speech, self.ack = speech, ack
        self.events = events if events is not None else []
        self.sent: list[tuple[str, dict]] = []

    def __call__(self, event: str, data: str) -> None:
        d = json.loads(data)
        self.sent.append((event, d))
        if event == "talk_speak":
            self.events.append("browser:" + d["text"])
            if self.ack is not None:
                threading.Timer(self.ack, self.speech.done, args=(d["id"],)).start()

    def of(self, event: str) -> list[dict]:
        return [d for e, d in self.sent if e == event]


def _speech(ack: float | None = 0.05, **kw: float) -> tuple[BrowserSpeech, _Bus]:
    sp = BrowserSpeech(**kw)
    bus = _Bus(sp, ack)
    sp.set_broadcaster(bus)
    return sp, bus


def test_speech_tab_parse() -> None:
    tab = SpeechTab.parse({"tab": "t1abc", "langs": ["en", "ja", "sw", "en-US", 3]})
    check("知らない言語コードは捨てる", tab == _tab("t1abc", "en", "ja"), repr(tab))
    check("空の langs は取り下げ", SpeechTab.parse({"tab": "t1", "langs": []}).langs == frozenset())
    for raw, label in [({"tab": "", "langs": []}, "空の tab"), ({"tab": "a b", "langs": []}, "空白入りの tab"),
                       ({"tab": "x" * 65, "langs": []}, "長すぎる tab"), ({"tab": 1, "langs": []}, "数値の tab"),
                       ({"tab": "t1", "langs": "en"}, "list でない langs"), ([], "object でない body")]:
        try:
            SpeechTab.parse(raw)
            check(f"{label}は ValueError", False)
        except ValueError:
            check(f"{label}は ValueError", True)
    check("見積もりは 1 秒 8 文字", estimate_speech_sec("x" * 16) == 2.0)


def test_speak_waits_for_done() -> None:
    sp, bus = _speech(ack=0.2)
    check("名乗るタブが無ければ送らない", not sp.speak("Hello.", Language.EN, lambda: False) and bus.sent == [])
    sp.ready(_tab("tabA", "en"))
    check("声のある言語だけ読める", sp.can_speak(Language.EN) and not sp.can_speak(Language.FR))
    t0 = time.monotonic()
    ok = sp.speak("Hello.", Language.EN, lambda: False)
    took = time.monotonic() - t0
    check("done まで返らない", ok and 0.15 <= took < 1.0, f"{took:.2f}s")
    check("文・言語・宛先のタブを送る", bus.of("talk_speak") == [{"id": "s1", "tab": "tabA", "text": "Hello.", "lang": "en"}],
          repr(bus.sent))
    check("終えた文の done は知らない", not sp.done("s1"))


def test_timeout_moves_on_and_forgets_tab() -> None:
    sp, bus = _speech(ack=None, grace_sec=0.1)
    sp.ready(_tab("tabA", "en"))
    t0 = time.monotonic()
    ok = sp.speak("Hello.", Language.EN, lambda: False)
    took = time.monotonic() - t0
    est = estimate_speech_sec("Hello.")
    check("done が来なければ見積もり + 猶予で次へ進む", ok and est <= took < est + 1.0, f"{took:.2f}s")
    check("終わらなかったタブは以後使わない（VOICEVOX に戻す）", not sp.can_speak(Language.EN))
    sp.ready(_tab("tabA", "en"))
    check("名乗り直せばまた使う", sp.can_speak(Language.EN))


def test_ready_expires_and_withdraws() -> None:
    sp, _bus = _speech(ttl_sec=0.2)
    sp.ready(_tab("tabA", "en"))
    time.sleep(0.3)
    check("名乗りが途絶えたら使わない", not sp.can_speak(Language.EN))
    sp.ready(_tab("tabA", "en"))
    sp.ready(_tab("tabB", "en"))
    sp.ready(_tab("tabA"))
    check("別のタブの取り下げでは消えない", sp.can_speak(Language.EN))
    sp.ready(_tab("tabB"))
    check("使っているタブが取り下げたら使わない", not sp.can_speak(Language.EN))


def test_two_tabs_last_one_wins() -> None:
    sp, bus = _speech(ack=None)
    sp.ready(_tab("tabA", "en"))
    sp.ready(_tab("tabB", "en"))
    stop = threading.Event()
    th = threading.Thread(target=sp.speak, args=("Hello there.", Language.EN, stop.is_set), daemon=True)
    th.start()
    time.sleep(0.2)
    sp.ready(_tab("tabA", "en"))  # 文の途中で、もう1つのタブが名乗り直す
    stop.set()
    th.join(2)
    speak, cancel = bus.of("talk_speak"), bus.of("talk_speak_cancel")
    check("最後に名乗ったタブだけに送る", [d["tab"] for d in speak] == ["tabB"], repr(speak))
    check("止めるときは読んでいるタブに送る", cancel == [{"id": speak[0]["id"], "tab": "tabB"}], repr(cancel))
    check("止めたら速やかに返る", not th.is_alive())


# --- TalkDriver: /api/say の lang で読む先を分ける ---

class _TextBackend:
    """合成した文を覚える VOICEVOX の代役。PCM の値が文の番号"""
    LANGUAGES = (Language.JA,)
    DEFAULT_LANGUAGE = Language.JA

    def __init__(self) -> None:
        self.texts: list[str] = []

    def check(self) -> None:
        pass

    def credit(self) -> str:
        return "VOICEVOX:test"

    def voices(self) -> list[dict]:
        return []

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        self.texts.append(text)
        return np.array([len(self.texts) - 1], dtype=np.float32), 24000


class _RecSink(_Sink):
    """届け先ありの talk mode の pw-cat。鳴らした文を events に残す"""

    def __init__(self, events: list[str], backend: _TextBackend) -> None:
        super().__init__()
        self.events, self.backend = events, backend

    def play(self, pcm, sr, should_stop) -> None:
        self.events.append("vv:" + self.backend.texts[int(pcm[0])])


def _talk(ack: float | None = 0.05, route: bool = False):
    backend, events, made = _TextBackend(), [], {}
    speech = BrowserSpeech()
    bus = _Bus(speech, ack, events)

    def play(pcm, sr, should_stop) -> None:
        events.append("vv:" + backend.texts[int(pcm[0])])

    def player_factory(b, cfg, on_error):
        made["player"] = TtsPlayer(b, play, on_error)
        return made["player"]

    def engine_factory(name):
        made["engine"] = _Engine(name)
        return made["engine"]

    sink = _RecSink(events, backend)
    d = TalkDriver(lambda _l: None, config_loader=lambda: dict(_CONFIG), backend_factory=lambda cfg, v=None: backend,
                   player_factory=player_factory, engine_factory=engine_factory,
                   route_factory=lambda: _Route(ok=route), sink_factory=lambda: sink, speech=speech)
    d.set_broadcaster(bus)
    return d, events, made, bus


def _wait(cond, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_driver_routes_by_lang() -> None:
    d, events, made, bus = _talk()
    d.speech_ready(_tab("tabA", "en"))
    d.start("x", None)
    d.say("説明です。")
    d.api_say("They are there.", Language.EN)
    d.say("次です。")
    d.say("日本語です。", Language.JA)
    _wait(lambda: len(events) == 4 and not made["player"].is_busy())
    check("lang 付きの文だけブラウザへ、送った順に鳴る",
          events == ["vv:説明です。", "browser:They are there.", "vv:次です。", "vv:日本語です。"], repr(events))
    check("待っていない文の done は False", not d.speech_done("s1"))
    d.stop()


def test_driver_falls_back_without_tab() -> None:
    d, events, made, bus = _talk()
    d.start("x", None)
    d.say("Hello.", Language.EN)
    _wait(lambda: events)
    check("名乗ったタブが無ければ VOICEVOX で読む", events == ["vv:Hello."] and bus.sent == [], repr(events))
    d.stop()
    d2, events2, _m, bus2 = _talk()
    d2.speech_ready(_tab("tabA", "en"))
    d2.say("Hello.", Language.EN)
    _wait(lambda: events2)
    check("talk mode の外では lang を見ない", events2 == ["vv:Hello."] and bus2.sent == [], repr(events2))


def test_driver_route_ignores_lang() -> None:
    d, events, made, bus = _talk(route=True)
    d.speech_ready(_tab("tabA", "en"))
    d.start("x", None, None, "Chromium")
    d.say("Hello.", Language.EN)
    _wait(lambda: events)
    check("届け先ありでは lang を無視して VOICEVOX", events == ["vv:Hello."] and bus.sent == [], repr(events))
    d.stop()


def test_driver_stop_word_cancels_browser_sentence() -> None:
    d, events, made, bus = _talk(ack=None)
    d.speech_ready(_tab("tabA", "en"))
    d.start("x", None)
    d.say("This is a long sentence.", Language.EN)
    _wait(lambda: bus.of("talk_speak"))
    time.sleep(0.1)
    check("ブラウザが読んでいる間は busy", made["player"].is_busy())
    d.on_self_line(TranscriptLine("2026-10-04 10:00:00", Speaker.SELF, "待って"))
    _wait(lambda: bus.of("talk_speak_cancel"))
    sent = bus.of("talk_speak")[0]
    check("制止でタブに cancel を送る", bus.of("talk_speak_cancel") == [{"id": sent["id"], "tab": "tabA"}],
          repr(bus.sent))
    check("止めた文を engine に渡す", made["engine"].cuts == ["This is a long sentence."], repr(made["engine"].cuts))
    check("止めたら busy でない", _wait(lambda: not made["player"].is_busy(), 1.0))
    d.stop()


if __name__ == "__main__":
    test_speech_tab_parse()
    test_speak_waits_for_done()
    test_timeout_moves_on_and_forgets_tab()
    test_ready_expires_and_withdraws()
    test_two_tabs_last_one_wins()
    test_driver_routes_by_lang()
    test_driver_falls_back_without_tab()
    test_driver_route_ignores_lang()
    test_driver_stop_word_cancels_browser_sentence()
    sys.exit(0 if all(results) else 1)
