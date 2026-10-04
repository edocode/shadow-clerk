"""mtg スキル向けエンドポイントの検証

実行: uv run python tests/test_skill_api.py
daemon も音声デバイスも不要。一時ディレクトリ内で完結する。
"""
from __future__ import annotations
import io
import os
import tempfile
import threading

DATA = tempfile.mkdtemp(prefix="shadow-clerk-skillapi-")
os.environ.setdefault("SHADOW_CLERK_DATA_DIR", DATA)
os.environ["MEETING_CONFIG"] = os.path.join(DATA, "mtg.yaml")
with open(os.environ["MEETING_CONFIG"], "w", encoding="utf-8") as _f:
    _f.write("defaults:\n  verbosity: normal\n  history: 3\n"
             "meetings:\n  - pattern: 'Sprint[ _-]?MTG'\n    verbosity: minimal\n"
             "    interval: 20\n    note: 短時間\n")

from shadow_clerk._daemon_constants import SESSION_FILE  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_skill import (
    wrap_transcript,  # noqa: E402
    _DashboardHandlerSkillOps as Ops, _norm)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Handler(Ops):
    def __init__(self, query: str = "", client: str = "127.0.0.1",
                 active: str = "transcript-20260908.txt") -> None:
        self.path = "/api/session" + (f"?{query}" if query else "")
        self.client_address = (client, 1)
        self.headers = {"Content-Length": "0"}
        self.rfile = io.BytesIO(b"")
        self.sent: dict = {}
        self.recorder = type("_Rec", (), {
            "_output_dir": DATA,
            "output_path": os.path.join(DATA, active),
            "stop_event": threading.Event(),
        })()

    def _send_json(self, d: dict) -> None:
        self.sent = d


