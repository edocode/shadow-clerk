"""会議中に transcript を削除しても recorder.output_path が日次に切り替わらないことの検証

実行: uv run python tests/test_meeting_delete_keeps_output.py
daemon も音声デバイスも不要。一時ディレクトリ内で完結する。
"""
from __future__ import annotations
import datetime
import io
import json
import os
import tempfile
import threading
import types

# **import より前に差し替えること。** SESSION_FILE は import 時に DATA_DIR から決まる
DATA = tempfile.mkdtemp(prefix="shadow-clerk-keepout-")
os.environ["SHADOW_CLERK_DATA_DIR"] = DATA

from shadow_clerk._daemon_constants import SESSION_FILE  # noqa: E402
from shadow_clerk._daemon_dashboard_ops import _DashboardHandlerOps as Ops  # noqa: E402
from shadow_clerk.domain import meeting_start_marker  # noqa: E402

results: list[bool] = []
START = datetime.datetime(2026, 10, 4, 10, 0)
MEETING = os.path.join(DATA, "transcript-202610041000@acme.txt")
DAILY = os.path.join(DATA, "transcript-20261004.txt")
MARKER = meeting_start_marker(START)


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Rec:
    def __init__(self, output: str, in_meeting: bool) -> None:
        self._output_dir = DATA
        self.output_path = output
        self.transcript_lock = threading.Lock()
        self.current_session = types.SimpleNamespace(started_at=START) if in_meeting else None

    def _get_default_output(self) -> str:
        return DAILY


class _Handler(Ops):
    def __init__(self, body: dict, rec: _Rec) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        self.recorder = rec
        self.file_watcher = None

    def _send_json(self, d: dict) -> None:
        self.sent = d


def _setup(path: str, content: str, in_meeting: bool) -> _Rec:
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    if in_meeting:
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            f.write(path)
    elif os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
    return _Rec(path, in_meeting)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_delete_lines_in_meeting() -> None:
    line = "[2026-10-04 10:01:00] hello\n"
    rec = _setup(MEETING, MARKER + line, True)
    h = _Handler({"lines": [line], "file": os.path.basename(MEETING)}, rec)
    h._delete_transcript_line()
    check("会議中: 出力先は会議ファイルのまま", rec.output_path == MEETING, rec.output_path)
    check("会議中: 開始マーカーだけで再作成", os.path.exists(MEETING) and _read(MEETING) == MARKER,
          repr(_read(MEETING) if os.path.exists(MEETING) else None))
    check("会議中: 削除は応答に載る", h.sent.get("deleted") == [os.path.basename(MEETING)], repr(h.sent))


def test_delete_file_in_meeting() -> None:
    rec = _setup(MEETING, MARKER + "[2026-10-04 10:01:00] hi\n", True)
    h = _Handler({"file": os.path.basename(MEETING)}, rec)
    h._delete_transcript_file()
    check("会議中ファイル削除: 出力先維持", rec.output_path == MEETING, rec.output_path)
    check("会議中ファイル削除: マーカーのみで再作成", os.path.exists(MEETING) and _read(MEETING) == MARKER)
    check("会議中ファイル削除: deleted を返す", h.sent.get("status") == "ok" and h.sent.get("deleted") == [os.path.basename(MEETING)], repr(h.sent))


def test_delete_not_in_meeting() -> None:
    rec = _setup(DAILY, "[2026-10-04 09:00:00] a\n", False)
    h = _Handler({"file": os.path.basename(DAILY)}, rec)
    h._delete_transcript_file()
    check("会議外: ファイルは消える", not os.path.exists(DAILY))
    check("会議外: 出力先は日次のまま/日次へ切替", rec.output_path == DAILY)
    other = os.path.join(DATA, "transcript-20261003.txt")
    rec = _setup(other, "[2026-10-03 09:00:00] a\n", False)
    _Handler({"file": os.path.basename(other)}, rec)._delete_transcript_file()
    check("会議外: 他の日のファイル削除で日次へ切替", rec.output_path == DAILY and not os.path.exists(other), rec.output_path)


if __name__ == "__main__":
    test_delete_lines_in_meeting()
    test_delete_file_in_meeting()
    test_delete_not_in_meeting()
    print(f"{sum(results)}/{len(results)} passed")
    raise SystemExit(0 if all(results) else 1)
