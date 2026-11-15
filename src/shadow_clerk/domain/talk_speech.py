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


# /api/say の text の中で、別の言語で読む区間。<en>…</en> のように言語コードで囲む
_LANG_TAG = re.compile(r"<(/?)([a-z]{2})>")
_SPEAKABLE = re.compile(r"\w")


@dataclass(frozen=True)
class SayText:
    """/api/say の text を、読む言語ごとの区間に分けたもの。lang が None の区間は読み上げの言語（VOICEVOX）で読む。
    plain はタグを外した文（transcript に書く。読むものの無い区間の句読点も残る）"""
    segments: tuple[tuple[str, Language | None], ...]
    plain: str

    @classmethod
    def parse(cls, text: str, lang: Language | None = None) -> SayText:
        """タグの外は lang で読む。知らない言語・閉じていない・入れ子のタグは ValueError。読むもの（文字）の無い区間は捨てる"""
        known = {x.value for x in Language}
        segments: list[tuple[str, Language | None]] = []
        pos, inner = 0, None
        for m in _LANG_TAG.finditer(text):
            closing, code = m.group(1) == "/", m.group(2)
            if code not in known:
                raise ValueError(f"unknown language tag <{m.group(1)}{code}>")
            if closing != (inner is not None) or (closing and code != inner):
                raise ValueError(f"unbalanced language tag <{m.group(1)}{code}>")
            segments.append((text[pos:m.start()], Language(inner) if inner else lang))
            pos, inner = m.end(), None if closing else code
        if inner is not None:
            raise ValueError(f"unclosed language tag <{inner}>")
        segments.append((text[pos:], lang))
        return cls(tuple((s, lg) for s, lg in segments if _SPEAKABLE.search(s)), "".join(s for s, _ in segments))
