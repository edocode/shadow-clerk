"""TalkDriver の検証（claude・TTS は偽物）

実行: uv run python tests/test_talk_driver.py
"""
from __future__ import annotations
import sys
from typing import Callable

import numpy as np

from shadow_clerk._daemon_talk import TalkDriver, TalkStartError, one_line
from shadow_clerk._daemon_tts import TtsError
from shadow_clerk.domain import Language, Speaker, TranscriptLine

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Backend:
    LANGUAGES = (Language.JA,)
    DEFAULT_LANGUAGE = Language.JA

    def __init__(self, reachable: bool = True) -> None:
        self.reachable = reachable

    def check(self) -> None:
        if not self.reachable:
            raise TtsError("down")

    def credit(self) -> str:
        return "VOICEVOX:test"

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        return np.zeros(1, dtype=np.float32), 24000


class _Player:
    def __init__(self, on_error: Callable[[str], None]) -> None:
        self.spoken: list[str] = []
        self.closed = False
        self.on_error = on_error

    def speak(self, text: str) -> None:
        self.spoken.append(text)

    def close(self, discard_pending: bool = True) -> None:
        self.closed = True


class _Proc:
    def __init__(self, argv: list[str], workdir: str, on_reply: Callable[[str], None],
                 on_exit: Callable[[int | None], None], fail: bool = False) -> None:
        self.argv, self.on_reply, self.on_exit, self.fail = argv, on_reply, on_exit, fail
        self.workdir = workdir
        self.sent: list[str] = []
        self.stopped = False

    def start(self) -> None:
        if self.fail:
            raise FileNotFoundError("claude")

    def send(self, text: str) -> None:
        self.sent.append(text)

    def stop(self) -> None:
        self.stopped = True


_CONFIG = {"translate_language": "en", "talk_language": "", "claude_cli_path": "claude",
           "talk_allowed_tools": "Read", "talk_model": "", "ai_assistant_workdir": "",
           "talk_personas": {"devil": "反対の立場から話す"}, "talk_default_persona": "devil"}


def _driver(reachable: bool = True, proc_fail: bool = False, **config: object):
    written: list[TranscriptLine] = []
    made: dict = {}

    def player_factory(backend, config, on_error):
        made["player"] = _Player(on_error)
        return made["player"]

    def process_factory(argv, workdir, on_reply, on_exit):
        made["proc"] = _Proc(argv, workdir, on_reply, on_exit, fail=proc_fail)
        return made["proc"]

    d = TalkDriver(written.append, config_loader=lambda: {**_CONFIG, **config},
                   backend_factory=lambda c: _Backend(reachable), player_factory=player_factory,
                   process_factory=process_factory, clock=lambda: "2026-10-02 10:00:00")
    return d, written, made


def _self(text: str) -> TranscriptLine:
    return TranscriptLine("2026-10-02 10:00:00", Speaker.SELF, text)


def test_start_and_kickoff() -> None:
    d, written, made = _driver()
    d.start("新機能の設計", None)
    proc = made["proc"]
    prompt = proc.argv[proc.argv.index("--append-system-prompt") + 1]
    check("開始すると口火を送る", len(proc.sent) == 1, repr(proc.sent))
    check("既定 persona と議題が prompt に入る", "反対の立場から話す" in prompt and "新機能の設計" in prompt)
    check("monitor を抑制する", d.is_suppressed("monitor") and not d.is_suppressed("mic"))
    snap = d.snapshot()
    check("snapshot に状態", snap["active"] and snap["persona"] == "devil" and snap["language"] == "ja"
          and snap["credit"] == "VOICEVOX:test", repr(snap))
    d.start("二度目", None)
    check("二重開始しない", made["proc"] is proc and len(proc.sent) == 1)


def test_reply_and_batching() -> None:
    d, written, made = _driver()
    d.start("", "")
    proc, player = made["proc"], made["player"]
    check("persona 空文字は persona なし", d.snapshot()["persona"] == "")
    d.on_self_line(_self("一つ目"))
    check("生成中は送らずためる", len(proc.sent) == 1)
    d.on_self_line(_self("二つ目"))
    proc.on_reply("最初の質問です。\n- どう思う？")
    check("応答を1行で書く", [(w.speaker, w.text) for w in written]
          == [(Speaker.CLAUDE, "最初の質問です。 - どう思う？")], repr(written))
    check("応答を読み上げに渡す", player.spoken == ["最初の質問です。 - どう思う？"], repr(player.spoken))
    check("ためた行をまとめて送る", proc.sent[-1] == "一つ目\n二つ目", repr(proc.sent))
    proc.on_reply("")
    check("空の応答は書かない", len(written) == 1)
    d.on_self_line(_self("三つ目"))
    check("待機中ならすぐ送る", proc.sent[-1] == "三つ目", repr(proc.sent))


def test_stop() -> None:
    d, written, made = _driver()
    d.start("x", None)
    proc, player = made["proc"], made["player"]
    d.stop()
    check("停止でプロセスと再生を止める", proc.stopped and player.closed)
    check("停止で抑制を解く", not d.is_suppressed("monitor"))
    d.on_self_line(_self("遅れて届いた"))
    proc.on_reply("遅れた応答")
    check("停止後の行と応答は無視", len(proc.sent) == 1 and written == [], repr(written))
    d.stop()
    check("停止は二度呼べる", True)


def test_start_failures() -> None:
    d, _w, made = _driver(reachable=False)
    try:
        d.start("x", None)
        check("VOICEVOX 不達で TalkStartError", False)
    except TalkStartError:
        check("VOICEVOX 不達で TalkStartError", not d.snapshot()["active"] and "proc" not in made)
    d, _w, made = _driver(proc_fail=True)
    try:
        d.start("x", None)
        check("claude 起動失敗で TalkStartError", False)
    except TalkStartError:
        check("claude 起動失敗で TalkStartError", not d.is_suppressed("monitor") and made["player"].closed)


def test_process_exit_and_tts_error() -> None:
    d, _w, made = _driver()
    d.start("x", None)
    made["player"].on_error("synth failed")
    check("TTS の失敗を status に出す", d.snapshot()["error"] == "synth failed", repr(d.snapshot()))
    made["proc"].on_exit(1)
    snap = d.snapshot()
    check("プロセス終了で talk mode を終える", not snap["active"] and not d.is_suppressed("monitor"))
    check("終了理由を残す", "1" in snap["error"], repr(snap))


def test_workdir_resolution() -> None:
    import os
    home = os.path.expanduser("~")
    d, _w, made = _driver(ai_assistant_workdir="~")
    d.start("x", None)
    check("workdir の ~ を展開する", made["proc"].workdir == home, made["proc"].workdir)
    d, _w, made = _driver(ai_assistant_workdir="~/no-such-dir-for-talk-test")
    d.start("x", None)
    check("存在しない workdir はホームに戻す", made["proc"].workdir == home, made["proc"].workdir)


def test_one_line() -> None:
    check("改行・連続空白を1つに", one_line(" a\n\n b\t c ") == "a b c")


if __name__ == "__main__":
    test_start_and_kickoff()
    test_reply_and_batching()
    test_stop()
    test_start_failures()
    test_process_exit_and_tts_error()
    test_workdir_resolution()
    test_one_line()
    sys.exit(0 if all(results) else 1)
