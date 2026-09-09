"""Console エンドポイントの検証

実行: uv run python tests/test_console_ops.py
"""
from __future__ import annotations
import io
import json
import os
import tempfile

os.environ.setdefault(
    "SHADOW_CLERK_DATA_DIR",
    os.path.join(tempfile.gettempdir(), "shadow-clerk-console-ops-test"))
os.makedirs(os.environ["SHADOW_CLERK_DATA_DIR"], exist_ok=True)

from shadow_clerk._daemon_dashboard_ops_console import (  # noqa: E402
    _DashboardHandlerConsoleOps as Ops)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_OUTPUT_DIR = os.path.join(os.environ["SHADOW_CLERK_DATA_DIR"], "output")


class _FakeHandler(Ops):
    def __init__(self, body=None, client: str = "127.0.0.1",
                 output_dir: str = _OUTPUT_DIR, output_path: str | None = None,
                 headers: dict | None = None) -> None:
        raw = json.dumps(body if body is not None else {}).encode("utf-8")
        self.client_address = (client, 12345)
        self.headers = {"Content-Length": str(len(raw)), **(headers or {})}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        # daemon では DashboardHandler.recorder がクラス属性で入る
        self.recorder = type("_Rec", (), {
            "_output_dir": output_dir,
            "output_path": output_path or os.path.join(
                output_dir, "transcript-202609071200.txt"),
        })()

    def _send_json(self, data: dict) -> None:
        self.sent = data


class _FakeConsole:
    """start_console_for のロジックだけを検証するための偽 ConsoleSession"""

    def __init__(self, running: bool) -> None:
        self.running = running
        self.calls: list[str] = []

    def is_running(self) -> bool:
        return self.running

    def start_if_stopped(self, argv: list[str], workdir: str) -> tuple[bool, bool]:
        started = not self.running
        self.running = True
        self.calls.append("start_if_stopped")
        return True, started

    def write(self, text: str) -> None:
        self.calls.append(f"write:{text}")

    def send_after_ready(self, text: str) -> None:
        self.calls.append(f"send_after_ready:{text}")


def test_input_rejects_remote() -> None:
    h = _FakeHandler({"data": "x"}, client="10.0.0.9")
    h._console_input()
    check("外部からの入力を拒否する", h.sent.get("status") == "error", repr(h.sent))


def test_input_rejects_non_string() -> None:
    h = _FakeHandler({"data": 42})
    h._console_input()
    check("data が文字列でなければエラー", h.sent.get("status") == "error", repr(h.sent))


def test_input_rejects_oversized() -> None:
    h = _FakeHandler({"data": "x" * 9000})
    h._console_input()
    check("長すぎる入力を拒否する", h.sent.get("status") == "error", repr(h.sent))


def test_serve_console_shape() -> None:
    h = _FakeHandler()
    h._serve_console()
    for key in ("rows", "max_row", "cursor", "running"):
        check(f"snapshot に {key} がある", key in h.sent, repr(sorted(h.sent)))


def test_serve_console_rejects_remote() -> None:
    """I2: GET /api/console も localhost 限定にする(grid には mtg スキルの
    出力・ツールの標準出力がそのまま載りうるため)"""
    h = _FakeHandler(client="10.0.0.9")
    h._serve_console()
    check("外部からの GET を拒否する", h.sent.get("status") == "error", repr(h.sent))


def test_resize_clamps() -> None:
    from shadow_clerk._daemon_console import get_console
    h = _FakeHandler({"cols": 999999})
    h._console_resize()
    check("cols を上限で丸める", get_console().screen.columns <= 500,
          str(get_console().screen.columns))
    check("resize が成功を返す", h.sent.get("status") == "ok", repr(h.sent))


def test_stop_when_not_running() -> None:
    h = _FakeHandler()
    h._stop_console()
    check("走っていなくても stop はエラーにしない", h.sent.get("status") == "ok",
          repr(h.sent))


