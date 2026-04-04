"""shadow-clerk domain: Translation バリューオブジェクト"""
from __future__ import annotations

import os
from dataclasses import dataclass

from shadow_clerk._transcript_name import TranscriptName


@dataclass(frozen=True)
class Translation:
    """会議 transcript の翻訳を表すバリューオブジェクト。

    language は "en", "ja" などの言語コード文字列。
    content は翻訳済みテキスト（元の transcript 行フォーマットに準拠）。
    """

    transcript_name: TranscriptName
    language: str
    content: str

    def file_path(self, output_dir: str) -> str:
        """output_dir 内の翻訳ファイルパスを返す。"""
        return os.path.join(output_dir, self.transcript_name.translation_filename(self.language))
