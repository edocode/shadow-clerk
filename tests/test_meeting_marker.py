"""会議ファイルの区切り行の検証（録音中の会議と、後から切り出した会議で同じ形）

実行: uv run python tests/test_meeting_marker.py
"""
from __future__ import annotations
import datetime
import sys

from shadow_clerk._daemon_dashboard_ops_meeting import _DashboardHandlerMeetingOps as Ops
from shadow_clerk.domain import MEETING_END_MARKER, meeting_start_marker

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_markers() -> None:
    at = datetime.datetime(2026, 10, 1, 10, 2, 11)
    check("開始は日時（分まで）入り", meeting_start_marker(at) == "--- 会議開始 2026-10-01 10:02 ---\n",
          repr(meeting_start_marker(at)))
    check("終了は録音中の会議と同じ", MEETING_END_MARKER == "--- 会議終了 ---\n")


def test_merge_uses_same_markers() -> None:
    existing = ["--- 会議開始 2026-10-01 10:00 ---\n", "[2026-10-01 10:00:05] [自分] a\n", "--- 会議終了 ---\n"]
    merged = Ops._merge_meeting_lines(existing, ["[2026-10-01 09:58:00] [相手] b\n"])
    check("マージ後も先頭行の時刻で開始を書く", merged[0] == "--- 会議開始 2026-10-01 09:58 ---\n", repr(merged[0]))
    check("末尾は会議終了", merged[-1] == MEETING_END_MARKER, repr(merged[-1]))
    check("本文は時刻順", merged[1:-1] == ["[2026-10-01 09:58:00] [相手] b\n", "[2026-10-01 10:00:05] [自分] a\n"],
          repr(merged))


if __name__ == "__main__":
    test_markers()
    test_merge_uses_same_markers()
    sys.exit(0 if all(results) else 1)
