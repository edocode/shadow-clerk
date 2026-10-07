"""Claude への呼びかけ検出と多人数会議での応答の検証

実行: uv run python tests/test_talk_addressed.py
"""
from __future__ import annotations
import sys
import time
from typing import Callable

import numpy as np

from shadow_clerk._daemon_talk import (
    TalkDriver, TalkStartError, _is_addressed_to_claude, stop_pattern)
from shadow_clerk._daemon_tts import TtsError, TtsPlayer
from shadow_clerk.domain import Language, Speaker, TalkVoice, TranscriptLine

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


# ── 偽物の TTS / engine / route ──────────────────────────────────────

class _Backend:
    LANGUAGES = (Language.JA,)
    DEFAULT_LANGUAGE = Language.JA

    def __init__(self) -> None:
        pass

    def check(self) -> None:
        pass

    def credit(self) -> str:
        return "VOICEVOX:test"

    def voices(self) -> list[dict]:
        return [{"id": 1, "name": "テスト"}]

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        return np.zeros(1, dtype=np.float32), 24000


class _Player:
    def __init__(self, on_error: Callable[[str], None]) -> None:
        self.spoken: list[str] = []
        self.speaking = ""
        self.closed = False
        self.on_error = on_error
        self.on_played = None

    def set_on_played(self, fn) -> None:
        self.on_played = fn

    def set_remote(self, remote) -> None:
        pass

    def speak(self, text: str, lang: Language | None = None) -> None:
        self.spoken.append(text)

    def is_busy(self) -> bool:
        return bool(self.speaking)

    def interrupt(self) -> str:
        speaking, self.speaking = self.speaking, ""
        return speaking

    def close(self, discard_pending: bool = True) -> None:
        self.closed = True


class _Engine:
    def __init__(self, name: str) -> None:
        self.name = name
        self.wants_idle_interrupt = False
        self.ctx = None
        self.lines: list[str] = []
        self.cuts: list[str] = []
        self.pending_cut: str | None = None
        self.stopped = False

    def start(self, ctx) -> None:
        self.ctx = ctx

    def stop(self) -> None:
        self.stopped = True

    def on_self_line(self, text: str) -> None:
        self.lines.append(text)

    def on_interrupt(self, cut: str) -> None:
        self.cuts.append(cut)
        self.pending_cut = cut

    def on_held(self, text: str, heard: list[str]) -> None:
        pass

    def consume_interrupt(self) -> str | None:
        cut, self.pending_cut = self.pending_cut, None
        return cut


class _Route:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.connected_to: tuple | None = None
        self.disconnected = False

    def available(self) -> bool:
        return self.ok

    def targets(self) -> list:
        from shadow_clerk.domain import RouteTarget
        return [RouteTarget("Chromium", 10, "Chromium — WebRTC")]

    def connect(self, app: str, source_port: str) -> None:
        self.connected_to = (app, source_port)

    def disconnect(self) -> None:
        self.disconnected = True

    def status(self) -> dict:
        return {"app": "", "connected": False}


class _Sink:
    def start(self) -> str:
        return "shadow-clerk-talk:output_MONO"

    def play(self, pcm, sr, should_stop) -> None:
        pass

    def stop(self) -> None:
        pass


_CONFIG = {"translate_language": "en", "talk_language": "", "talk_engine": "console",
           "talk_filler_sec": 0, "talk_stop_words": ["待って"]}


def _driver(route_factory=None, sink_factory=None, **config):
    written: list[TranscriptLine] = []
    made: dict = {}

    def backend_factory(cfg, voice=None):
        made["backend"] = _Backend()
        return made["backend"]

    def player_factory(backend, cfg, on_error):
        made["player"] = _Player(on_error)
        return made["player"]

    def engine_factory(name):
        made["engine"] = _Engine(name)
        return made["engine"]

    d = TalkDriver(written.append, config_loader=lambda: {**_CONFIG, **config},
                   backend_factory=backend_factory, player_factory=player_factory,
                   engine_factory=engine_factory, clock=lambda: "2026-10-07 10:00:00",
                   route_factory=route_factory or (lambda: _Route(ok=False)),
                   sink_factory=sink_factory or (lambda: _Sink()))
    return d, written, made


def _self(text: str) -> TranscriptLine:
    return TranscriptLine("2026-10-07 10:00:00", Speaker.SELF, text)


def _other(text: str) -> TranscriptLine:
    return TranscriptLine("2026-10-07 10:00:00", Speaker.OTHER, text)


