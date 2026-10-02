"""TalkDriver（共通部分）の検証。TTS と engine は偽物

実行: uv run python tests/test_talk_driver.py
"""
from __future__ import annotations
import sys
import time
from typing import Callable

import numpy as np

from shadow_clerk._daemon_talk import TalkDriver, TalkStartError, one_line, stop_pattern
from shadow_clerk._daemon_tts import TtsError
from shadow_clerk.domain import Language, Speaker, TalkVoice, TranscriptLine

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Backend:
    LANGUAGES = (Language.JA,)
    DEFAULT_LANGUAGE = Language.JA

    def __init__(self, reachable: bool = True, voice: TalkVoice | None = None) -> None:
        self.reachable, self.voice = reachable, voice

    def check(self) -> None:
        if not self.reachable:
            raise TtsError("down")

    def credit(self) -> str:
        return "VOICEVOX:test"

    def voices(self) -> list[dict]:
        return [{"id": 3, "name": "テスト（ノーマル）"}]

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        return np.zeros(1, dtype=np.float32), 24000


class _Player:
    def __init__(self, on_error: Callable[[str], None]) -> None:
        self.spoken: list[str] = []
        self.closed = False
        self.on_error = on_error
        self.speaking = ""
        self.interrupts = 0

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def interrupt(self) -> str:
        self.interrupts += 1
        speaking, self.speaking = self.speaking, ""
        return speaking

    def close(self, discard_pending: bool = True) -> None:
        self.closed = True


class _Engine:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name, self.fail = name, fail
        self.ctx = None
        self.lines: list[str] = []
        self.cuts: list[str] = []
        self.pending_cut: str | None = None
        self.stopped = False

    def start(self, ctx) -> None:
        if self.fail:
            raise TalkStartError("engine down")
        self.ctx = ctx

    def stop(self) -> None:
        self.stopped = True

    def on_self_line(self, text: str) -> None:
        self.lines.append(text)

    def on_interrupt(self, cut: str) -> None:
        self.cuts.append(cut)
        self.pending_cut = cut

    def consume_interrupt(self) -> str | None:
        cut, self.pending_cut = self.pending_cut, None
        return cut


_CONFIG = {"translate_language": "en", "talk_language": "", "talk_engine": "console",
           "talk_personas": {"devil": "反対の立場から話す"}, "talk_default_persona": "devil",
           "talk_filler_sec": 0, "talk_stop_words": ["待って", "stop", "wait"]}


def _driver(reachable: bool = True, engine_fail: bool = False, **config: object):
    written: list[TranscriptLine] = []
    made: dict = {}

    def backend_factory(cfg, voice=None):
        made["backend"] = _Backend(reachable, voice)
        return made["backend"]

    def player_factory(backend, cfg, on_error):
        made["player"] = _Player(on_error)
        return made["player"]

    def engine_factory(name):
        made["engine"] = _Engine(name, engine_fail)
        return made["engine"]

    d = TalkDriver(written.append, config_loader=lambda: {**_CONFIG, **config},
                   backend_factory=backend_factory, player_factory=player_factory,
                   engine_factory=engine_factory, clock=lambda: "2026-10-03 10:00:00")
    return d, written, made


def _self(text: str) -> TranscriptLine:
    return TranscriptLine("2026-10-03 10:00:00", Speaker.SELF, text)


def test_start_and_context() -> None:
    d, _w, made = _driver(talk_engine="headless")
    d.start("新機能の設計", None)
    ctx = made["engine"].ctx
    check("設定の engine を使う", made["engine"].name == "headless")
    check("engine に議題・persona・言語を渡す", ctx.topic == "新機能の設計" and ctx.persona.name == "devil"
          and ctx.language == Language.JA)
    snap = d.snapshot()
    check("snapshot に engine と persona 本文", snap["engine"] == "headless"
          and snap["persona_instructions"] == "反対の立場から話す" and snap["active"], repr(snap))
    check("monitor を抑制する", d.is_suppressed("monitor") and not d.is_suppressed("mic"))
    first = made["engine"]
    d.start("二度目", None)
    check("二重開始しない", made["engine"] is first)


def test_start_failures() -> None:
    d, _w, made = _driver(reachable=False)
    try:
        d.start("x", None)
        check("VOICEVOX 不達で TalkStartError", False)
    except TalkStartError:
        check("VOICEVOX 不達で TalkStartError", "engine" not in made and not d.active)
    d, _w, made = _driver(engine_fail=True)
    try:
        d.start("x", None)
        check("engine の起動失敗で TalkStartError", False)
    except TalkStartError:
        check("engine の起動失敗で TalkStartError", made["player"].closed and not d.is_suppressed("monitor"))