def test_start_console_rejects_path_escape() -> None:
    """_start_console のパス解決: 実際にアシスタントを起動させず、渡された
    transcript パスだけを記録するスタブに start_console_for を差し替えて検証する"""
    import shadow_clerk._daemon_dashboard_ops_console as _ops_mod
    recorded: list[str] = []
    orig = _ops_mod.start_console_for

    def _stub(transcript_path: str) -> bool:
        recorded.append(transcript_path)
        return True

    _ops_mod.start_console_for = _stub
    try:
        good = "transcript-202609071200@Board.txt"
        h = _FakeHandler({"transcript": good})
        h._start_console()
        check("正常なファイル名は output_dir を前置する",
              recorded[-1] == os.path.join(_OUTPUT_DIR, good), recorded[-1])

        for bad in ("..", ".", "/etc/passwd", "notes.md", "../../etc/passwd",
                    "transcript-202609071200@a/b.txt"):
            h = _FakeHandler({"transcript": bad})
            h._start_console()
            check(f"{bad!r} は拒否されて output_path にフォールバックする",
                  recorded[-1] == h.recorder.output_path, recorded[-1])
    finally:
        _ops_mod.start_console_for = orig


def test_start_console_for_always_uses_send_after_ready() -> None:
    """running/停止のどちらでも send_after_ready を使う(I1)。

    「起動済みなら即 write」だと、TUI がまだ起動中に届いた2回目の呼び出し
    (連打・auto_analyze 直後の発話コマンド・start_meeting の重複) が
    起動途中の端末にプロンプトを打ち込んで消してしまう。start_console_for
    は _daemon_console.py に定義されているので、そのモジュールの
    get_console を差し替える。
    """
    import shadow_clerk._daemon_console as _console_mod
    for running in (True, False):
        fake = _FakeConsole(running=running)
        orig_get_console = _console_mod.get_console
        _console_mod.get_console = lambda: fake  # noqa: B023
        try:
            ok = _console_mod.start_console_for("")
            check(f"成功を返す (running={running})", ok, str(fake.calls))
            check(f"常に send_after_ready を使う (running={running})",
                  any(c.startswith("send_after_ready:") for c in fake.calls), str(fake.calls))
            check(f"write は使わない (running={running})",
                  not any(c.startswith("write:") for c in fake.calls), str(fake.calls))
        finally:
            _console_mod.get_console = orig_get_console


def test_console_input_rejects_cross_origin() -> None:
    """C2: Origin が自分自身と異なる POST を拒否する(CSRF)"""
    h = _FakeHandler({"data": "x"}, headers={
        "Origin": "http://evil.example", "Host": "localhost:8765"})
    h._console_input()
    check("クロスオリジンの Origin を拒否する", h.sent.get("status") == "error", repr(h.sent))


def test_console_input_allows_same_origin() -> None:
    """C2: Origin が自分自身と一致する POST は通す"""
    h = _FakeHandler({"data": ""}, headers={
        "Origin": "http://localhost:8765", "Host": "localhost:8765"})
    h._console_input()
    check("同一オリジンの Origin は通す", h.sent.get("status") == "ok", repr(h.sent))


def test_console_input_allows_missing_origin() -> None:
    """C2: Origin ヘッダが無い POST(curl 等)は通す"""
    h = _FakeHandler({"data": ""})
    h._console_input()
    check("Origin ヘッダが無ければ通す(curl 経路)", h.sent.get("status") == "ok", repr(h.sent))


def test_console_body_rejects_non_dict_json() -> None:
    """I3: dict でない JSON ボディ([1,2] や "x")でも 500 にならずエラー応答する"""
    for bad_body in ([1, 2], "x", 42):
        h = _FakeHandler(bad_body)
        h._console_input()
        check(f"非 dict ボディ {bad_body!r} はエラー応答する",
              h.sent.get("status") == "error", repr(h.sent))


def main() -> int:
    test_input_rejects_remote()
    test_input_rejects_non_string()
    test_input_rejects_oversized()
    test_serve_console_shape()
    test_serve_console_rejects_remote()
    test_resize_clamps()
    test_stop_when_not_running()
    test_start_console_rejects_path_escape()
    test_start_console_for_always_uses_send_after_ready()
    test_console_input_rejects_cross_origin()
    test_console_input_allows_same_origin()
    test_console_input_allows_missing_origin()
    test_console_body_rejects_non_dict_json()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
