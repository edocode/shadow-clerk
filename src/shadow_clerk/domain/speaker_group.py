"""shadow-clerk domain: 話者のグループ（会社・組織）と、名前帳の1件"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

# 背景が明暗どちらでも読める中間色。ダッシュボードで style に直接入れるので形式を固定する
GROUP_PALETTE: tuple[str, ...] = ("#e57373", "#64b5f6", "#81c784", "#ffb74d",
                                  "#ba68c8", "#4db6ac", "#f06292", "#a1887f")
_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")
_MAX_GROUP_LEN = 50


def is_color(value: object) -> bool:
    return isinstance(value, str) and bool(_COLOR_RE.match(value))


def next_group_color(used: Iterable[str]) -> str:
    """まだ使っていないパレット色。使い切ったら使用数で巡回する"""
    used_list = list(used)
    for color in GROUP_PALETTE:
        if color not in used_list:
            return color
    return GROUP_PALETTE[len(used_list) % len(GROUP_PALETTE)]


@dataclass(frozen=True)
class GroupName:
    """グループ（会社・組織・チーム）の名前"""

    value: str

    def __post_init__(self) -> None:
        v = self.value.strip() if isinstance(self.value, str) else ""
        if not v:
            raise ValueError("グループ名が空")
        if len(v) > _MAX_GROUP_LEN:
            raise ValueError("グループ名が長すぎる")
        if "[" in v or "]" in v or any(ord(c) < 32 for c in v):
            raise ValueError("グループ名に使えない文字がある")
        object.__setattr__(self, "value", v)


@dataclass(frozen=True)
class SpeakerEntry:
    """名前帳の1件。person=False は会社名・役割名のラベル（声紋に登録しない）"""

    group: str = ""
    person: bool = True

    def to_dict(self) -> dict[str, object]:
        return {"group": self.group, "person": self.person}

    @classmethod
    def from_dict(cls, d: object) -> SpeakerEntry:
        if not isinstance(d, dict):
            raise ValueError("名前帳の項目がオブジェクトではない")
        group, person = d.get("group", ""), d.get("person", True)
        if not isinstance(group, str) or not isinstance(person, bool):
            raise ValueError("名前帳の項目の型が不正")
        return cls(group, person)
