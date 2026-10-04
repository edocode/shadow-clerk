"""練習言語の文をブラウザで読む仕組み（SpeechTab / BrowserSpeech）の検証

実行: uv run python tests/test_talk_speech.py
ブラウザもダッシュボードも不要。SSE の送り口は偽物で、タブの done もここから返す。
"""
from __future__ import annotations
import json
import sys
import threading
import time

from shadow_clerk._daemon_talk_speech import BrowserSpeech
from shadow_clerk.domain import Language, SpeechTab, estimate_speech_sec

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


if __name__ == "__main__":
    test_speech_tab_parse()
    test_speak_waits_for_done()
    test_timeout_moves_on_and_forgets_tab()
    test_ready_expires_and_withdraws()
    test_two_tabs_last_one_wins()
    sys.exit(0 if all(results) else 1)
