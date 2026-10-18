"""shadow-clerk domain: 発音フィードバック（音素レベル）の値オブジェクト

daemon は判定しない。期待IPAと実測IPAの語ごとの対応だけを持つ。
合否・点数・編集距離の合計は意図的に持たせていない（設計書 §7.3）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from shadow_clerk.domain.language import Language

_MAX_TEXT_CHARS = 500
_MAX_FOCUS = 20


class PronounceState(Enum):
    """アームの状態。解析中かどうかは state ではなく pending で表す（設計書 §7.2）"""
    IDLE = "idle"
    ARMED = "armed"
    LOADING = "loading"
    UNAVAILABLE = "unavailable"


class OpKind(Enum):
    SAME = "same"
    SUB = "sub"
    DEL = "del"
    INS = "ins"


@dataclass(frozen=True)
class FocusPhoneme:
    """この課題で狙った音。word の中の phoneme だけが評価の対象になる。

    index は同じ語が課題文に複数あるときの何番目か、phoneme_index は語内に同じ音素が
    複数あるときの何番目か。どちらも 0 始まりで、数えるのは正規化後の期待列（設計書 §7.1）
    """
    word: str
    phoneme: str
    index: int = 0
    phoneme_index: int = 0

    def to_json(self) -> dict:
        return {"word": self.word, "phoneme": self.phoneme,
                "index": self.index, "phoneme_index": self.phoneme_index}


@dataclass(frozen=True)
class PronunciationTask:
    text: str
    language: Language
    focus: tuple[FocusPhoneme, ...]

    @classmethod
    def parse(cls, raw: object) -> PronunciationTask:
        """POST /api/pronounce の body。不正なら ValueError（呼び手が status: error にする）"""
        if not isinstance(raw, dict):
            raise ValueError("body must be an object")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")
        if len(text) > _MAX_TEXT_CHARS:
            raise ValueError(f"text must be at most {_MAX_TEXT_CHARS} characters")
        lang = raw.get("lang")
        if not isinstance(lang, str) or lang not in {x.value for x in Language}:
            raise ValueError("lang must be a known language code")
        focus_raw = raw.get("focus", [])
        if not isinstance(focus_raw, list) or len(focus_raw) > _MAX_FOCUS:
            raise ValueError(f"focus must be a list of at most {_MAX_FOCUS} entries")
        return cls(text, Language(lang), tuple(_parse_focus(x) for x in focus_raw))

    def to_json(self) -> dict:
        return {"text": self.text, "lang": self.language.value,
                "focus": [f.to_json() for f in self.focus]}


def _parse_focus(raw: object) -> FocusPhoneme:
    if not isinstance(raw, dict):
        raise ValueError("each focus entry must be an object")
    word, phoneme = raw.get("word"), raw.get("phoneme")
    if not isinstance(word, str) or not word.strip():
        raise ValueError("focus[].word must be a non-empty string")
    if not isinstance(phoneme, str) or not phoneme.strip():
        raise ValueError("focus[].phoneme must be a non-empty string")
    return FocusPhoneme(word, phoneme, _parse_index(raw, "index"), _parse_index(raw, "phoneme_index"))


def _parse_index(raw: dict, key: str) -> int:
    value = raw.get(key, 0)
    # bool は int の派生なので、True が 1 として通らないよう明示的に弾く
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"focus[].{key} must be a non-negative integer")
    return value


@dataclass(frozen=True)
class PhonemeOp:
    """期待側1音素と実測側1音素の対応。focus は「この op が課題の狙いの音か」"""
    kind: OpKind
    expected: str
    actual: str
    focus: bool

    def to_json(self) -> dict:
        return {"kind": self.kind.value, "expected": self.expected,
                "actual": self.actual, "focus": self.focus}


@dataclass(frozen=True)
class WordComparison:
    word: str
    expected: tuple[str, ...]
    actual: tuple[str, ...]
    ops: tuple[PhonemeOp, ...]

    def to_json(self) -> dict:
        return {"word": self.word, "expected": list(self.expected),
                "actual": list(self.actual), "ops": [op.to_json() for op in self.ops]}


@dataclass(frozen=True)
class Attempt:
    """1回の読み上げの解析結果。直近3件を保持する（設計書 §8.2）"""
    at: str                  # 解析が終わった時刻。segment_at と同じ形式
    segment_at: str          # transcript の行と突き合わせる鍵。YYYY-MM-DD HH:MM:SS
    asr_text: str            # 同じセグメントの文字起こし。課題の発話かを Claude が判断する
    words: tuple[WordComparison, ...]

    def to_json(self) -> dict:
        return {"at": self.at, "segment_at": self.segment_at, "asr_text": self.asr_text,
                "words": [w.to_json() for w in self.words]}
