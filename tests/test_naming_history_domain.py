"""名前付け履歴の値オブジェクトのテスト"""
from __future__ import annotations

from shadow_clerk.domain.naming_history import NamingRecord


def test_naming_record_roundtrip() -> None:
    r = NamingRecord.new("相手A", "alice", True, ["2026-10-09 10:00:01"], ["t1"], ["t0"])
    back = NamingRecord.parse(r.to_json_line())
    assert back == r
    assert back.lines == ("2026-10-09 10:00:01",) and back.added == ("t1",) and back.removed == ("t0",)
    assert back.undone is False and len(back.id) == 32 and len(back.at) == 19


def test_naming_record_parse_broken() -> None:
    assert NamingRecord.parse("{") is None
    assert NamingRecord.parse('{"id": "x"}') is None
