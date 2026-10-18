"""Shadow-clerk daemon: 発音フィードバックの突き合わせ（音韻クラス・アライメント・語への帰属）

daemon が持つのは音韻クラスまで。どの差分が意味を持つかの判断と学習者への言い方は
スキル（Claude）の側に置く（設計書 §2）。
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Sequence

from shadow_clerk.domain import OpKind

logger = logging.getLogger("shadow-clerk")

# 正規化後のアルファベットに対する母音クラス。æ ɑ ɒ ɔ ɪ ə ɐ ʌ ᵻ ɨ ɜ ɚ は
# 正規化で A O @ R になるのでここには現れない（設計書 §4.1）
VOWELS: frozenset[str] = frozenset({
    "@", "R", "O", "A",                                   # 正規化のクラス記号
    "i", "e", "ɛ", "a", "u", "ʊ", "ʉ", "y", "ø", "œ", "ɤ", "ɯ", "ɘ", "ɞ", "ɵ",
    "aɪ", "aʊ", "ɔɪ", "eɪ", "oʊ", "əʊ", "ɪə", "ɛə", "ʊə",  # 二重母音
})
# 結合記号。表に無い記号を基底文字で引き直すときに外す
_COMBINING = "̩̥̪̝̞̠̃̈"


@lru_cache(maxsize=None)
def is_vowel(symbol: str) -> bool:
    """母音クラスか。表に無い記号は子音として扱い、1行だけ WARNING を出す"""
    if symbol in VOWELS:
        return True
    base = symbol.strip(_COMBINING)
    if base != symbol and base in VOWELS:
        return True
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
