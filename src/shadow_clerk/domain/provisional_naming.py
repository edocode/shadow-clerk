"""shadow-clerk domain: 会議中の話者の仮登録（会議終了時に本登録する名前付け）"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

LineKey = tuple[str, str]  # (時刻, transcript 上の元のラベル)


@dataclass(frozen=True)
class ProvisionalNaming:
    """labels: ラベル → /api/speakers/assign の mapping の値（名前の文字列か {name, group?, person?, confirm?}）。
    lines: (時刻, 元のラベル) → /api/speakers/assign-lines の {name, group?, person?}。
    会議中は transcript を書き換えず、終了時に行 → ラベルの順で本登録する（行単位の指定が優先される）"""

    labels: dict[str, Any] = field(default_factory=dict)
    lines: dict[LineKey, dict[str, Any]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.labels and not self.lines

    def with_labels(self, mapping: dict[str, Any]) -> ProvisionalNaming:
        """ラベル単位の指定を足す。値が "" のラベルは仮登録の取り消し"""
        labels = {**self.labels, **mapping}
        return ProvisionalNaming({k: v for k, v in labels.items() if v != ""}, self.lines)

    def with_lines(self, targets: set[LineKey], assign: dict[str, Any] | None) -> ProvisionalNaming:
        """後からの指定で上書きする。assign None（または元のラベルに戻す指定）は、その行の仮登録の取り消し"""
        lines = dict(self.lines)
        for key in targets:
            if assign is None or assign["name"] == key[1]:
                lines.pop(key, None)
            else:
                lines[key] = dict(assign)
        return ProvisionalNaming(self.labels, lines)

    def line_groups(self) -> list[tuple[dict[str, Any], set[LineKey]]]:
        """同じ割り当ての行をまとめる（本登録で assign-lines を呼ぶ単位）"""
        groups: dict[str, tuple[dict[str, Any], set[LineKey]]] = {}
        for key, assign in self.lines.items():
            groups.setdefault(json.dumps(assign, sort_keys=True), (assign, set()))[1].add(key)
        return list(groups.values())

    @staticmethod
    def _name(value: Any) -> str:
        return value if isinstance(value, str) else value.get("name", "")

    def display(self) -> dict[str, Any]:
        """ダッシュボードの表示用。lines のキーは「時刻\\tラベル」、raw_labels はモーダルに入れ直す元の値"""
        return {"labels": {label: self._name(v) for label, v in self.labels.items()}, "raw_labels": self.labels,
                "lines": {f"{ts}\t{label}": a["name"] for (ts, label), a in self.lines.items()}}

    def to_json(self) -> str:
        return json.dumps({"labels": self.labels,
                           "lines": [{"ts": ts, "label": label, **a} for (ts, label), a in self.lines.items()]},
                          ensure_ascii=False)

    @classmethod
    def parse(cls, text: str) -> ProvisionalNaming:
        """壊れていれば ValueError"""
        try:
            raw = json.loads(text)
            labels = raw.get("labels", {})
            lines = {(x["ts"], x["label"]): {k: v for k, v in x.items() if k not in ("ts", "label")}
                     for x in raw.get("lines", [])}
        except (json.JSONDecodeError, AttributeError, KeyError, TypeError) as e:
            raise ValueError(str(e)) from e
        if not isinstance(labels, dict) or not all(isinstance(a.get("name"), str) for a in lines.values()):
            raise ValueError("仮登録の形式が不正")
        return cls(labels, lines)
