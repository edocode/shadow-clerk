"""console engine（talk コンソール + clerk-talk skill）の検証

実行: uv run python tests/test_talk_engine_console.py
"""
from __future__ import annotations
import sys
import time

from shadow_clerk._daemon_talk_console import ConsoleEngine
from shadow_clerk._daemon_talk_engine import TalkContext, TalkStartError
from shadow_clerk.domain import Language

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Console:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.running = False
        self.workdir = ""
        self.started: list[tuple[list[str], str]] = []
        self.sent: list[str] = []
        self.stopped = False

    def start_if_stopped(self, argv: list[str], workdir: str) -> tuple[bool, bool]:
        if self.running:
            return True, False
        self.started.append((argv, workdir))
        self.running, self.workdir = self.ok, workdir
        return self.ok, self.ok

    def send_after_ready(self, text: str) -> None:
        self.sent.append(text)

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> None:
        self.stopped = True
        self.running = False


def _ctx(ended: list[str], workdir: str = "/tmp/talk-work") -> TalkContext:
    return TalkContext("x", None, Language.JA, workdir, {"ai_assistant_command": "claude", "ai_assistant_args": ""},
                       lambda _t: None, ended.append)


def test_start() -> None:
    con = _Console()
    e = ConsoleEngine(console_factory=lambda: con, skill_check=lambda: True, poll_sec=0.05)
    e.start(_ctx([]))
    check("talk コンソールを ctx の作業ディレクトリで起動する", len(con.started) == 1
          and con.started[0] == (["claude"], "/tmp/talk-work"), repr(con.started))
    check("/clerk-talk を送る", con.sent == ["/clerk-talk\r"], repr(con.sent))
    e.stop()
    check("stop で talk コンソールを止める", con.stopped)
    con = _Console()
    con.running, con.workdir = True, "/tmp/other"
    ConsoleEngine(console_factory=lambda: con, skill_check=lambda: True, poll_sec=0.05).start(_ctx([]))
    check("別の作業ディレクトリで動いていれば起動し直す", con.stopped and con.started == [(["claude"], "/tmp/talk-work")],
          repr(con.started))
    con = _Console()
    con.running, con.workdir = True, "/tmp/talk-work"
    ConsoleEngine(console_factory=lambda: con, skill_check=lambda: True, poll_sec=0.05).start(_ctx([]))
    check("同じ作業ディレクトリならそのまま使う", not con.stopped and con.started == [] and con.sent == ["/clerk-talk\r"])


def test_start_failures() -> None:
    con = _Console()
    try:
        ConsoleEngine(console_factory=lambda: con, skill_check=lambda: False).start(_ctx([]))
        check("skill が無ければ TalkStartError", False)
    except TalkStartError:
        check("skill が無ければ TalkStartError", con.started == [])
    con = _Console(ok=False)
    try:
        ConsoleEngine(console_factory=lambda: con, skill_check=lambda: True).start(_ctx([]))
        check("コンソールを起動できなければ TalkStartError", False)
    except TalkStartError:
        check("コンソールを起動できなければ TalkStartError", con.sent == [])


def test_console_exit() -> None:
    con, ended = _Console(), []
    e = ConsoleEngine(console_factory=lambda: con, skill_check=lambda: True, poll_sec=0.05)
    e.start(_ctx(ended))
    con.running = False
    time.sleep(0.2)
    check("talk コンソールが終わったら ended", len(ended) == 1, repr(ended))
    con, ended = _Console(), []
    e = ConsoleEngine(console_factory=lambda: con, skill_check=lambda: True, poll_sec=0.05)
    e.start(_ctx(ended))
    e.stop()
    time.sleep(0.2)
    check("stop() による終了は知らせない", ended == [])


def test_interrupt() -> None:
    e = ConsoleEngine(console_factory=_Console, skill_check=lambda: True)
    check("制止が無ければ None", e.consume_interrupt() is None)
    e.on_interrupt("途中の文。")
    check("制止の直後は止めた文", e.consume_interrupt() == "途中の文。")
    check("一度返したら解く", e.consume_interrupt() is None)
    e.on_interrupt("")
    check("何も話していなくても制止は伝える", e.consume_interrupt() == "")
    e.on_self_line("何か")
    check("発言は skill が読むので何もしない", e.consume_interrupt() is None)


if __name__ == "__main__":
    test_start()
    test_start_failures()
    test_console_exit()
    test_interrupt()
    sys.exit(0 if all(results) else 1)
