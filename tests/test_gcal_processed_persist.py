"""処理済みイベント状態の永続化（デーモン再起動後の start_meeting 再送防止）の検証

実行: uv run python tests/test_gcal_processed_persist.py
"""
from __future__ import annotations
import datetime
import json
import logging
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["SHADOW_CLERK_DATA_DIR"] = _TMP

from shadow_clerk import gcal_monitor as gm  # noqa: E402

results: list[bool] = []
PFILE = os.path.join(_TMP, "gcal_processed.json")
gm.PROCESSED_FILE = PFILE
gm.SESSION_FILE = os.path.join(_TMP, ".clerk_session")  # 作らない = セッションなし


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def _event(eid: str, start_off: int, end_off: int) -> dict:
    now = datetime.datetime.utcnow()
    fmt = lambda off: (now + datetime.timedelta(minutes=off)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": eid, "summary": "週次定例", "start": {"dateTime": fmt(start_off)},
            "end": {"dateTime": fmt(end_off)}}


def _monitor() -> tuple[gm.GCalMonitor, list[str]]:
    sent: list[str] = []
    mon = gm.GCalMonitor({})
    mon._send_command = sent.append  # type: ignore[method-assign]
    mon._wait_for_silence = lambda *a, **k: True  # type: ignore[method-assign]
    return mon, sent


def _poll(mon: gm.GCalMonitor, events: list[dict]) -> None:
    gm._fetch_events = lambda *a, **k: events
    mon._poll(None, "primary", 2, 1)


def _load() -> dict:
    with open(PFILE, encoding="utf-8") as f:
        return json.load(f)


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def main() -> int:
    ongoing = [_event("ev1", -5, 30)]

    mon, sent = _monitor()
    _poll(mon, ongoing)
    check("1: 初回は start_meeting 送信", sent == ["start_meeting 週次定例"], str(sent))
    saved = _load() if os.path.exists(PFILE) else {}
    check("1: 状態が保存される",
          saved.get("version") == 1 and saved.get("events", {}).get("ev1", {}).get("state") == "started", str(saved))
    mon2, sent2 = _monitor()  # ユーザーが手動で会議を終了済み (セッションなし) → 再起動
    _poll(mon2, ongoing)
    check("1: 再起動後は start_meeting を再送しない", sent2 == [], str(sent2))

    ended = [_event("ev1", -60, -10)]
    _poll(mon2, ended)
    check("2: 終了後は end_meeting が1回送られる", sent2 == ["end_meeting"], str(sent2))
    mon3, sent3 = _monitor()
    _poll(mon3, ended)
    check("2: 再起動後に end_meeting を再送しない", sent3 == [], str(sent3))
    check("2: ended が永続化される", _load()["events"]["ev1"]["state"] == "ended")

    now = datetime.datetime.utcnow()
    old = (now - datetime.timedelta(days=2)).isoformat()
    fresh = (now + datetime.timedelta(minutes=30)).isoformat()
    with open(PFILE, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "events": {"old": {"state": "ended", "end": old},
                                            "new": {"state": "started", "end": fresh}}}, f)
    mon4, _ = _monitor()
    check("3: 1日以上前のエントリは読み込み時に捨てる",
          "old" not in mon4._processed and mon4._processed.get("new") == "started", str(mon4._processed))
    mon4._mark("x", "started", now + datetime.timedelta(minutes=5))
    keys = set(_load()["events"])
    check("3: 保存後のファイルにも古いエントリは残らない", keys == {"new", "x"}, str(keys))

    broken = "{not json"
    with open(PFILE, "w", encoding="utf-8") as f:
        f.write(broken)
    cap = _Capture()
    gm.logger.addHandler(cap)
    mon5, sent5 = _monitor()
    check("4: 破損ファイルは警告して空で開始", len(cap.records) == 1 and mon5._processed == {},
          str([r.getMessage() for r in cap.records]))
    check("4: 変更が無い間は破損ファイルを上書きしない", open(PFILE, encoding="utf-8").read() == broken)
    _poll(mon5, ongoing)
    check("4: 監視は動作し start_meeting が送られる", sent5 == ["start_meeting 週次定例"], str(sent5))
    check("4: 最初の変更で正常なファイルに置き換わる", _load()["events"]["ev1"]["state"] == "started")
    gm.logger.removeHandler(cap)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
