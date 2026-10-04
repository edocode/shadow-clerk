"""Shadow-clerk daemon: Claude talk mode の headless engine（claude -p の常駐プロセス）

[自分] 行を stdin に送り、text ブロックが届くたびに話す。生成中に届いた行はためておき、
ターンが終わったらまとめて送る。制止されたターンの残りは捨て、止めた位置を注記で伝える。
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from shadow_clerk._daemon_talk_claude import ClaudeTalkProcess, build_claude_argv
from shadow_clerk._daemon_talk_engine import TalkContext, TalkStartError
from shadow_clerk._daemon_talk_prompt import HELD_NOTE, INTERRUPT_NOTE, KICKOFF_MESSAGE, build_system_prompt
from shadow_clerk.i18n import t

logger = logging.getLogger("shadow-clerk")


class HeadlessEngine:
    wants_idle_interrupt = True

    def __init__(self, process_factory: Callable[..., ClaudeTalkProcess] = ClaudeTalkProcess) -> None:
        self._process_factory = process_factory
        self._lock = threading.Lock()
        self._ctx: TalkContext | None = None
        self._proc: Any = None
        self._busy = False
        self._pending: list[str] = []
        self._interrupted = False  # 制止されたターン。終わるまで claude の発話を捨てる
        self._note = ""            # 次に送る行の前に付ける、制止の注記
        self._stopping = False

    def start(self, ctx: TalkContext) -> None:
        argv = build_claude_argv(ctx.config, build_system_prompt(ctx.language, ctx.persona, ctx.topic))
        proc = self._process_factory(argv, ctx.workdir, self._on_text, self._on_turn_end, self._on_exit)
        self._ctx = ctx  # 起動直後に claude が落ちても _on_exit が ended を伝えられるよう、start() より前に
        try:
            proc.start()
        except OSError as e:
            raise TalkStartError(t("talk.claude_start_failed", error=str(e))) from e
        with self._lock:
            self._proc = proc
            self._send_locked(KICKOFF_MESSAGE)

    def stop(self) -> None:
        with self._lock:
            self._stopping = True
            proc, self._proc = self._proc, None
        if proc is not None:
            proc.stop()

    def on_interrupt(self, cut: str) -> None:
        with self._lock:
            if cut or self._busy:
                self._note = INTERRUPT_NOTE.format(cut=cut)
            if self._busy:
                self._interrupted = True

    def on_held(self, text: str, heard: list[str]) -> None:
        """話さなかった文と、その間の発言を伝える。生成中のターンの残りは古い話題への返事なので捨てる"""
        note = HELD_NOTE.format(text=text, heard="\n".join(heard))
        with self._lock:
            if self._proc is None:
                return
            if self._busy:
                self._interrupted = True
                self._pending.append(note)
            else:
                self._send_locked(note)

    def on_self_line(self, text: str) -> None:
        with self._lock:
            if self._proc is None:
                return
            if self._note:
                text, self._note = f"{self._note}\n{text}", ""
            if self._busy:
                self._pending.append(text)
            else:
                self._send_locked(text)

    def consume_interrupt(self) -> str | None:
        return None  # 発話は engine の内側で捨てるので、/api/say 側では止めない

    def _send_locked(self, text: str) -> None:
        self._busy = True
        self._proc.send(text)

    def _on_text(self, text: str) -> None:
        with self._lock:
            if self._proc is None or self._interrupted:
                return
            ctx = self._ctx
        ctx.say(text)

    def _on_turn_end(self, ok: bool) -> None:
        with self._lock:
            if self._proc is None:
                return
            self._interrupted = False
            batch = "\n".join(self._pending)
            self._pending.clear()
            if batch:
                self._send_locked(batch)
            else:
                self._busy = False

    def _on_exit(self, code: int | None) -> None:
        if not self._stopping and self._ctx is not None:
            self._ctx.ended(t("talk.claude_exited", code=code))
