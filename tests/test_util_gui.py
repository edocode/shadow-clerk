"""clerk-util gui の状態判定とログ追尾（tkinter を読み込まない部分）

実行: uv run pytest -q tests/test_util_gui.py
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("SHADOW_CLERK_DATA_DIR", tempfile.mkdtemp(prefix="shadow-clerk-gui-"))

from shadow_clerk._util_gui import DaemonState, resolve_state  # noqa: E402


def test_no_process_is_stopped() -> None:
    assert resolve_state(alive=False, api_ok=False, pending=None, elapsed=0.0) is DaemonState.STOPPED


def test_process_without_api_is_starting() -> None:
    """PID は生きているが API が未応答: モデル読み込み中。「起動中」と出す"""
    assert resolve_state(alive=True, api_ok=False, pending=None, elapsed=0.0) is DaemonState.STARTING


def test_process_with_api_is_running() -> None:
    assert resolve_state(alive=True, api_ok=True, pending=None, elapsed=0.0) is DaemonState.RUNNING


def test_stop_requested_while_alive_is_stopping() -> None:
    assert resolve_state(alive=True, api_ok=True, pending="stop", elapsed=1.0) is DaemonState.STOPPING


def test_stop_completed_is_stopped() -> None:
    assert resolve_state(alive=False, api_ok=False, pending="stop", elapsed=1.0) is DaemonState.STOPPED


def test_start_that_never_answers_fails_after_timeout() -> None:
    """起動を指示したのにプロセスが出てこない: 失敗と言い切る"""
    assert resolve_state(alive=False, api_ok=False, pending="start", elapsed=5.0) is DaemonState.STARTING
    assert resolve_state(alive=False, api_ok=False, pending="start", elapsed=90.1) is DaemonState.FAILED


def test_start_whose_api_never_answers_fails_after_timeout() -> None:
    """プロセスは残っているのに API が開かない（ポート衝突など）も失敗"""
    assert resolve_state(alive=True, api_ok=False, pending="start", elapsed=90.1) is DaemonState.FAILED


def test_stop_that_never_finishes_fails_after_timeout() -> None:
    assert resolve_state(alive=True, api_ok=True, pending="stop", elapsed=30.1) is DaemonState.FAILED


def test_running_without_pending_never_times_out() -> None:
    """稼働中は経過時間を見ない。長く開いていても失敗扱いにしない"""
    assert resolve_state(alive=True, api_ok=True, pending=None, elapsed=99999.0) is DaemonState.RUNNING


# ── ログ追尾 ───────────────────────────────────────────────────────

from shadow_clerk._util_gui import LogTail  # noqa: E402


def test_first_read_returns_the_tail_not_the_whole_file(tmp_path) -> None:
    """開いた直後に何万行も流し込まない。末尾の数行だけ見せる"""
    p = tmp_path / "daemon.log"
    p.write_text("".join(f"line{i}\n" for i in range(100)), encoding="utf-8")
    assert LogTail(str(p), max_lines=3).read_new() == ["line97", "line98", "line99"]


def test_second_read_returns_only_what_was_appended(tmp_path) -> None:
    p = tmp_path / "daemon.log"
    p.write_text("a\n", encoding="utf-8")
    tail = LogTail(str(p), max_lines=10)
    tail.read_new()
    with open(p, "a", encoding="utf-8") as f:
        f.write("b\nc\n")
    assert tail.read_new() == ["b", "c"]


def test_no_new_bytes_returns_nothing(tmp_path) -> None:
    p = tmp_path / "daemon.log"
    p.write_text("a\n", encoding="utf-8")
    tail = LogTail(str(p), max_lines=10)
    tail.read_new()
    assert tail.read_new() == []


def test_multibyte_lines_survive_the_offset(tmp_path) -> None:
    """日本語のログでオフセットがずれない（バイト単位で数える）"""
    p = tmp_path / "daemon.log"
    p.write_text("モデル読み込み中\n", encoding="utf-8")
    tail = LogTail(str(p), max_lines=10)
    assert tail.read_new() == ["モデル読み込み中"]
    with open(p, "a", encoding="utf-8") as f:
        f.write("モデル読み込み完了\n")
    assert tail.read_new() == ["モデル読み込み完了"]


def test_truncated_file_is_read_from_the_start(tmp_path) -> None:
    """ログが作り直されたら先頭から読み直す（オフセットを残すと永久に無言になる）"""
    p = tmp_path / "daemon.log"
    p.write_text("old1\nold2\nold3\n", encoding="utf-8")
    tail = LogTail(str(p), max_lines=10)
    tail.read_new()
    p.write_text("fresh\n", encoding="utf-8")
    assert tail.read_new() == ["fresh"]


def test_missing_file_is_not_an_error(tmp_path) -> None:
    """デーモンを一度も起動していなければログは無い。空で返す"""
    tail = LogTail(str(tmp_path / "absent.log"), max_lines=10)
    assert tail.read_new() == []


def test_a_line_still_being_written_is_held_until_its_newline(tmp_path) -> None:
    """改行前の書きかけを途中で出さない。次の読みで1行として出す"""
    p = tmp_path / "daemon.log"
    p.write_text("done\npart", encoding="utf-8")
    tail = LogTail(str(p), max_lines=10)
    assert tail.read_new() == ["done"]
    with open(p, "a", encoding="utf-8") as f:
        f.write("ial\n")
    assert tail.read_new() == ["partial"]


# ── 起動の失敗を拾う ───────────────────────────────────────────────

import sys  # noqa: E402
import time  # noqa: E402

from shadow_clerk._util_gui import spawn_detached  # noqa: E402


def _wait_failure(attempt, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = attempt.poll_failure()
        if msg is not None:
            return msg
        time.sleep(0.05)
    raise AssertionError("子プロセスが終了しなかった")


def test_a_child_that_dies_surfaces_its_stderr() -> None:
    """デーモンは多重起動を stderr に書いてから終わる。GUI はその文面を出したい"""
    attempt = spawn_detached(
        [sys.executable, "-c", "import sys; sys.stderr.write('既に起動しています (pid=1)\\n'); sys.exit(1)"])
    assert "既に起動しています" in _wait_failure(attempt)


def test_a_child_that_dies_silently_still_reports_the_exit_code() -> None:
    attempt = spawn_detached([sys.executable, "-c", "raise SystemExit(3)"])
    assert "3" in _wait_failure(attempt)


def test_a_running_child_reports_no_failure() -> None:
    attempt = spawn_detached([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert attempt.poll_failure() is None
    finally:
        attempt.terminate()


def test_a_command_that_does_not_exist_is_reported_not_raised() -> None:
    """clerk-daemon が見つからないのは、GUI では traceback ではなくメッセージにする"""
    attempt = spawn_detached(["shadow-clerk-no-such-executable"])
    assert "shadow-clerk-no-such-executable" in _wait_failure(attempt)


def test_a_child_that_forks_away_and_exits_zero_is_not_a_failure(tmp_path) -> None:
    """clerk-daemon -d は二重 fork して親が 0 で抜ける。成功した起動を失敗と呼ばない"""
    done = tmp_path / "forked"
    attempt = spawn_detached(
        [sys.executable, "-c", f"open({str(done)!r}, 'w').close(); raise SystemExit(0)"])
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline and not done.exists():
        time.sleep(0.05)
    assert done.exists(), "子プロセスが動かなかった"
    time.sleep(0.3)  # 終了が poll に見えるまで
    assert attempt.poll_failure() is None
