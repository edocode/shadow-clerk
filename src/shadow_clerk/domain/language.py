"""shadow-clerk domain: 言語バリューオブジェクト"""
from __future__ import annotations

from enum import Enum


class Language(str, Enum):
    """音声認識・翻訳で使用する言語コード。

    str を継承しているため、Language.JA == "ja" が True になり
    既存の設定値・API 呼び出しと透過的に互換する。

    未知の言語コードが来た場合は文字列のままで扱う（下記 coerce() を参照）。
    """

    JA = "ja"    # 日本語
    EN = "en"    # 英語
    ZH = "zh"    # 中国語
    KO = "ko"    # 韓国語
    DE = "de"    # ドイツ語
    FR = "fr"    # フランス語
    ES = "es"    # スペイン語

    @classmethod
    def coerce(cls, value: str) -> Language | str:
        """設定値などの文字列を Language に変換する。

        既知の言語コードなら Language enum を返し、
        未知のコードはそのまま str で返す。
        """
        try:
            return cls(value)
        except ValueError:
            return value
