"""shadow-clerk domain: Summary バリューオブジェクト"""
from __future__ import annotations

import datetime
import os
from dataclasses import dataclass, field

from shadow_clerk._transcript_name import TranscriptName


@dataclass(frozen=True)
class Summary:
    """会議の要約（議事録）を表すバリューオブジェクト。

    content は Markdown 形式の文字列。
    """

    transcript_name: TranscriptName
    content: str
    generated_at: datetime.datetime = field(default_factory=datetime.datetime.now)

    def file_path(self, output_dir: str) -> str:
        """output_dir 内の summary ファイルパスを返す。"""
        return os.path.join(output_dir, self.transcript_name.summary_filename)
