"""Shadow-clerk daemon: Claude talk mode の会話の担い手（engine）

TalkDriver は TTS・monitor の抑制・制止・つなぎの一言を持ち、会話そのものは engine に任せる。
console（AI Console の talk 枠で動く Claude Code + clerk-talk skill）と
headless（daemon が常駐させる claude -p）の2つがある。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from shadow_clerk.domain import Language, TalkPersona


class TalkStartError(Exception):
    """talk mode を開始できなかった。メッセージはそのままユーザーに見せる"""


@dataclass(frozen=True)
class TalkContext:
    """engine に渡す会話の条件と、engine から driver を呼ぶ口"""

    topic: str
    persona: TalkPersona | None
    language: Language
    workdir: str                  # 会話役を起動する作業ディレクトリ（解決済み）
    config: dict
    say: Callable[[str], None]    # [Claude] 行を書いて読み上げる
    ended: Callable[[str], None]  # engine 側で会話が終わった。引数は status に出す理由


class TalkEngine(Protocol):
    # 何も話していないときの制止も on_interrupt で受けるか。headless は生成中のターンを捨てるので受ける。
    # console は受けると、制止の言葉への返事（次の /api/say）まで止めてしまう
    wants_idle_interrupt: bool

    def start(self, ctx: TalkContext) -> None: ...
    def stop(self) -> None: ...
    def on_self_line(self, text: str) -> None: ...
    def on_interrupt(self, cut: str) -> None: ...
    def consume_interrupt(self) -> str | None: ...


def make_engine(name: str) -> TalkEngine:
    """talk_engine の値から engine を作る。headless 以外（未知の値を含む）は console"""
    if name == "headless":
        from shadow_clerk._daemon_talk_headless import HeadlessEngine
        return HeadlessEngine()
    from shadow_clerk._daemon_talk_console import ConsoleEngine
    return ConsoleEngine()
