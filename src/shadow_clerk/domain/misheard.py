"""聞き間違い候補の一覧（値オブジェクト）

glossary が「訳語と読み」の表なのに対し、こちらは **transcript を読むときに
文脈で判断が要る対**を貯める。どちらも transcript には適用しない——同音の
一般語が本当にその意味で使われている箇所と切り分けられるのは読み手だけで、
置換は不可逆だから。

1 行 1 対の TSV にしてあるのは、気づくたびに**追記だけで済ませる**ため。
同じ語の別表記は行を足す。
"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass

from shadow_clerk._daemon_constants import MISHEARD_FILE

logger = logging.getLogger("shadow-clerk")

HEADER = "actual\theard\tnote"
MAX_FIELD_LEN = 200
MAX_ENTRIES = 2000


@dataclass(frozen=True)
class Misheard:
    """`実際 <TAB> 観測された表記 <TAB> 備考` の 1 行"""

    actual: str
    heard: str
    note: str = ""

    @property
    def key(self) -> tuple[str, str]:
        """同じ対を二重に貯めないための同一性。備考は含めない"""
        return (self.actual, self.heard)

    def to_row(self) -> str:
        return "\t".join((self.actual, self.heard, self.note))


def _clean(value: object) -> str:
    """TSV を壊さないよう、タブと改行を落として長さを詰める"""
    if not isinstance(value, str):
        return ""
    return value.replace("\t", " ").replace("\n", " ").strip()[:MAX_FIELD_LEN]


def load(path: str = "") -> list[Misheard]:
    """記録を読む。無ければ空。ヘッダ行と `#` 始まりは飛ばす"""
    out: list[Misheard] = []
    try:
        with open(path or MISHEARD_FILE, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line.strip() or line.startswith("#") or line == HEADER:
                    continue
                cols = line.split("\t")
                actual, heard = _clean(cols[0]), _clean(cols[1] if len(cols) > 1 else "")
                if not actual or not heard:
                    continue
                out.append(Misheard(actual, heard,
                                    _clean(cols[2] if len(cols) > 2 else "")))
                if len(out) >= MAX_ENTRIES:
                    break
    except OSError:
        return []
    return out


def append(entries: object, path: str = "") -> list[Misheard]:
    """まだ無い対だけを足して、追加できたものを返す

    スキルが会議中に呼ぶので、**既にある対は黙って捨てる**。同じ崩れは何度も
    現れるため、これが無いと同じ行が積み上がる。
    """
    target = path or MISHEARD_FILE
    existing = load(target)
    known = {e.key for e in existing}
    added: list[Misheard] = []
    for item in entries if isinstance(entries, list) else []:
        if not isinstance(item, dict):
            continue
        e = Misheard(_clean(item.get("actual")), _clean(item.get("heard")),
                     _clean(item.get("note")))
        if not e.actual or not e.heard or e.key in known:
            continue
        if len(existing) + len(added) >= MAX_ENTRIES:
            break
        known.add(e.key)
        added.append(e)
    if not added:
        return []
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        new_file = not os.path.exists(target) or os.path.getsize(target) == 0
        with open(target, "a", encoding="utf-8") as f:
            if new_file:
                f.write(HEADER + "\n")
            for e in added:
                f.write(e.to_row() + "\n")
    except OSError as err:
        logger.error("misheard の追記に失敗: %s", err)
        return []
    return added
