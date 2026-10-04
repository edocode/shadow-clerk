"""shadow-clerk domain: ブラウザの読み上げ（練習言語の文を鳴らすダッシュボードのタブ）"""
from __future__ import annotations

import re
from dataclasses import dataclass

from shadow_clerk.domain.language import Language

_TAB_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
# 読み上げの長さの見積もり（1 秒あたりの文字数）。遅めに見積もる。短く見積もると、言い終える前に次の文へ進んでしまう
_CHARS_PER_SEC = 8.0


def estimate_speech_sec(text: str) -> float:
    """文を読み上げる長さの見積もり（秒）。ブラウザで読む文の待ち時間と、エコー用の区間に使う"""
    return len(text) / _CHARS_PER_SEC


@dataclass(frozen=True)
class SpeechTab:
    """練習言語の文を読めると名乗ったダッシュボードのタブ。langs が空なら名乗りの取り下げ"""
    tab: str
    langs: frozenset[Language]

    @classmethod
    def parse(cls, raw: object) -> SpeechTab:
        """POST /api/talk-speech/ready の body。不正なら ValueError。知らない言語コードは捨てる（ブラウザの声は多い）"""
        if not isinstance(raw, dict):
            raise ValueError("body must be an object")
        tab, langs = raw.get("tab"), raw.get("langs")
        if not isinstance(tab, str) or not _TAB_ID.fullmatch(tab):
            raise ValueError("tab must be a short id of letters, digits, - and _")
        if not isinstance(langs, list):
            raise ValueError("langs must be a list of language codes")
        known = {lang.value for lang in Language}
        return cls(tab, frozenset(Language(x) for x in langs if isinstance(x, str) and x in known))

    def speaks(self, lang: Language) -> bool:
        return lang in self.langs
