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

# 翻訳ファイルの言語サフィックスとして認識するコード（domain.Language と同期すること）。
# 任意の [a-z]+ を許すと "follow-up" のような会議名が翻訳ファイルと誤判定されるため
# allowlist で制限する。
KNOWN_LANGUAGE_CODES: tuple[str, ...] = ("ja", "en", "zh", "ko", "de", "fr", "es", "pt", "ru")
_LANG_ALT = "|".join(KNOWN_LANGUAGE_CODES)

def sanitize_meeting_name(name: str) -> str:
    """会議名をファイル名に使用できる形式にエスケープする。

    音声コマンド・gcal・ダッシュボード API すべてこの関数を通すこと。
    `.` はファイル名パターン（@name 部は `[^.]+`）を壊すため、`'` と `` ` `` は
    ダッシュボード JS の onclick 文字列を壊すため除去する。
    """
    # ファイル名・パターン・JS に使えない文字を除去
    name = re.sub(r'[/\\:*?"\'`<>|.\x00-\x1f]', '', name)
    # @ は区切り文字と衝突するため除去
    name = name.replace('@', '')
    # 連続空白を _ に置換、前後トリム
    name = re.sub(r'\s+', '_', name.strip())
    # 長さ制限後、末尾の区切り文字（_ / -）を除去（切り詰めで末尾に残ることがある）
    name = name[:50].rstrip('_-')
    # 末尾が -{言語コード} だと翻訳ファイルと誤判定されるため区切りを _ に変える
    return re.sub(rf'-({_LANG_ALT})$', r'_\1', name)


# 全 transcript ファイルにマッチ（日次 + 会議）
_FILE_RE = re.compile(r'^transcript-(\d{8,12})(?:@([^.]+))?\.txt$')
# 会議ファイルにのみマッチ（HHMM あり）
_MEETING_RE = re.compile(r'^transcript-(\d{12})(?:@([^.]+))?\.txt$')
# 翻訳ファイルにマッチ: transcript-YYYYMMDDHHMM[@name]-{lang}.txt
_TRANSLATION_RE = re.compile(
    rf'^transcript-(\d{{8,12}})(?:@([^.]+))?-({_LANG_ALT})\.txt$')


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
        """ファイル名から TranscriptName を生成。マッチしなければ None。

        翻訳ファイル (transcript-...-{lang}.txt) は除外する。
        名前付き会議の翻訳ファイル `transcript-...@name-{lang}.txt` は
        `_FILE_RE` にもマッチしてしまうため、先に翻訳パターンで判定する。
        """
        if _TRANSLATION_RE.match(filename):
            return None
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

    @property
    def attendees_filename(self) -> str:
        """transcript-YYYYMMDDHHMM[@name].attendees.json"""
        suffix = f"@{self.meeting_name}" if self.meeting_name else ""
        return f"transcript-{self.datetime_str}{suffix}.attendees.json"

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
        """同タイムスタンプ・同会議名の関連ファイル（翻訳・offset等）の stem にマッチするパターン。

        stem 直後が `.`（拡張子）または `-`（翻訳サフィックス）の場合のみマッチする。
        会議名を `[^.]+` で緩くマッチさせると翻訳ファイル `@name-en.txt` の
        `-en` まで stem として食われ、リネーム時に transcript 本体と同名に
        衝突してしまうため、実際の会議名をエスケープして厳密にマッチさせる。
        """
        return re.compile(r'^' + re.escape(self.stem) + r'(?=[.-])')

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
        sum_pat = re.compile(r'^' + re.escape(self.summary_stem) + r'(?=[.-])')
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
