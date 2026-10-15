"""グループの値オブジェクトのテスト"""
from __future__ import annotations

import pytest

from shadow_clerk.domain.speaker_group import (
    GROUP_PALETTE, GroupName, SpeakerEntry, is_color, next_group_color,
)


def test_group_name_strips() -> None:
    assert GroupName("  acme ").value == "acme"


@pytest.mark.parametrize("bad", ["", "  ", "[acme]", "ac]me", "a\nb", "x" * 51])
def test_group_name_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        GroupName(bad)


def test_is_color() -> None:
    assert is_color("#e57373")
    for bad in ["e57373", "#E57373", "#e5737", "red", None, 3, "#e57373;x"]:
        assert not is_color(bad)


def test_next_group_color_uses_unused_first_then_cycles() -> None:
    assert next_group_color([]) == GROUP_PALETTE[0]
    assert next_group_color([GROUP_PALETTE[0]]) == GROUP_PALETTE[1]
    assert next_group_color(list(GROUP_PALETTE)) == GROUP_PALETTE[0]
    assert all(is_color(c) for c in GROUP_PALETTE)


def test_speaker_entry_roundtrip() -> None:
    e = SpeakerEntry("acme", False)
    assert SpeakerEntry.from_dict(e.to_dict()) == e
    assert SpeakerEntry.from_dict({}) == SpeakerEntry("", True)


@pytest.mark.parametrize("bad", [None, [], "x", {"group": 1}, {"person": "yes"}])
def test_speaker_entry_rejects(bad: object) -> None:
    with pytest.raises(ValueError):
        SpeakerEntry.from_dict(bad)
