"""headless engine（claude -p の常駐プロセス）の検証

実行: uv run python tests/test_talk_engine_headless.py
"""
from __future__ import annotations
import sys
from typing import Callable

from shadow_clerk._daemon_talk_engine import TalkContext, TalkStartError
from shadow_clerk._daemon_talk_headless import HeadlessEngine
from shadow_clerk.domain import Language, TalkPersona

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Proc:
    def __init__(self, argv: list[str], workdir: str, on_text: Callable[[str], None],
                 on_turn_end: Callable[[bool], None], on_exit: Callable[[int | None], None],
                 fail: bool = False, exit_on_start: bool = False) -> None:
        self.argv, self.workdir, self.on_text, self.on_turn_end, self.on_exit = argv, workdir, on_text, on_turn_end, on_exit
        self.fail, self.exit_on_start = fail, exit_on_start
        self.sent: list[str] = []
        self.stopped = False

    def start(self) -> None:
        if self.fail:
            raise FileNotFoundError("claude")
        if self.exit_on_start:
            self.on_exit(1)  # 起動直後に落ちた claude（start() の中で読み取りスレッドが終了を見る）

    def send(self, text: str) -> None:
        self.sent.append(text)

    def stop(self) -> None:
        self.stopped = True


_CONFIG = {"claude_cli_path": "claude", "talk_allowed_tools": "Read", "talk_model": ""}


def _engine(fail: bool = False, exit_on_start: bool = False):
    made: dict = {}

    def factory(argv, workdir, on_text, on_turn_end, on_exit):
        made["proc"] = _Proc(argv, workdir, on_text, on_turn_end, on_exit, fail, exit_on_start)
        return made["proc"]

    said: list[str] = []
    ended: list[str] = []
    ctx = TalkContext("新機能の設計", TalkPersona("devil", "反対の立場から話す"), Language.JA,
                      "/tmp/talk-work", _CONFIG, said.append, ended.append)
    return HeadlessEngine(process_factory=factory), ctx, made, said, ended


def test_start() -> None:
    e, ctx, made, _s, _e = _engine()
    e.start(ctx)
    proc = made["proc"]
    prompt = proc.argv[proc.argv.index("--append-system-prompt") + 1]
    check("口火を送る", len(proc.sent) == 1)
    check("persona と議題が prompt に入る", "反対の立場から話す" in prompt and "新機能の設計" in prompt)
    check("ctx の作業ディレクトリで起動する", proc.workdir == "/tmp/talk-work", proc.workdir)
    e, ctx, _m, _s, _e = _engine(fail=True)
    try:
        e.start(ctx)
        check("起動できなければ TalkStartError", False)
    except TalkStartError:
        check("起動できなければ TalkStartError", True)


def test_turns() -> None:
    e, ctx, made, said, _e = _engine()
    e.start(ctx)
    proc = made["proc"]
    proc.on_text("ちょっと考えます。")
    check("text ブロックをすぐ話す", said == ["ちょっと考えます。"])
    e.on_self_line("一つ目")
    e.on_self_line("二つ目")
    check("生成中はためる", len(proc.sent) == 1)
    proc.on_turn_end(True)
    check("ターン終了でまとめて送る", proc.sent[-1] == "一つ目\n二つ目", repr(proc.sent))
    proc.on_turn_end(True)
    e.on_self_line("三つ目")
    check("待機中ならすぐ送る", proc.sent[-1] == "三つ目")


def test_interrupt() -> None:
    e, ctx, made, said, _e = _engine()
    e.start(ctx)
    proc = made["proc"]
    proc.on_text("一文目です。")
    e.on_interrupt("一文目です。")
    e.on_self_line("ちょっと待って")
    proc.on_text("続きです。")
    check("制止のあとのこのターンの発話は捨てる", said == ["一文目です。"], repr(said))
    proc.on_turn_end(True)
    check("止めた位置の注記つきで送る", "一文目です。" in proc.sent[-1] and proc.sent[-1].endswith("ちょっと待って"), repr(proc.sent))
    proc.on_turn_end(True)
    e.on_interrupt("")
    e.on_self_line("待って")
    check("待機中で何も話していなければ注記なし", proc.sent[-1] == "待って", repr(proc.sent))
    check("consume_interrupt は使わない", e.consume_interrupt() is None)
    check("話していないときの制止も受ける", HeadlessEngine.wants_idle_interrupt is True)


def test_exit() -> None:
    e, ctx, made, _s, ended = _engine()
    e.start(ctx)
    made["proc"].on_exit(1)
    check("予期しない終了を ended で知らせる", len(ended) == 1 and "1" in ended[0], repr(ended))
    e, ctx, made, _s, ended = _engine()
    e.start(ctx)
    e.stop()
    made["proc"].on_exit(0)
    check("stop() の後の終了は知らせない", ended == [] and made["proc"].stopped)
    e, ctx, made, _s, ended = _engine(exit_on_start=True)
    e.start(ctx)
    check("起動中に終了しても ended で知らせる", len(ended) == 1 and "1" in ended[0], repr(ended))


if __name__ == "__main__":
    test_start()
    test_turns()
    test_interrupt()
    test_exit()
    sys.exit(0 if all(results) else 1)