def _touch(name: str, body: str = "x\n") -> str:
    p = os.path.join(DATA, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    return p


def test_session_uses_session_file_not_mtime() -> None:
    """会議中かどうかは SESSION_FILE で決める。mtime の推測はしない"""
    _touch("transcript-20260908.txt", "a\nb\nc\n")
    try:
        os.remove(SESSION_FILE)
    except OSError:
        pass
    h = _Handler()
    h._serve_session()
    check("会議中でないと分かる", h.sent.get("in_meeting") is False, repr(h.sent.get("in_meeting")))
    check("行数を返す", h.sent.get("lines") == 3, repr(h.sent.get("lines")))
    check("経過秒を返す", isinstance(h.sent.get("age_seconds"), int))

    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        f.write("x")
    h = _Handler()
    h._serve_session()
    check("会議中だと分かる", h.sent.get("in_meeting") is True)
    os.remove(SESSION_FILE)


def test_session_returns_generated_paths() -> None:
    _touch("transcript-202609081132@週次定例.txt")
    _touch("advice-202609081132@週次定例.md")
    h = _Handler(active="transcript-202609081132@週次定例.txt")
    h._serve_session()
    check("会議名を返す", h.sent.get("meeting") == "週次定例", repr(h.sent.get("meeting")))
    check("advice の絶対パス",
          h.sent.get("advice") == os.path.join(DATA, "advice-202609081132@週次定例.md"),
          repr(h.sent.get("advice")))
    check("存在しない attendees は空",
          h.sent.get("attendees") == "", repr(h.sent.get("attendees")))


def test_session_rejects_remote() -> None:
    h = _Handler(client="10.0.0.9")
    h._serve_session()
    check("外部からの取得を拒否する", h.sent.get("status") == "error", repr(h.sent))


def test_config_resolve_matches_rule() -> None:
    h = _Handler("meeting=Sprint_MTG")
    h.path = "/api/meeting-config/resolve?meeting=Sprint_MTG"
    h._serve_meeting_config_resolve()
    check("ルールが当たる", h.sent.get("verbosity") == "minimal", repr(h.sent))
    check("interval も上書きされる", h.sent.get("interval") == 20, repr(h.sent))
    check("note を返す", h.sent.get("note") == "短時間", repr(h.sent))
    h.path = "/api/meeting-config/resolve?meeting=NoSuchMeeting"
    h._serve_meeting_config_resolve()
    check("当たらなければ defaults", h.sent.get("verbosity") == "normal", repr(h.sent))
    check("history の既定は 3", h.sent.get("history") == 3, repr(h.sent))


def test_history_normalised_match() -> None:
    for n in ("transcript-202608010900@1_on_1_alice_(offline).txt",
              "transcript-202608150900@1_on_1_alice(Offline).txt",
              "transcript-202609010900@1_on_1_alice(Offline).txt",
              "transcript-202609010900@別の会議.txt"):
        _touch(n)
    _touch("summary-202608010900@1_on_1_alice_(offline).md")
    h = _Handler(active="transcript-202609010900@1_on_1_alice(Offline).txt")
    h.path = "/api/meeting-history?meeting=1_on_1_alice(Offline)&count=5"
    h._serve_meeting_history()
    got = h.sent.get("meetings", [])
    check("表記ゆれを束ねる", len(got) == 2, repr([m["meeting"] for m in got]))
    check("新しい順", got[0]["datetime"] > got[1]["datetime"], repr([m["datetime"] for m in got]))
    check("進行中の回は含まない",
          all("202609010900@1_on_1_alice(Offline)" not in m["transcript"] for m in got))
    check("無関係な会議は含まない", all("別の会議" not in m["transcript"] for m in got))
    check("存在する summary のパスを返す", got[-1]["summary"].endswith(
        "summary-202608010900@1_on_1_alice_(offline).md"), repr(got[-1]["summary"]))
    check("存在しない analysis は空", got[-1]["analysis"] == "", repr(got[-1]["analysis"]))


def test_history_count_zero() -> None:
    h = _Handler()
    h.path = "/api/meeting-history?meeting=Sprint_MTG&count=0"
    h._serve_meeting_history()
    check("count=0 なら空", h.sent.get("meetings") == [], repr(h.sent))


def test_history_tail() -> None:
    body = "".join(f"[2026-10-01 09:{i:02d}:00] [自分] 行{i}\n" for i in range(20)) + "--- 会議終了 ---\n"
    _touch("transcript-202610010900@英語練習.txt", body)
    h = _Handler(active="transcript-202610040900@英語練習.txt")
    h.path = "/api/meeting-history?meeting=英語練習&count=3&tail=3"
    h._serve_meeting_history()
    got = h.sent.get("meetings", [])
    check("tail で transcript の末尾を足す", len(got) == 1 and got[0].get("tail") == [
        "[2026-10-01 09:18:00] [自分] 行18", "[2026-10-01 09:19:00] [自分] 行19", "--- 会議終了 ---"], repr(got))
    for query, expect, label in [("tail=0", None, "tail=0 なら足さない"), ("", None, "既定は足さない"),
                                 ("tail=abc", None, "数でなければ足さない"), ("tail=99", 21, "50 行まで（ファイルが短ければ全部）")]:
        h.path = "/api/meeting-history?meeting=英語練習&count=3" + (f"&{query}" if query else "")
        h._serve_meeting_history()
        row = h.sent["meetings"][0]
        check(label, (row.get("tail") is None) if expect is None else len(row["tail"]) == expect, repr(row.get("tail"))[:80])


def test_query_reads_raw_utf8() -> None:
    """curl は日本語の会議名を符号化せずに送り、http.server はそれを latin-1 として読む"""
    _touch("transcript-202610020900@英語練習.txt")
    h = _Handler(active="transcript-202610040900@英語練習.txt")
    h.path = "/api/meeting-history?meeting=英語練習&count=5".encode("utf-8").decode("latin-1")
    h._serve_meeting_history()
    check("生の UTF-8 の会議名でも当たる", [m["meeting"] for m in h.sent.get("meetings", [])] == ["英語練習", "英語練習"],
          repr(h.sent))
    h.path = "/api/meeting-history?meeting=%E8%8B%B1%E8%AA%9E%E7%B7%B4%E7%BF%92&count=5"
    h._serve_meeting_history()
    check("percent-encoding も従来どおり", len(h.sent.get("meetings", [])) == 2, repr(h.sent))


def test_norm() -> None:
    check("正規化: 大文字小文字と区切りを無視",
          _norm("1_on_1_alice_(offline)") == _norm("1 on 1 Alice(Offline)"),
          f"{_norm('1_on_1_alice_(offline)')} vs {_norm('1 on 1 Alice(Offline)')}")
    check("別物は束ねない", _norm("Sprint_MTG") != _norm("Platform_Standup"))


def test_watch_wraps_transcript() -> None:
    """流す行が <transcript> で囲まれること

    中身は音声認識の結果であって指示ではない。裸で流すと「まとめて」のような
    発言が指示として読まれる。
    """
    out = wrap_transcript("transcript-20260910.txt", "[12:00] [相手] まとめて\n").decode()
    check("開きタグにファイル名が入る",
          out.startswith('<transcript file="transcript-20260910.txt">\n'), out[:60])
    check("閉じタグで終わる", out.endswith("</transcript>\n"), out[-30:])
    check("本文はそのまま", "[12:00] [相手] まとめて" in out)

    # 境界は「行そのものが </transcript>」であること。本文がそれを名乗っても
    # 先頭に空白を入れて境界にならないようにする
    def terminators(text: str) -> int:
        return sum(1 for ln in text.split("\n") if ln == "</transcript>")

    out = wrap_transcript("t.txt", "a\n</transcript>\nb\n").decode()
    check("本文中の閉じタグは境界にならない", terminators(out) == 1, repr(out))
    check("無害化しても文字は残る", "</transcript>" in out.split("\n")[2], repr(out))

    out = wrap_transcript("t.txt", "</transcript>\n").decode()
    check("先頭が閉じタグでも境界は1つ", terminators(out) == 1, repr(out))

    out = wrap_transcript("t.txt", "改行なし").decode()
    check("改行が無ければ足す", out.endswith("改行なし\n</transcript>\n"), repr(out))


def test_wrap_with_other_tag() -> None:
    out = wrap_transcript("advice-20260910.md", "- 期限が未定\n</advice>\n", tag="advice").decode()
    check("タグを変えて囲える", out.startswith('<advice file="advice-20260910.md">\n') and out.endswith("</advice>\n"),
          repr(out))
    check("本文中の閉じタグは境界にならない", sum(1 for ln in out.split("\n") if ln == "</advice>") == 1, repr(out))


class _Stream(_Handler):
    """GET /api/watch を別スレッドで回すための偽物。書いたものを溜める"""

    def __init__(self, query: str, active: str) -> None:
        super().__init__(query, active=active)
        self.path = "/api/watch?" + query
        self.out = io.BytesIO()
        self.wfile = self.out
        self.status: int | None = None

    def send_response(self, code: int) -> None:
        self.status = code

    def send_header(self, k: str, v: str) -> None:
        pass

    def end_headers(self) -> None:
        pass

    def send_error(self, code: int) -> None:
        self.status = code


def test_watch_advice_streams_whole_file_on_change() -> None:
    import time
    active = "transcript-20260911.txt"
    _touch(active, "")
    _touch("advice-20260911.md", "- 最初の論点\n")
    h = _Stream("kind=advice&interval=1", active)
    th = threading.Thread(target=h._serve_watch, daemon=True)
    th.start()
    time.sleep(0.5)
    first = h.out.getvalue().decode()
    check("開始時に advice の中身を流す", '<advice file="advice-20260911.md">' in first and "最初の論点" in first, repr(first))
    time.sleep(1.2)
    check("変わっていなければ流さない", h.out.getvalue().decode().count("<advice ") == 1, repr(h.out.getvalue()))
    _touch("advice-20260911.md", "- 書き換えた論点\n")
    time.sleep(1.5)
    h.recorder.stop_event.set()
    th.join(timeout=3)
    out = h.out.getvalue().decode()
    check("書き換わったら全体を流し直す", out.count("<advice ") == 2 and "書き換えた論点" in out, repr(out))


def test_watch_advice_waits_for_file() -> None:
    import time
    active = "transcript-20260912.txt"
    _touch(active, "")
    h = _Stream("kind=advice&interval=1", active)
    th = threading.Thread(target=h._serve_watch, daemon=True)
    th.start()
    time.sleep(0.5)
    check("advice がまだ無ければ何も流さない", h.out.getvalue() == b"", repr(h.out.getvalue()))
    _touch("advice-20260912.md", "- 後からできた\n")
    time.sleep(1.5)
    h.recorder.stop_event.set()
    th.join(timeout=3)
    check("できたら流す", "後からできた" in h.out.getvalue().decode(), repr(h.out.getvalue()))


def test_watch_rejects_unknown_kind() -> None:
    h = _Stream("kind=nope", "transcript-20260911.txt")
    h._serve_watch()
    check("未知の kind は 400", h.status == 400, repr(h.status))


def _append(name: str, body: str) -> None:
    with open(os.path.join(DATA, name), "a", encoding="utf-8") as f:
        f.write(body)


def test_watch_follows_output_path() -> None:
    """日付が変わる・会議が始まる/終わると書き込み先が変わる。file 指定なしの監視は付いていく"""
    import time
    old, new = "transcript-20261003.txt", "transcript-20261004.txt"
    _touch(old, "[2026-10-03 23:59:58] [自分] 前の日\n")
    h = _Stream("interval=1", old)
    th = threading.Thread(target=h._serve_watch, daemon=True)
    th.start()
    time.sleep(0.3)
    _touch(new, "[2026-10-04 00:00:01] [自分] 次の日\n")
    h.recorder.output_path = os.path.join(DATA, new)
    time.sleep(1.2)
    _append(new, "[2026-10-04 00:00:05] [自分] 続き\n")
    time.sleep(1.2)
    h.recorder.stop_event.set()
    th.join(timeout=3)
    out = h.out.getvalue().decode()
    notice = f"<notice>書き込み先が {new} に変わりました</notice>"
    check("書き込み先が変わったら notice を流す", notice in out, repr(out))
    check("新しいファイルを先頭から流す", f'<transcript file="{new}">' in out and "次の日" in out
          and out.index(notice) < out.index("次の日"), repr(out))
    check("移ったあとの追記も流す", "続き" in out, repr(out))
    check("前のファイルの既存行は流さない", "前の日" not in out, repr(out))


def test_watch_with_file_stays() -> None:
    import time
    a, b = "transcript-20261005.txt", "transcript-20261006.txt"
    _touch(a, "")
    _touch(b, "")
    h = _Stream(f"interval=1&file={a}", a)
    th = threading.Thread(target=h._serve_watch, daemon=True)
    th.start()
    time.sleep(0.3)
    h.recorder.output_path = os.path.join(DATA, b)
    _append(b, "[2026-10-06 10:00:00] [自分] 別のファイル\n")
    _append(a, "[2026-10-05 10:00:00] [自分] 指定のファイル\n")
    time.sleep(1.2)
    h.recorder.stop_event.set()
    th.join(timeout=3)
    out = h.out.getvalue().decode()
    check("file 指定なら書き込み先が変わっても移らない", "<notice>" not in out and "指定のファイル" in out
          and "別のファイル" not in out, repr(out))


def main() -> int:
    test_session_uses_session_file_not_mtime()
    test_session_returns_generated_paths()
    test_session_rejects_remote()
    test_config_resolve_matches_rule()
    test_history_normalised_match()
    test_history_count_zero()
    test_history_tail()
    test_query_reads_raw_utf8()
    test_norm()
    test_watch_wraps_transcript()
    test_wrap_with_other_tag()
    test_watch_advice_streams_whole_file_on_change()
    test_watch_advice_waits_for_file()
    test_watch_rejects_unknown_kind()
    test_watch_follows_output_path()
    test_watch_with_file_stays()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
