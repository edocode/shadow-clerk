"""shadow-clerk domain: 会議ごとの名前付け履歴（取り消しに使う）"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime


@dataclass(frozen=True)
class NamingRecord:
    """名前付け1回分の記録。lines は書き換えた transcript 行のタイムスタンプ、
    added は足したサンプルの recorded_at（source はその transcript 自身）、
    removed は label が名前付け済みだったとき、その人から外したサンプルの recorded_at"""

    id: str
    at: str
    label: str
    name: str
    person: bool
    lines: tuple[str, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    undone: bool = False

    @classmethod
    def new(cls, label: str, name: str, person: bool, lines: list[str] | tuple[str, ...],
            added: list[str] | tuple[str, ...], removed: list[str] | tuple[str, ...]) -> NamingRecord:
        return cls(uuid.uuid4().hex, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), label, name, person,
                   tuple(lines), tuple(added), tuple(removed))

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False) + "\n"

    @classmethod
    def parse(cls, line: str) -> NamingRecord | None:
        """1行をパースする。壊れた行は None"""
        try:
            d = json.loads(line)
            return cls(str(d["id"]), str(d["at"]), str(d["label"]), str(d["name"]), bool(d["person"]),
                       tuple(map(str, d["lines"])), tuple(map(str, d["added"])),
                       tuple(map(str, d["removed"])), bool(d.get("undone", False)))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            return None
