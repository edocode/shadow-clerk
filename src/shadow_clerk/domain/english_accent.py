"""shadow-clerk domain: 練習する英語（米音・英音）"""
from __future__ import annotations

from enum import Enum


class EnglishAccent(str, Enum):
    """英語の練習で揃える英語。判定（espeak）・発音記号・お手本の声・図鑑の声が従う。英音は RP（イングランド南部）"""

    AMERICAN = "american"
    BRITISH = "british"

    @property
    def espeak(self) -> str:
        return "en-gb" if self is EnglishAccent.BRITISH else "en-us"

    @property
    def bcp47(self) -> str:
        return "en-GB" if self is EnglishAccent.BRITISH else "en-US"

    @classmethod
    def from_config(cls, config: dict) -> EnglishAccent:
        """設定の english_accent。キーが無い・知らない値なら米音"""
        value = config.get("english_accent")
        return cls(value) if value in {a.value for a in cls} else cls.AMERICAN