def test_engine_say_and_end() -> None:
    d, written, made = _driver()
    d.start("x", None)
    made["engine"].ctx.say("こんにちは。\n- どうですか？")
    check("engine の say は1行で書いて話す", [w.text for w in written] == ["こんにちは。 - どうですか？"]
          and made["player"].spoken == ["こんにちは。 - どうですか？"], repr(written))
    made["engine"].ctx.ended("console exited")
    check("engine が終わったら talk mode を終える", not d.active and made["engine"].stopped
          and made["player"].closed and d.snapshot()["error"] == "console exited")
    made["engine"].ctx.say("遅れた発話")
    check("終了後の engine の say は無視", len(written) == 1)


def test_self_lines_and_stop_words() -> None:
    d, _w, made = _driver()
    d.start("x", None)
    eng, player = made["engine"], made["player"]
    d.on_self_line(_self("うん"))
    check("[自分] 行を engine に渡す", eng.lines == ["うん"] and player.interrupts == 0)
    player.speaking = "長い説明です。"
    d.on_self_line(_self("ちょっと待って"))
    check("制止で読み上げを止め engine に知らせる", player.interrupts == 1 and eng.cuts == ["長い説明です。"]
          and eng.lines[-1] == "ちょっと待って", repr(eng.cuts))
    d.on_self_line(_self("the waiter came"))
    check("英語は単語で照合", player.interrupts == 1)
    d.stop()
    d.on_self_line(_self("終了後"))
    check("終了後の行は渡さない", eng.lines[-1] == "the waiter came")


def test_api_say() -> None:
    d, written, made = _driver()
    check("talk mode 外でも話せる", d.api_say("テスト") is None and written[-1].text == "テスト")
    d.start("x", None)
    made["engine"].pending_cut = "途中の文。"
    check("制止の直後は話さずに止めた文を返す", d.api_say("続き") == "途中の文。" and written[-1].text == "テスト")
    check("2回目からは話す", d.api_say("どうぞ") is None and written[-1].text == "どうぞ")


def test_filler() -> None:
    d, written, made = _driver(talk_filler_sec=0.05)
    d.start("x", None)
    time.sleep(0.25)
    check("開始後に話さなければつなぎを話す", made["player"].spoken == ["ちょっと考えます。"], repr(made["player"].spoken))
    check("つなぎは transcript に書かない", written == [])
    d, written, made = _driver(talk_filler_sec=0.2)
    d.start("x", None)
    d.on_self_line(_self("質問です"))
    d.api_say("答えです。")
    time.sleep(0.35)
    check("話していればつなぎは入れない", made["player"].spoken == ["答えです。"], repr(made["player"].spoken))


def test_workdir() -> None:
    import os
    import tempfile
    home = os.path.expanduser("~")
    d, _w, made = _driver()
    d.start("x", None)
    check("指定が無ければ設定、それも無ければホーム", made["engine"].ctx.workdir == home
          and d.snapshot()["workdir"] == home, made["engine"].ctx.workdir)
    with tempfile.TemporaryDirectory() as tmp:
        d, _w, made = _driver(talk_workdir=tmp)
        d.start("x", None)
        check("talk_workdir を使う", made["engine"].ctx.workdir == tmp)
        d, _w, made = _driver(talk_workdir=tmp)
        d.start("x", None, "~")
        check("開始時の指定を優先し ~ を展開する", made["engine"].ctx.workdir == home)
    d, _w, made = _driver()
    try:
        d.start("x", None, "/no/such/dir-for-talk-test")
        check("存在しない指定は TalkStartError", False)
    except TalkStartError:
        check("存在しない指定は TalkStartError", "engine" not in made and not d.active)


def test_unknown_engine_name_is_passed_through() -> None:
    d, _w, made = _driver(talk_engine="nope")
    d.start("x", None)
    check("engine 名はそのまま factory へ（解釈は make_engine）", made["engine"].name == "nope")


def test_preview_and_voices() -> None:
    d, written, made = _driver()
    d.preview(TalkVoice(speaker_id=5, speed=1.4), "試しに読みます")
    check("試聴は渡した声で、transcript に書かない", made["backend"].voice == TalkVoice(speaker_id=5, speed=1.4)
          and made["player"].spoken == ["試しに読みます"] and written == [])
    check("話者一覧を返す", d.voices() == [{"id": 3, "name": "テスト（ノーマル）"}])


def test_helpers() -> None:
    check("改行・連続空白を1つに", one_line(" a\n\n b\t c ") == "a b c")
    check("制止の言葉が無ければ None", stop_pattern([]) is None and stop_pattern("x") is None)


if __name__ == "__main__":
    test_start_and_context()
    test_start_failures()
    test_engine_say_and_end()
    test_self_lines_and_stop_words()
    test_api_say()
    test_filler()
    test_workdir()
    test_unknown_engine_name_is_passed_through()
    test_preview_and_voices()
    test_helpers()
    sys.exit(0 if all(results) else 1)
