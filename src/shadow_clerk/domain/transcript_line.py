"""shadow-clerk domain: TranscriptLine バリューオブジェクト"""
from __future__ import annotations

import re
from dataclasses import dataclass

from shadow_clerk.domain.speaker import Speaker


# transcript ファイルの1行フォーマット: [YYYY-MM-DD HH:MM:SS] [話者] テキスト
_LINE_RE = re.compile(
    r"^\[([^\]]+)\]\s+\[([^\]]+)\]\s+(.+)$"
)


@dataclass(frozen=True)
class TranscriptLine:
    """transcript ファイルの1行を表すバリューオブジェクト。

    timestamp は "YYYY-MM-DD HH:MM:SS" 形式の文字列。
    """

    timestamp: str
    speaker: Speaker
    text: str

    def format(self) -> str:
        """ファイル書き込み用文字列（末尾改行あり）を返す。"""
        return f"[{self.timestamp}] [{self.speaker}] {self.text}\n"

    @classmethod
    def parse(cls, line: str) -> TranscriptLine | None:
        """ファイル1行から TranscriptLine を生成する。

        マッチしない行（マーカー行など）は None を返す。
        """
        m = _LINE_RE.match(line.rstrip("\n"))
        if not m:
            return None
        timestamp, speaker_str, text = m.group(1), m.group(2), m.group(3)
        try:
            speaker = Speaker(speaker_str)
        except ValueError:
            # 未知の話者ラベルは Speaker.SELF として扱う（後方互換）
            speaker = Speaker.SELF
        return cls(timestamp=timestamp, speaker=speaker, text=text)

    @classmethod
    def from_source(cls, timestamp: str, source: str, text: str) -> TranscriptLine:
        """audio source ("mic" / "monitor") と文字列から TranscriptLine を生成する。"""
        return cls(
            timestamp=timestamp,
            speaker=Speaker.from_source(source),
            text=text,
        )
