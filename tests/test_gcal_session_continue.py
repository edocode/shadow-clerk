"""デーモン再起動後、継続中の会議セッションに対して start_meeting を重複送信しない検証

実行: uv run python tests/test_gcal_session_continue.py
"""
from __future__ import annotations
import datetime
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["SHADOW_CLERK_DATA_DIR"] = _TMP

from shadow_clerk import gcal_monitor as gm  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def _event(start_off: int, end_off: int) -> dict:
    now = datetime.datetime.utcnow()
    fmt = lambda off: (now + datetime.timedelta(minutes=off)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": "ev1", "summary": "週次定例", "start": {"dateTime": fmt(start_off)},
            "end": {"dateTime": fmt(end_off)}}


def _run(session_name: str | None, events: list[dict]) -> tuple[list[str], gm.GCalMonitor]:
    path = os.path.join(_TMP, ".clerk_session")
    gm.SESSION_FILE = path
    if os.path.exists(path):
        os.remove(path)
    if session_name:
        with open(path, "w", encoding="utf-8") as f:
            f.write(os.path.join(_TMP, f"transcript-202610151100@{session_name}.txt"))
    sent: list[str] = []
    mon = gm.GCalMonitor({})
    mon._send_command = sent.append  # type: ignore[method-assign]
    mon._wait_for_silence = lambda *a, **k: True  # type: ignore[method-assign]
    gm._fetch_events = lambda *a, **k: events
    mon._poll(None, "primary", 2, 1)
    return sent, mon


def main() -> int:
    sent, mon = _run("週次定例", [_event(-5, 30)])
    check("同一会議のセッション継続中は start_meeting 送信なし", sent == [], str(sent))
    check("started 扱いになる", mon._processed.get("ev1") == "started")
    gm._fetch_events = lambda *a, **k: [_event(-60, -10)]
    mon._poll(None, "primary", 2, 1)
    check("終了時刻後は end_meeting が送られる", sent == ["end_meeting"], str(sent))

    sent, _ = _run(None, [_event(-5, 30)])
    check("セッションなしなら start_meeting 送信", sent == ["start_meeting 週次定例"], str(sent))

    sent, _ = _run("別会議", [_event(-5, 30)])
    check("別会議のセッションなら start_meeting 送信 (back-to-back)",
          sent == ["start_meeting 週次定例"], str(sent))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
