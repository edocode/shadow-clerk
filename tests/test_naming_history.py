"""名前付け履歴ファイルのテスト"""
from __future__ import annotations

import pytest

from shadow_clerk._daemon_naming_history import (
    NamingHistoryError, append_history, mark_undone, naming_path, read_history, split_history)
from shadow_clerk.domain.naming_history import NamingRecord


def _rec(rid: str, lines: list[str], added: list[str] | None = None, removed: list[str] | None = None) -> NamingRecord:
    return NamingRecord(rid, "2026-10-09 12:00:00", "相手A", "alice", True, tuple(lines),
                        tuple(added if added is not None else lines), tuple(removed or ()))


def test_history_append_read_and_mark_undone(tmp_path) -> None:
    t = str(tmp_path / "transcript-202610091000@acme.txt")
    assert read_history(t) == []
    assert naming_path(t) == str(tmp_path / "transcript-202610091000@acme.naming.jsonl")
    append_history(t, [_rec("a", ["2026-10-09 10:00:01"])])
    append_history(t, [_rec("b", ["2026-10-09 10:00:02"])])
    assert [r.id for r in read_history(t)] == ["a", "b"]
    done = mark_undone(t, "a")
    assert done is not None and done.undone and done.id == "a"
    assert [r.undone for r in read_history(t)] == [True, False]
    assert mark_undone(t, "a") is None and mark_undone(t, "zzz") is None


def test_history_broken_raises(tmp_path) -> None:
    t = str(tmp_path / "transcript-202610091000.txt")
    append_history(t, [_rec("a", ["2026-10-09 10:00:01"])])
    with open(naming_path(t), "a", encoding="utf-8") as f:
        f.write('{"id": "x"}\n')
    with pytest.raises(NamingHistoryError):
        read_history(t)
    with pytest.raises(NamingHistoryError):
        append_history(t, [_rec("b", ["2026-10-09 10:00:02"])])
    with pytest.raises(NamingHistoryError):
        mark_undone(t, "a")


def test_split_history_moves_in_range(tmp_path) -> None:
    src = str(tmp_path / "transcript-20261009.txt")
    dst = str(tmp_path / "transcript-202610091030@acme.txt")
    inside, outside = "2026-10-09 11:00:00", "2026-10-09 09:00:00"
    append_history(src, [_rec("in", [inside]), _rec("out", [outside]),
                         _rec("both", [outside, inside], removed=[outside])])
    assert split_history(src, dst, "2026-10-09 10:30:00", "2026-10-09 11:30:00") == 2
    assert [(r.id, r.lines, r.added, r.removed) for r in read_history(src)] == [
        ("out", (outside,), (outside,), ()), ("both", (outside,), (outside,), (outside,))]
    assert [(r.id, r.lines, r.added, r.removed) for r in read_history(dst)] == [
        ("in", (inside,), (inside,), ()), ("both", (inside,), (inside,), ())]
    assert split_history(str(tmp_path / "none.txt"), dst, "a", "b") == 0
