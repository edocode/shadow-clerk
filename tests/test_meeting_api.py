"""clerk-practice が叩く会議・ミュート・生成物の API の検証

実行: uv run python tests/test_meeting_api.py
daemon も音声デバイスも不要。一時ディレクトリ内で完結する。
"""
from __future__ import annotations
import io
import json
import os
import sys
import tempfile

# **import より前に差し替えること。** SESSION_FILE は import 時に DATA_DIR から決まる
DATA = tempfile.mkdtemp(prefix="shadow-clerk-meetingapi-")
os.environ["SHADOW_CLERK_DATA_DIR"] = DATA

from shadow_clerk._daemon_constants import SESSION_FILE  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_skill import _DashboardHandlerSkillOps as Ops  # noqa: E402

results: list[bool] = []
DAILY = "transcript-20261004.txt"


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Rec:
    """recorder の代役。start_meeting と _execute_command の効果だけを真似る"""

    def __init__(self, active: str = DAILY) -> None:
        self._output_dir = DATA
        self.output_path = os.path.join(DATA, active)
        self.mute_mic = False
        self.mute_monitor = False
        self.started: list[tuple[str, bool]] = []
        self.commands: list[str] = []

    def start_meeting(self, meeting_name: str, analyze: bool = True) -> None:
        self.started.append((meeting_name, analyze))
        self.output_path = os.path.join(DATA, f"transcript-202610041000@{meeting_name}.txt")
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            f.write(self.output_path)

    def _execute_command(self, cmd: str) -> None:
        self.commands.append(cmd)
        if cmd == "end_meeting":
            os.remove(SESSION_FILE)
            self.output_path = os.path.join(DATA, DAILY)
        elif cmd.endswith(("mute_mic", "mute_monitor")):
            setattr(self, cmd.removeprefix("un"), not cmd.startswith("un"))


class _Handler(Ops):
    def __init__(self, body: object, client: str = "127.0.0.1", rec: _Rec | None = None) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.client_address = (client, 1)
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        self.recorder = rec or _Rec()

    def _send_json(self, d: dict) -> None:
        self.sent = d


def _no_meeting() -> None:
    try:
        os.remove(SESSION_FILE)
    except FileNotFoundError:
        pass


def test_meeting_start() -> None:
    _no_meeting()
    h = _Handler({"action": "start", "name": "英語練習", "analyze": False})
    h._meeting()
    check("analyze false で会議を始める", h.recorder.started == [("英語練習", False)], repr(h.recorder.started))
    check("会議名・transcript・会議中を返す", h.sent == {
        "status": "ok", "meeting": "英語練習",
        "transcript": os.path.join(DATA, "transcript-202610041000@英語練習.txt"), "in_meeting": True}, repr(h.sent))
    rec = h.recorder
    h = _Handler({"action": "start", "name": "別の会議"}, rec=rec)
    h._meeting()
    check("会議中なら何もしない", rec.started == [("英語練習", False)] and h.sent.get("meeting") == "英語練習",
          repr(h.sent))
    _no_meeting()
    h = _Handler({"action": "start", "name": "週次 定例"})
    h._meeting()
    check("analyze の既定は true、名前は sanitize する", h.recorder.started == [("週次_定例", True)],
          repr(h.recorder.started))
    _no_meeting()


def test_meeting_start_rejects() -> None:
    _no_meeting()
    for body, label in [({"action": "start"}, "名前なし"), ({"action": "start", "name": ""}, "空の名前"),
                        ({"action": "start", "name": "..."}, "sanitize で空になる名前"),
                        ({"action": "start", "name": "x" * 101}, "101 字の名前"),
                        ({"action": "start", "name": 3}, "数値の名前"),
                        ({"action": "start", "name": "英語練習", "analyze": "no"}, "bool でない analyze"),
                        ({"action": "restart"}, "知らない action")]:
        h = _Handler(body)
        h._meeting()
        check(f"{label}は拒否", h.sent.get("status") == "error" and h.recorder.started == [], repr(h.sent))
    h = _Handler({"action": "start", "name": "x" * 100})
    h._meeting()
    check("100 字の名前は通す", len(h.recorder.started) == 1, repr(h.sent))
    _no_meeting()
    h = _Handler({"action": "start", "name": "英語練習"}, client="10.0.0.9")
    h._meeting()
    check("外部からは拒否", h.sent.get("status") == "error" and h.recorder.started == [], repr(h.sent))


def test_meeting_end() -> None:
    _no_meeting()
    rec = _Rec()
    _Handler({"action": "start", "name": "英語練習", "analyze": False}, rec=rec)._meeting()
    h = _Handler({"action": "end"}, rec=rec)
    h._meeting()
    check("会議中なら終える", rec.commands == ["end_meeting"] and h.sent == {
        "status": "ok", "meeting": "", "transcript": os.path.join(DATA, DAILY), "in_meeting": False}, repr(h.sent))
    h = _Handler({"action": "end"}, rec=rec)
    h._meeting()
    check("会議中でなければ何もしない", rec.commands == ["end_meeting"] and h.sent.get("status") == "ok", repr(h.sent))


def test_mute() -> None:
    rec = _Rec()
    h = _Handler({"source": "monitor", "muted": True}, rec=rec)
    h._set_mute()
    check("monitor をミュートして切り替え前を返す", rec.commands == ["mute_monitor"] and h.sent == {
        "status": "ok", "source": "monitor", "muted": True, "previous": False}, repr(h.sent))
    h = _Handler({"source": "monitor", "muted": True}, rec=rec)
    h._set_mute()
    check("すでにミュートなら previous は true", h.sent.get("previous") is True, repr(h.sent))
    h = _Handler({"source": "monitor", "muted": False}, rec=rec)
    h._set_mute()
    check("元に戻す", rec.mute_monitor is False and rec.commands[-1] == "unmute_monitor", repr(rec.commands))
    h = _Handler({"source": "mic", "muted": True}, rec=rec)
    h._set_mute()
    check("mic も切り替えられる", rec.mute_mic is True and h.sent.get("source") == "mic", repr(h.sent))
    for body, label in [({"source": "speaker", "muted": True}, "知らない source"),
                        ({"source": "monitor", "muted": "yes"}, "bool でない muted"), ({}, "指定なし")]:
        h = _Handler(body)
        h._set_mute()
        check(f"{label}は拒否", h.sent.get("status") == "error" and h.recorder.commands == [], repr(h.sent))
    h = _Handler({"source": "monitor", "muted": True}, client="10.0.0.9")
    h._set_mute()
    check("ミュートも外部からは拒否", h.sent.get("status") == "error" and h.recorder.commands == [], repr(h.sent))


if __name__ == "__main__":
    test_meeting_start()
    test_meeting_start_rejects()
    test_meeting_end()
    test_mute()
    _no_meeting()
    sys.exit(0 if all(results) else 1)
