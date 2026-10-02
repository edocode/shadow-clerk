"""Shadow-clerk daemon: Claude talk mode の console engine

AI Console の talk 枠で Claude Code を起動し、clerk-talk skill を送る。発言は skill が /api/watch で読み、
応答は skill が /api/say で話すので、ここが持つのは起動・終了と、制止を /api/say に伝える状態だけ。
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from shadow_clerk._daemon_talk_engine import TalkContext, TalkStartError
from shadow_clerk.domain import ConsoleRole
from shadow_clerk.domain.ai_assistant import AiAssistantConfig
from shadow_clerk.i18n import t
from shadow_clerk.skill_install import TALK_SKILL_NAME

logger = logging.getLogger("shadow-clerk")


def _talk_console() -> Any:
    from shadow_clerk._daemon_console import get_console
    return get_console(ConsoleRole.TALK)


def _talk_skill_installed() -> bool:
    from shadow_clerk.skill_install import remembered_targets, skill_installed
    return skill_installed(TALK_SKILL_NAME, remembered_targets())


class ConsoleEngine:
    def __init__(self, console_factory: Callable[[], Any] = _talk_console,
                 skill_check: Callable[[], bool] = _talk_skill_installed, poll_sec: float = 1.0) -> None:
        self._console_factory = console_factory
        self._skill_check = skill_check
        self._poll_sec = poll_sec
        self._lock = threading.Lock()
        self._console: Any = None
        self._ctx: TalkContext | None = None
        self._cut: str | None = None
        self._stop = threading.Event()

    def start(self, ctx: TalkContext) -> None:
        if not self._skill_check():
            raise TalkStartError(t("talk.skill_missing", skill=TALK_SKILL_NAME))
        ai = AiAssistantConfig.from_config(ctx.config)
        console = self._console_factory()
        if console.is_running() and console.workdir != ctx.workdir:
            # 別のリポジトリで動いている Claude を使い回すと、Read や編集の基準がずれる
            logger.info("talk: 作業ディレクトリが違うため talk コンソールを起動し直します (%s -> %s)",
                        console.workdir, ctx.workdir)
            console.stop()
        ok, _started = console.start_if_stopped(ai.argv(), ctx.workdir)
        if not ok:
            raise TalkStartError(t("talk.console_start_failed"))
        console.send_after_ready(f"/{TALK_SKILL_NAME}\r")
        self._console, self._ctx = console, ctx
        threading.Thread(target=self._watch, name="talk-console-watch", daemon=True).start()

    def _watch(self) -> None:
        """talk コンソールが自分で終わったら（/exit など）talk mode も終える"""
        while not self._stop.wait(self._poll_sec):
            if not self._console.is_running():
                if not self._stop.is_set() and self._ctx is not None:
                    self._ctx.ended(t("talk.console_exited"))
                return

    def stop(self) -> None:
        self._stop.set()
        if self._console is not None:
            self._console.stop()

    def on_self_line(self, text: str) -> None:
        pass  # skill が /api/watch で読む

    def on_interrupt(self, cut: str) -> None:
        with self._lock:
            self._cut = cut

    def consume_interrupt(self) -> str | None:
        with self._lock:
            cut, self._cut = self._cut, None
            return cut