# ── _is_addressed_to_claude の単体テスト ────────────────────────────

def test_is_addressed_to_claude() -> None:
    yes = [
        "Claude、説明して",
        "Claude意見を言って",
        "Claude、調べてください",
        "Claude、どう思う？",
        "Claude、これってどうなんですか？",
        "claudeこれやってくれ",
        "Claude まとめてほしい",
        "Claude、ちょっと教えてみて",
    ]
    no = [
        "Claudeにやらせてます",
        "Claudeが説明しています",
        "Claudeの分析が出ました",
        "さっきClaudeが言ってました",
        "Claudeは今調べています",
        "田中さん、どう思いますか？",
        "Claudeにお願いしてあるので大丈夫です",
        "Claudeが担当しています",
    ]
    for text in yes:
        check(f"依頼として検出: {text!r}", _is_addressed_to_claude(text))
    for text in no:
        check(f"第三者言及として除外: {text!r}", not _is_addressed_to_claude(text))


# ── on_other_line が Claude 宛て依頼を engine に渡す ─────────────────

def test_other_line_addressed_triggers_engine() -> None:
    route, sink = _Route(), _Sink()
    d, _w, made = _driver(route_factory=lambda: route, sink_factory=lambda: sink)
    d.start("x", None, None, "Chromium")
    try:
        d.on_other_line(_other("Claude、このトピックを説明して"))
        time.sleep(0.05)
        check("[相手] の Claude 宛て依頼は engine に渡す", made["engine"].lines == ["Claude、このトピックを説明して"])

        d.on_other_line(_other("Claudeにやらせてます"))
        time.sleep(0.05)
        check("[相手] の第三者言及は engine に渡さない", len(made["engine"].lines) == 1)

        d.on_other_line(_other("田中さん、意見は？"))
        time.sleep(0.05)
        check("[相手] の無関係な発言は engine に渡さない", len(made["engine"].lines) == 1)
    finally:
        d.stop()


def test_other_line_no_route_ignored() -> None:
    """non-routed（1対1）では [相手] 行は Claude 宛てでも engine に渡さない"""
    d, _w, made = _driver()
    d.start("x", None)
    try:
        d.on_other_line(_other("Claude、説明して"))
        time.sleep(0.05)
        check("non-routed では [相手] の依頼も engine に渡さない", made["engine"].lines == [])
    finally:
        d.stop()


# ── on_self_line の routed vs non-routed ──────────────────────────────

def test_self_line_routed_only_responds_when_addressed() -> None:
    """routed（多人数会議）では Claude 宛てのときだけ応答する"""
    route, sink = _Route(), _Sink()
    d, _w, made = _driver(route_factory=lambda: route, sink_factory=lambda: sink)
    d.start("x", None, None, "Chromium")
    try:
        d.on_self_line(_self("田中さん、どう思いますか？"))
        time.sleep(0.05)
        check("routed: 他の人への発言は engine に渡さない", made["engine"].lines == [])

        d.on_self_line(_self("Claudeにやらせてます"))
        time.sleep(0.05)
        check("routed: Claude の第三者言及は engine に渡さない", made["engine"].lines == [])

        d.on_self_line(_self("Claude、意見を言って"))
        time.sleep(0.05)
        check("routed: Claude 宛ての依頼は engine に渡す", made["engine"].lines == ["Claude、意見を言って"])
    finally:
        d.stop()


def test_self_line_non_routed_always_responds() -> None:
    """non-routed（1対1）では [自分] の発言はすべて engine に渡す（従来の動作）"""
    d, _w, made = _driver()
    d.start("x", None)
    try:
        d.on_self_line(_self("田中さん、どう思いますか？"))
        time.sleep(0.05)
        check("non-routed: Claude 宛てでない発言も engine に渡す", made["engine"].lines == ["田中さん、どう思いますか？"])

        d.on_self_line(_self("Claude、説明して"))
        time.sleep(0.05)
        check("non-routed: Claude 宛ての依頼も engine に渡す", len(made["engine"].lines) == 2)
    finally:
        d.stop()


if __name__ == "__main__":
    test_is_addressed_to_claude()
    test_other_line_addressed_triggers_engine()
    test_other_line_no_route_ignored()
    test_self_line_routed_only_responds_when_addressed()
    test_self_line_non_routed_always_responds()
    sys.exit(0 if all(results) else 1)
