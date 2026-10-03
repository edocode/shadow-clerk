"""EchoFilter の検証（Claude 自身の読み上げを monitor から見分ける）

実行: uv run python tests/test_talk_echo.py
"""
from __future__ import annotations
import sys

from shadow_clerk.domain import EchoFilter, SpokenSpan
from shadow_clerk.domain.talk_echo import normalize_for_echo

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def _filter() -> EchoFilter:
    f = EchoFilter(tail_sec=3.0, similarity=0.5, keep_sec=60.0)
    f.record(SpokenSpan(100.0, 103.0, "それはいい考えですね。"))
    f.record(SpokenSpan(103.2, 106.0, "期限はいつまでにしますか？"))
    return f


def test_normalize() -> None:
    check("空白・句読点・記号を除き小文字にする",
          normalize_for_echo(" それは、いい考え です！ OK? ") == "それはいい考えですok", normalize_for_echo(" それは、いい考え です！ OK? "))


def test_echo_detected() -> None:
    f = _filter()
    check("時間が重なり文も同じなら捨てる", f.is_echo(101.0, 104.0, "それはいい考えですね"))
    check("2文にまたがっても捨てる", f.is_echo(102.0, 106.5, "それはいい考えですね期限はいつまでにしますか"))
    check("誤認識を少し含んでも捨てる", f.is_echo(103.5, 107.0, "期限はいつまでにしますかね"))
    check("一部だけでも捨てる", f.is_echo(104.0, 106.0, "いつまでにしますか"))


def test_other_side_kept() -> None:
    f = _filter()
    check("時間が重なっても文が違えば残す", not f.is_echo(101.0, 104.0, "来週の金曜でどうでしょう"))
    check("時間が外れていれば似ていても残す", not f.is_echo(120.0, 122.0, "それはいい考えですね"))
    check("余裕の範囲（終了後3秒）は重なりとみなす", f.is_echo(108.5, 109.0, "期限はいつまでにしますか"))
    check("正規化して空なら残す", not f.is_echo(101.0, 104.0, "、。！"))
    check("履歴が無ければ残す", not EchoFilter().is_echo(101.0, 104.0, "それはいい考えですね"))


def test_old_history_dropped() -> None:
    f = EchoFilter(tail_sec=3.0, similarity=0.5, keep_sec=60.0)
    f.record(SpokenSpan(100.0, 103.0, "それはいい考えですね。"))
    f.record(SpokenSpan(200.0, 201.0, "はい。"))
    check("keep_sec より古い履歴は使わない", not f.is_echo(101.0, 104.0, "それはいい考えですね"))


def _chatty() -> EchoFilter:
    f = EchoFilter()
    f.record(SpokenSpan(100.0, 103.0, "それはいい考えですね。"))
    f.record(SpokenSpan(103.2, 106.0, "はい、そうですね。期限はいつまでにしますか？"))
    f.record(SpokenSpan(106.2, 110.0, "いいですね、それで進めましょう。来週の会議で確認します。"))
    return f


def test_ordinary_replies_kept() -> None:
    f = _chatty()
    for t in ["はい", "いいえ", "了解です", "いや、それは違うと思います", "うーん、どうでしょうね", "それでいいですか"]:
        check(f"返事は残す: {t}", not f.is_echo(104.0, 106.0, t))


def test_mangled_echo_dropped() -> None:
    f = _chatty()
    for t in ["それは良い考えですね", "期げんはいつまでにしますか", "いいですねそれで進めましょう"]:
        check(f"言い違いの反響は捨てる: {t}", f.is_echo(104.0, 108.0, t))


def test_overlaps() -> None:
    f = _filter()
    check("読み上げ中の区間は重なる", f.overlaps(101.0, 102.0))
    check("余裕を過ぎた区間は重ならない", not f.overlaps(120.0, 121.0))
    check("履歴が無ければ重ならない", not EchoFilter().overlaps(101.0, 102.0))


def test_reply_repeating_claude_kept() -> None:
    # 既定の余裕では、Claude が話し終えてから話し始めた返事は、Claude の言葉を繰り返していても残す
    f = EchoFilter()
    f.record(SpokenSpan(100.0, 103.0, "明日の会議は10時からでよろしいですか"))
    check("話し終えた後に始まる返事は残す", not f.is_echo(104.2, 106.0, "はい、明日の会議は10時からで大丈夫です"))
    check("読み上げ中に始まる反響は捨てる", f.is_echo(100.2, 104.0, "明日の会議は10時からでよろしいですか"))


if __name__ == "__main__":
    test_normalize()
    test_echo_detected()
    test_other_side_kept()
    test_old_history_dropped()
    test_ordinary_replies_kept()
    test_mangled_echo_dropped()
    test_reply_repeating_claude_kept()
    test_overlaps()
    sys.exit(0 if all(results) else 1)
