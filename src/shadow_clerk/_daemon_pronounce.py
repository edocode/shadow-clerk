"""Shadow-clerk daemon: 発音フィードバックの突き合わせ（音韻クラス・アライメント・語への帰属）

daemon が持つのは音韻クラスまで。どの差分が意味を持つかの判断と学習者への言い方は
スキル（Claude）の側に置く（設計書 §2）。
"""
from __future__ import annotations

import bisect
import logging
from functools import lru_cache
from typing import Sequence

from shadow_clerk._daemon_pronounce_ipa import word_key
from shadow_clerk.domain import FocusPhoneme, OpKind, PhonemeOp, WordComparison

logger = logging.getLogger("shadow-clerk")

# 正規化後のアルファベットに対する母音クラス。æ ɑ ɒ ɔ ɪ ə ɐ ʌ ᵻ ɨ ɜ ɚ は
# 正規化で A O @ R になるのでここには現れない（設計書 §4.1）
VOWELS: frozenset[str] = frozenset({
    "@", "R", "O", "A",                                   # 正規化のクラス記号
    "i", "e", "ɛ", "a", "u", "ʊ", "ʉ", "y", "ø", "œ", "ɤ", "ɯ", "ɘ", "ɞ", "ɵ",
    "aɪ", "aʊ", "ɔɪ", "eɪ", "oʊ", "əʊ", "ɪə", "ɛə", "ʊə",  # 二重母音
})
# スパイクでモデルが実際に出した子音。母音表と合わせて「既知の記号」を成す。
# どちらにも無い記号が来たら、表を広げる必要があるという合図なので WARNING を出す
CONSONANTS: frozenset[str] = frozenset({
    "b", "d", "dʒ", "f", "h", "j", "k", "l", "m", "n", "ŋ", "p", "r", "ɹ",
    "s", "ʃ", "t", "tʃ", "θ", "ð", "v", "w", "z", "ʒ", "ɡ",
})
# 結合記号。表に無い記号を基底文字で引き直すときに外す
_COMBINING = "̩̥̪̝̞̠̃̈"


@lru_cache(maxsize=None)
def is_vowel(symbol: str) -> bool:
    """母音クラスか。母音表にも子音表にも無い記号は、子音として扱って WARNING を1行出す"""
    if symbol in VOWELS:
        return True
    if symbol in CONSONANTS:
        return False
    base = symbol.strip(_COMBINING)
    if base in VOWELS:
        return True
    if base in CONSONANTS:
        return False
    logger.warning("pronounce: 音素クラス表に無い記号 %r を子音として扱います", symbol)
    return False


def _sub_cost(expected: str, actual: str) -> int | None:
    """置換のコスト。クラスをまたぐ置換は演算として持たない（None = 不許可）"""
    if expected == actual:
        return 0
    return 1 if is_vowel(expected) == is_vowel(actual) else None


def align(expected: Sequence[str], actual: Sequence[str]) -> tuple[tuple[OpKind, str, str], ...]:
    """音韻クラスで重み付けした編集経路。同コストなら same < sub < del < ins の辞書順最小。

    末尾からのバックトレースでは「先頭から辞書順最小」にならないので、
    先に接尾コスト表を作り、先頭から貪欲に選ぶ（設計書 §4.1）
    """
    n, m = len(expected), len(actual)
    inf = float("inf")
    # rest[i][j] = expected[i:] と actual[j:] を揃える最小コスト
    rest: list[list[float]] = [[inf] * (m + 1) for _ in range(n + 1)]
    rest[n][m] = 0.0
    for i in range(n, -1, -1):
        for j in range(m, -1, -1):
            if i == n and j == m:
                continue
            best = inf
            if i < n and j < m and (cost := _sub_cost(expected[i], actual[j])) is not None:
                best = min(best, cost + rest[i + 1][j + 1])
            if i < n:
                best = min(best, 1 + rest[i + 1][j])
            if j < m:
                best = min(best, 1 + rest[i][j + 1])
            rest[i][j] = best

    ops: list[tuple[OpKind, str, str]] = []
    i = j = 0
    while i < n or j < m:
        if i < n and j < m and expected[i] == actual[j] and rest[i + 1][j + 1] == rest[i][j]:
            ops.append((OpKind.SAME, expected[i], actual[j]))
            i, j = i + 1, j + 1
            continue
        if i < n and j < m:
            cost = _sub_cost(expected[i], actual[j])
            if cost is not None and cost + rest[i + 1][j + 1] == rest[i][j]:
                ops.append((OpKind.SUB, expected[i], actual[j]))
                i, j = i + 1, j + 1
                continue
        if i < n and 1 + rest[i + 1][j] == rest[i][j]:
            ops.append((OpKind.DEL, expected[i], ""))
            i += 1
            continue
        ops.append((OpKind.INS, "", actual[j]))
        j += 1
    return tuple(ops)


def compare(words: Sequence[str], per_word: Sequence[Sequence[str]],
            actual: Sequence[str], focus: Sequence[FocusPhoneme]) -> tuple[WordComparison, ...]:
    """語ごとの期待列と発話全体の実測列を突き合わせ、語ごとの対応に切り分ける。

    アライメントは連結した期待列に対して1回だけ掛け、期待側の index で語に帰属させる。
    ins は直前に消費した期待音素の語に付く。同名の語が複数あっても境界の位置で引くので混ざらない
    """
    expected = [p for seq in per_word for p in seq]
    # bounds[i] = i 語目の期待列が始まる位置。語の長さが 0 でも破綻しないよう右端で引く
    bounds: list[int] = []
    total = 0
    for seq in per_word:
        bounds.append(total)
        total += len(seq)
    focused = _focus_positions(words, per_word, focus)

    def word_at(position: int) -> int:
        if not words:
            return 0
        return max(0, min(bisect.bisect_right(bounds, min(position, total - 1 if total else 0)) - 1,
                          len(words) - 1))

    ops_of: list[list[PhonemeOp]] = [[] for _ in words]
    actual_of: list[list[str]] = [[] for _ in words]
    consumed = 0
    for kind, exp_sym, act_sym in align(expected, actual):
        index = word_at(consumed - 1 if kind is OpKind.INS else consumed)
        ops_of[index].append(
            PhonemeOp(kind, exp_sym, act_sym, kind is not OpKind.INS and consumed in focused))
        if act_sym:
            actual_of[index].append(act_sym)
        if kind is not OpKind.INS:
            consumed += 1
    return tuple(WordComparison(words[i], tuple(per_word[i]), tuple(actual_of[i]), tuple(ops_of[i]))
                 for i in range(len(words)))


def _focus_positions(words: Sequence[str], per_word: Sequence[Sequence[str]],
                     focus: Sequence[FocusPhoneme]) -> set[int]:
    """focus が指す音素が、連結した期待列の何番目かを集める。見つからないものは黙って捨てる
    （POST の時点で検証済み。ここは防御的な処理）"""
    keys = [word_key(w) for w in words]
    starts: list[int] = []
    total = 0
    for seq in per_word:
        starts.append(total)
        total += len(seq)
    out: set[int] = set()
    for item in focus:
        hits = [i for i, key in enumerate(keys) if key == word_key(item.word)]
        if item.index >= len(hits):
            continue
        at = hits[item.index]
        inside = [i for i, sym in enumerate(per_word[at]) if sym == item.phoneme]
        if item.phoneme_index < len(inside):
            out.add(starts[at] + inside[item.phoneme_index])
    return out
