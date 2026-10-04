"""EchoFilter の検証（Claude の読み上げ中・直後の monitor を時間だけで捨てる）

実行: uv run python tests/test_talk_echo.py
"""
from __future__ import annotations
import sys

from shadow_clerk.domain import EchoFilter, SpokenSpan

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def _filter() -> EchoFilter:
    f = EchoFilter(tail_sec=3.0, keep_sec=60.0)
    f.record(SpokenSpan(100.0, 103.0, "それはいい考えですね。"))
    f.record(SpokenSpan(103.2, 106.0, "期限はいつまでにしますか？"))
    return f


def test_short_overlap_dropped() -> None:
    f = _filter()
    check("読み上げと重なる短い行（了解です）は捨てる", f.overlaps(101.0, 102.0))


def test_tail_and_after() -> None:
    f = _filter()
    check("終了後 tail_sec 内は捨てる", f.overlaps(108.5, 109.0))
    check("tail_sec を過ぎたら残す", not f.overlaps(109.5, 111.0))
    check("読み上げ前に終わる区間は残す", not f.overlaps(90.0, 99.0))


def test_default_tail() -> None:
    f = EchoFilter()
    f.record(SpokenSpan(100.0, 103.0, "それはいい考えですね。"))
    check("既定の tail で終了後 0.5 秒に始まる区間は残す", not f.overlaps(103.5, 105.0))
    check("既定の tail で終了直後に始まる区間は捨てる", f.overlaps(103.1, 105.0))


def test_text_irrelevant() -> None:
    f = _filter()
    check("文が違っても重なれば捨てる", f.overlaps(101.0, 104.0))


def test_no_history() -> None:
    check("履歴が無ければ残す", not EchoFilter().overlaps(101.0, 104.0))


def test_old_history_dropped() -> None:
    f = EchoFilter(tail_sec=3.0, keep_sec=60.0)
    f.record(SpokenSpan(100.0, 103.0, "それはいい考えですね。"))
    f.record(SpokenSpan(200.0, 201.0, "はい。"))
    check("keep_sec より古い履歴は使わない", not f.overlaps(101.0, 104.0))
    check("新しい履歴は使う", f.overlaps(200.5, 201.5))


if __name__ == "__main__":
    test_short_overlap_dropped()
    test_tail_and_after()
    test_default_tail()
    test_text_irrelevant()
    test_no_history()
    test_old_history_dropped()
    sys.exit(0 if all(results) else 1)
