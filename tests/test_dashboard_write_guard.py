"""ダッシュボードの書き込み API のガードと、file パラメータの transcript 名検証

実行: uv run --with pytest pytest -q tests/test_dashboard_write_guard.py
"""
from __future__ import annotations
import io
import json
import os
import tempfile

os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-guard-")

from shadow_clerk._daemon_dashboard_handler import DashboardHandler  # noqa: E402

DATA = os.environ["SHADOW_CLERK_DATA_DIR"]
DAILY = "transcript-20261016.txt"


class _Rec:
    def __init__(self) -> None:
        self._output_dir = DATA
        self.output_path = os.path.join(DATA, DAILY)
        self.commands: list[str] = []
        self.transcript_lock = __import__("threading").Lock()

    def _execute_command(self, cmd: str) -> None:
        self.commands.append(cmd)


class _Handler(DashboardHandler):
    def __init__(self, path: str, body: object = None, *, client: str = "127.0.0.1",
                 headers: dict | None = None) -> None:
        raw = json.dumps(body).encode("utf-8") if body is not None else b""
        self.path = path
        self.client_address = (client, 1)
        self.headers = {"Content-Length": str(len(raw)), **(headers or {})}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        self.errors: list[int] = []
        self.recorder = _Rec()
        self.file_watcher = None

    def _send_json(self, d: dict) -> None:
        self.sent = d

    def send_error(self, code: int, *_: object) -> None:
        self.errors.append(code)


def _write(name: str, text: str = "secret\n") -> str:
    p = os.path.join(DATA, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def test_post_from_lan_is_rejected() -> None:
    h = _Handler("/api/command", {"command": "mute_mic"}, client="192.168.1.20")
    h.do_POST()
    assert h.sent["status"] == "error" and h.recorder.commands == []


def test_cross_origin_post_is_rejected() -> None:
    h = _Handler("/api/command", {"command": "mute_mic"},
                 headers={"Host": "localhost:8765", "Origin": "http://evil.example"})
    h.do_POST()
    assert h.sent["status"] == "error" and h.recorder.commands == []


def test_same_origin_post_passes() -> None:
    h = _Handler("/api/command", {"command": "mute_mic"},
                 headers={"Host": "localhost:8765", "Origin": "http://localhost:8765"})
    h.do_POST()
    assert h.recorder.commands == ["mute_mic"]


def test_custom_exec_is_not_accepted_over_http() -> None:
    h = _Handler("/api/command", {"command": "custom_exec touch /tmp/pwned"})
    h.do_POST()
    assert h.sent["status"] == "error" and h.recorder.commands == []


def test_transcript_get_only_serves_transcript_names() -> None:
    _write(".env", "API_KEY=xyz\n")
    h = _Handler("/api/transcript?file=.env")
    h._serve_transcript()
    assert h.sent["lines"] == []
    _write(DAILY, "[2026-10-16 10:00:00] [自分] hello\n")
    h = _Handler(f"/api/transcript?file=../{DAILY}")
    h._serve_transcript()
    assert h.sent["lines"] == ["[2026-10-16 10:00:00] [自分] hello"]


def test_delete_file_refuses_non_transcript() -> None:
    cfg = _write("config.yaml", "a: 1\n")
    h = _Handler("/api/transcript/delete-file", {"file": "config.yaml"})
    h.do_POST()
    assert h.sent["status"] == "error" and os.path.exists(cfg)


def test_delete_file_removes_transcript() -> None:
    p = _write("transcript-202610161000@x.txt", "[2026-10-16 10:00:00] [自分] a\n")
    h = _Handler("/api/transcript/delete-file", {"file": "transcript-202610161000@x.txt"})
    h.do_POST()
    assert h.sent["status"] == "ok" and not os.path.exists(p)


_PNG = "data:image/png;base64,iVBORw0KGgo="


def test_screenshot_from_extension_passes() -> None:
    h = _Handler("/api/screenshot", {"image": _PNG},
                 headers={"Host": "127.0.0.1:8765", "Origin": "chrome-extension://abcdefgh",
                          "Sec-Fetch-Site": "none"})
    h.do_POST()
    assert h.sent["status"] == "ok"


def test_screenshot_from_web_page_is_rejected() -> None:
    h = _Handler("/api/screenshot", {"image": _PNG},
                 headers={"Host": "127.0.0.1:8765", "Origin": "http://evil.example"})
    h.do_POST()
    assert h.sent["status"] == "error"


def test_extension_origin_is_rejected_elsewhere() -> None:
    h = _Handler("/api/command", {"command": "mute_mic"},
                 headers={"Host": "127.0.0.1:8765", "Origin": "chrome-extension://abcdefgh"})
    h.do_POST()
    assert h.sent["status"] == "error" and h.recorder.commands == []
