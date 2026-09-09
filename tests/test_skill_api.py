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
os.environ["MTG_CONFIG"] = os.path.join(DATA, "mtg.yaml")
with open(os.environ["MTG_CONFIG"], "w", encoding="utf-8") as _f:
    _f.write("defaults:\n  verbosity: normal\n  history: 3\n"
             "meetings:\n  - pattern: 'Sprint[ _-]?MTG'\n    verbosity: minimal\n"
             "    interval: 20\n    note: 短時間\n")

from shadow_clerk._daemon_constants import SESSION_FILE  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_skill import (  # noqa: E402
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
    h.path = "/api/mtg-config/resolve?meeting=Sprint_MTG"
    h._serve_mtg_config_resolve()
    check("ルールが当たる", h.sent.get("verbosity") == "minimal", repr(h.sent))
    check("interval も上書きされる", h.sent.get("interval") == 20, repr(h.sent))
    check("note を返す", h.sent.get("note") == "短時間", repr(h.sent))
    h.path = "/api/mtg-config/resolve?meeting=NoSuchMeeting"
    h._serve_mtg_config_resolve()
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


def test_norm() -> None:
    check("正規化: 大文字小文字と区切りを無視",
          _norm("1_on_1_alice_(offline)") == _norm("1 on 1 Alice(Offline)"),
          f"{_norm('1_on_1_alice_(offline)')} vs {_norm('1 on 1 Alice(Offline)')}")
    check("別物は束ねない", _norm("Sprint_MTG") != _norm("Platform_Standup"))


def main() -> int:
    test_session_uses_session_file_not_mtime()
    test_session_returns_generated_paths()
    test_session_rejects_remote()
    test_config_resolve_matches_rule()
    test_history_normalised_match()
    test_history_count_zero()
    test_norm()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
