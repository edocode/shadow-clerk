"""Shadow-clerk: transcript ファイル名の値オブジェクト

transcript ファイル名のパース・構築・派生を一元管理する。

フォーマット:
  transcript-YYYYMMDD.txt               日次ファイル（会議なし）
  transcript-YYYYMMDDHHMM.txt           会議ファイル（名前なし = ad-hoc）
  transcript-YYYYMMDDHHMM@name.txt      会議ファイル（名前付き）
"""
from __future__ import annotations

import os
import re

# 全 transcript ファイルにマッチ（日次 + 会議）
_FILE_RE = re.compile(r'^transcript-(\d{8,12})(?:@([^.]+))?\.txt$')
# 会議ファイルにのみマッチ（HHMM あり）
_MEETING_RE = re.compile(r'^transcript-(\d{12})(?:@([^.]+))?\.txt$')
# 翻訳ファイルにマッチ: transcript-YYYYMMDDHHMM[@name]-{lang}.txt
_TRANSLATION_RE = re.compile(r'^transcript-(\d{8,12})(?:@([^.]+))?-([a-z]{2,10})\.txt$')


class TranscriptName:
    """transcript ファイル名の値オブジェクト"""

    def __init__(self, datetime_str: str, meeting_name: str | None = None) -> None:
        """
        datetime_str: "YYYYMMDD" or "YYYYMMDDHHMM"
        meeting_name: サニタイズ済み会議名、または None
        """
        self.datetime_str = datetime_str
        self.meeting_name = meeting_name or None

    # --- ファクトリ ---

    @classmethod
    def parse(cls, filename: str) -> "TranscriptName | None":
        """ファイル名から TranscriptName を生成。マッチしなければ None。"""
        m = _FILE_RE.match(filename)
        if not m:
            return None
        return cls(m.group(1), m.group(2) or None)

    @classmethod
    def parse_translation(cls, filename: str) -> "tuple[TranscriptName, str] | None":
        """翻訳ファイル名から (TranscriptName, lang) を生成。マッチしなければ None。"""
        m = _TRANSLATION_RE.match(filename)
        if not m:
            return None
        return cls(m.group(1), m.group(2) or None), m.group(3)

    @classmethod
    def from_date_str(cls, date_str: str) -> "TranscriptName":
        """日付文字列から TranscriptName を生成。
        date_str は "YYYYMMDD", "YYYYMMDDHHMM", "YYYYMMDDHHMM@name" のいずれか。
        """
        if "@" in date_str:
            dt, name = date_str.split("@", 1)
        else:
            dt, name = date_str, None
        return cls(dt, name or None)

    @property
    def is_meeting_file(self) -> bool:
        return len(self.datetime_str) == 12

    # --- 派生ファイル名 ---

    @property
    def filename(self) -> str:
        """transcript-YYYYMMDDHHMM[@name].txt"""
        suffix = f"@{self.meeting_name}" if self.meeting_name else ""
        return f"transcript-{self.datetime_str}{suffix}.txt"

    @property
    def summary_filename(self) -> str:
        """summary-YYYYMMDDHHMM[@name].md"""
        suffix = f"@{self.meeting_name}" if self.meeting_name else ""
        return f"summary-{self.datetime_str}{suffix}.md"

    def translation_filename(self, lang: str) -> str:
        """transcript-YYYYMMDDHHMM[@name]-{lang}.txt"""
        suffix = f"@{self.meeting_name}" if self.meeting_name else ""
        return f"transcript-{self.datetime_str}{suffix}-{lang}.txt"

    # --- stem ---

    @property
    def stem(self) -> str:
        """transcript-YYYYMMDDHHMM[@name]（拡張子なし）"""
        suffix = f"@{self.meeting_name}" if self.meeting_name else ""
        return f"transcript-{self.datetime_str}{suffix}"

    @property
    def datetime_stem(self) -> str:
        """transcript-YYYYMMDDHHMM（@name なし・拡張子なし）"""
        return f"transcript-{self.datetime_str}"

    @property
    def summary_stem(self) -> str:
        """summary-YYYYMMDDHHMM[@name]（拡張子なし）"""
        suffix = f"@{self.meeting_name}" if self.meeting_name else ""
        return f"summary-{self.datetime_str}{suffix}"

    # --- 表示ラベル ---

    def _fmt_datetime(self) -> str:
        dt = self.datetime_str
        if len(dt) >= 12:
            return f"{dt[:4]}-{dt[4:6]}-{dt[6:8]} {dt[8:10]}:{dt[10:12]}"
        if len(dt) >= 8:
            return f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
        return dt

    @property
    def label(self) -> str:
        """ファイルセレクター用: "YYYY-MM-DD HH:MM @name" or "YYYY-MM-DD HH:MM" or "YYYY-MM-DD" """
        dt = self._fmt_datetime()
        return f"{dt} @{self.meeting_name}" if self.meeting_name else dt

    @property
    def meeting_label(self) -> str:
        """会議ペイン用: "YYYY-MM-DD HH:MM"（名前なし）"""
        return self._fmt_datetime()

    # --- 会議グループ ---

    @property
    def meeting_group(self) -> str | None:
        """会議ペイン用グループ名。日次ファイルは None、名前なし会議は 'ad-hoc'。"""
        if not self.is_meeting_file:
            return None
        return self.meeting_name or "ad-hoc"

    # --- 変換 ---

    @property
    def related_file_pattern(self) -> "re.Pattern[str]":
        """同タイムスタンプの関連ファイル（翻訳・summary・offset等）にマッチするパターン。

        transcript-YYYYMMDDHHMM[@任意の名前] で始まるファイルを対象とする。
        """
        return re.compile(r'^' + re.escape(self.datetime_stem) + r'(?:@[^.]+)?')

    def file_info(self) -> dict:
        """ダッシュボード /api/files レスポンス用の file_info dict を返す"""
        return {
            "label": self.label,
            "meeting_label": self.meeting_label,
            "meeting_group": self.meeting_group,
            "summary": self.summary_filename,
            "dt": self.datetime_str,
            "name": self.meeting_name,
        }

    def with_name(self, new_name: str | None) -> TranscriptName:
        """会議名だけ変えた新しい TranscriptName を返す"""
        return TranscriptName(self.datetime_str, new_name or None)

    def rename_plan(self, new_tn: TranscriptName, directory: str) -> list[tuple[str, str]]:
        """ディレクトリ内の関連ファイルを検索し (old_name, new_name) ペアを返す。

        対象:
          transcript-YYYYMMDDHHMM[@old].txt
          transcript-YYYYMMDDHHMM[@old]-{lang}.txt  (翻訳)
          transcript-YYYYMMDDHHMM[@old].txt.translate_offset
          summary-YYYYMMDDHHMM[@old].md
        """
        tr_pat = self.related_file_pattern
        sum_pat = re.compile(r'^summary-' + re.escape(self.datetime_str) + r'(?:@[^.]+)?')
        try:
            all_files = os.listdir(directory)
        except OSError:
            return []
        pairs: list[tuple[str, str]] = []
        for fname in all_files:
            if tr_pat.match(fname):
                new_fname = new_tn.stem + tr_pat.sub('', fname)
            elif sum_pat.match(fname):
                new_fname = new_tn.summary_stem + sum_pat.sub('', fname)
            else:
                continue
            if fname != new_fname:
                pairs.append((fname, new_fname))
        return pairs
