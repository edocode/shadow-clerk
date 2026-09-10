"""AI 分析の対象外にする話題の一覧（値オブジェクト）"""
from __future__ import annotations
import logging
import os
from dataclasses import dataclass

from shadow_clerk._daemon_constants import FORBID_ANALYZE_FILE

logger = logging.getLogger("shadow-clerk")

# 1 項目の長さと件数の上限。UI からの入力をそのままファイルに落とすので、
# 際限なく太らせない
MAX_ITEM_LEN = 200
MAX_ITEMS = 100


@dataclass(frozen=True)
class ForbidAnalyze:
    """`- 個人の評価` のような 1 行 1 項目のリスト

    空・不在は「制限なし = どんな会話でも分析する」を意味する。
    スキルはこのファイルだけを根拠に対象を絞り、自分の判断で広げない。
    """

    items: tuple[str, ...]

    @classmethod
    def load(cls, path: str = "") -> "ForbidAnalyze":
        try:
            with open(path or FORBID_ANALYZE_FILE, "r", encoding="utf-8") as f:
                return cls(cls._parse(f.read()))
        except OSError:
            return cls(())

    @staticmethod
    def _parse(text: str) -> tuple[str, ...]:
        """`- x` も `x` も受ける。空行とコメントは落とす"""
        out: list[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("- ", "-\t")):
                line = line[2:].strip()
            elif line == "-":
                continue
            if line:
                out.append(line[:MAX_ITEM_LEN])
            if len(out) >= MAX_ITEMS:
                break
        return tuple(out)

    @classmethod
    def from_items(cls, items: object) -> "ForbidAnalyze":
        """UI から来た配列を正規化する。文字列以外と重複は落とす"""
        seen: list[str] = []
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, str):
                continue
            v = it.strip()[:MAX_ITEM_LEN]
            if v and v not in seen:
                seen.append(v)
            if len(seen) >= MAX_ITEMS:
                break
        return cls(tuple(seen))

    def save(self, path: str = "") -> bool:
        target = path or FORBID_ANALYZE_FILE
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w", encoding="utf-8") as f:
                f.write("".join(f"- {i}\n" for i in self.items))
            return True
        except OSError as e:
            logger.error("forbid-ai-analyze の保存に失敗: %s", e)
            return False
