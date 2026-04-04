"""shadow-clerk domain: 話者バリューオブジェクト"""
from __future__ import annotations

from enum import Enum


class Speaker(str, Enum):
    """transcript ファイルに書き込まれる話者ラベル。

    str を継承しているため、Speaker.SELF == "自分" が True になり
    既存の文字列ベースの処理と透過的に互換する。
    """

    SELF = "自分"    # マイク入力（自分の発言）
    OTHER = "相手"   # モニター入力（相手の発言）

    @classmethod
    def from_source(cls, source: str) -> Speaker:
        """audio source ("mic" / "monitor") から Speaker を返す。"""
        if source == "mic":
            return cls.SELF
        if source == "monitor":
            return cls.OTHER
        raise ValueError(f"未知の source: {source!r}")
