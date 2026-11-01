"""/api/status の console_transcript（AI アシスタントが見ている transcript）を、起動経路ごとに検証する

実行: uv run python tests/test_console_transcript_status.py
"""
from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from typing import Any

os.environ.setdefault(
    "SHADOW_CLERK_DATA_DIR",
    os.path.join(tempfile.gettempdir(), "shadow-clerk-console-transcript-test"))
os.makedirs(os.environ["SHADOW_CLERK_DATA_DIR"], exist_ok=True)

import shadow_clerk._daemon_console as console_mod  # noqa: E402
import shadow_clerk._daemon_recorder_command as rc_mod  # noqa: E402
from shadow_clerk import _daemon_summary_regen as regen_mod  # noqa: E402
from shadow_clerk._daemon_dashboard_base import _DashboardHandlerBase  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_console import _DashboardHandlerConsoleOps  # noqa: E402

_OUT = os.path.join(os.environ["SHADOW_CLERK_DATA_DIR"], "output")


class _FakeConsole:
    def __init__(self) -> None:
        self.running = False
        self.transcript = ""

    def is_running(self) -> bool:
        return self.running

    def start_if_stopped(self, argv: list[str], workdir: str) -> tuple[bool, bool]:
        started = not self.running
        self.running = True
        return True, started

    def send_after_ready(self, text: str) -> None:
        pass

    def emit_auto_started(self) -> None:
        pass


class _Status(_DashboardHandlerBase):
    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        self.sent: dict = {}
        tr = SimpleNamespace(model_size="m", language=None, _backend="whisper", _loaded_model_id="m")
        self.recorder = SimpleNamespace(
            _translate_thread=None, stop_event=SimpleNamespace(is_set=lambda: False), backend_name="x",
            transcriber=tr, output_path=os.path.join(_OUT, "transcript-20261031.txt"), mute_mic=False,
            mute_monitor=False, use_mic=True, use_monitor=True, _command_mode=False, talk=None)

    def _send_json(self, data: dict) -> None:
        self.sent = data


class _Start(_DashboardHandlerConsoleOps):
    def __init__(self, transcript: str) -> None:  # pylint: disable=super-init-not-called
        self.recorder = SimpleNamespace(_output_dir=_OUT, output_path=os.path.join(_OUT, "transcript-20261031.txt"))
        self.body = {"transcript": transcript}
        self.sent: dict = {}

    def _console_body(self) -> dict | None:
        return self.body

    def _send_json(self, data: dict) -> None:
        self.sent = data


def _status() -> Any:
    h = _Status()
    h._serve_status()
    return h.sent.get("console_transcript", "MISSING")


def _with_fake(fn: Any) -> tuple[Any, Any]:
    fake = _FakeConsole()
    orig = console_mod.get_console, regen_mod.get_console
    console_mod.get_console = regen_mod.get_console = lambda role=None: fake
    try:
        return fn(fake), _status()
    finally:
        console_mod.get_console, regen_mod.get_console = orig


def test_stopped_reports_null() -> None:
    _, st = _with_fake(lambda f: None)
    assert st is None


def test_dashboard_start() -> None:
    def run(fake: _FakeConsole) -> None:
        _Start("transcript-202610301712@週次定例.txt")._start_console()
    _, st = _with_fake(run)
    assert st == "transcript-202610301712@週次定例.txt"


def test_auto_analyze_start() -> None:
    orig = rc_mod.load_config
    rc_mod.load_config = lambda: {"auto_analyze": True}
    try:
        ok, st = _with_fake(lambda f: rc_mod._RecorderCommandMixin._maybe_start_analysis(
            None, os.path.join(_OUT, "transcript-202610311000@acme.txt")))
    finally:
        rc_mod.load_config = orig
    assert ok and st == "transcript-202610311000@acme.txt"


def test_summary_regen_start() -> None:
    def run(fake: _FakeConsole) -> None:
        orig_m, orig_o = regen_mod.summary_method, regen_mod._other_meeting_active
        regen_mod.summary_method = lambda p: "console"
        regen_mod._other_meeting_active = lambda p: False
        try:
            assert regen_mod.regenerate_summary(None, os.path.join(_OUT, "transcript-20261029.txt")) == "console"
        finally:
            regen_mod.summary_method, regen_mod._other_meeting_active = orig_m, orig_o
    _, st = _with_fake(run)
    assert st == "transcript-20261029.txt"


def test_after_stop_reports_null() -> None:
    def run(fake: _FakeConsole) -> None:
        _Start("transcript-20261029.txt")._start_console()
        fake.running = False
    _, st = _with_fake(run)
    assert st is None


def main() -> int:
    ok = True
    for fn in (test_stopped_reports_null, test_dashboard_start, test_auto_analyze_start,
               test_summary_regen_start, test_after_stop_reports_null):
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except Exception as e:  # pylint: disable=broad-except
            ok = False
            print(f"[FAIL] {fn.__name__}: {e!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
