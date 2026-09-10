"""会議開始と連動した AI Console 起動の検証

実行: uv run python tests/test_auto_analyze.py
実際にアシスタントは起動せず、load_config と start_console_for を差し替えて
_maybe_start_analysis の分岐だけを見る。
"""
from __future__ import annotations
import os
import tempfile
import time
import threading

DATA = os.path.join(tempfile.gettempdir(), "shadow-clerk-autoanalyze-test")
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault("SHADOW_CLERK_DATA_DIR", DATA)

from shadow_clerk import _daemon_recorder_command as rc  # noqa: E402
from shadow_clerk._daemon_recorder_command import _RecorderCommandMixin  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Host(_RecorderCommandMixin):
    """_maybe_start_analysis だけを呼ぶための最小の器"""

    def __init__(self) -> None:
        pass


def _patch(auto: bool, starter) -> _Host:
    rc.load_config = lambda: {"auto_analyze": auto}
    rc.start_console_for = starter
    return _Host()


def test_disabled_by_default() -> None:
    calls: list[str] = []
    host = _patch(False, lambda p, auto=False: calls.append(p) or True)
    started = host._maybe_start_analysis("/tmp/t.txt")
    check("auto_analyze が false なら起動しない", started is False and not calls,
          repr(calls))


def test_enabled_starts() -> None:
    calls: list[str] = []

    def _start(path: str, auto: bool = False) -> bool:
        calls.append(path)
        return True

    host = _patch(True, _start)
    started = host._maybe_start_analysis("/tmp/t.txt")
    check("auto_analyze が true なら起動する", started is True, repr(calls))
    check("transcript のパスを渡す", calls == ["/tmp/t.txt"], repr(calls))


def test_failure_is_swallowed() -> None:
    def _boom(_path: str, auto: bool = False) -> bool:
        raise RuntimeError("boom")

    host = _patch(True, _boom)
    # 起動に失敗しても会議そのものは続く。例外を外に出さないこと
    started = host._maybe_start_analysis("/tmp/t.txt")
    check("起動失敗で例外を投げない", started is False)


class _MeetingHost(_RecorderCommandMixin):
    """start_meeting の配線だけを見るための最小の器"""

    def __init__(self, output_dir: str) -> None:
        self._output_dir = output_dir
        self.transcript_lock = threading.Lock()
        self.output_path = ""
        self.current_session = None
        self._explicit_output = False
        self.args = type("_Args", (), {"output": ""})()


def test_start_meeting_wires_maybe_start_analysis() -> None:
    """start_meeting が実際に _maybe_start_analysis を呼ぶことを確認する(I9)。

    test_disabled_by_default 等は _maybe_start_analysis を単体で見るだけなので、
    _daemon_recorder_command.py の start_meeting 側の呼び出し行を消しても
    それらのテストは全部通ってしまう。ここでは _execute_command 経由で
    実際に配線されているかを見る。
    """
    calls: list[str] = []
    host = _MeetingHost(DATA)
    host._maybe_start_analysis = lambda path: calls.append(path) or True  # type: ignore[method-assign]
    host._execute_command("start_meeting TestBoard")
    check("start_meeting が _maybe_start_analysis を呼ぶ", len(calls) == 1, str(calls))
    check("開始した transcript のパスを渡す",
          bool(calls) and calls[0] == host.output_path, str(calls))


def test_summary_goes_to_console_when_running() -> None:
    """コンソールが走っていれば議事録はそちらに頼み、LLM は回さない"""
    asked, spawned = [], []
    rc.request_summary_from_console = lambda p: asked.append(p) or True
    host = _Host()
    host._auto_summarize = lambda p: spawned.append(p)
    host._start_auto_summary({"auto_summary_via_console": True}, "/tmp/t.txt")
    check("コンソールに依頼する", asked == ["/tmp/t.txt"], repr(asked))
    check("LLM 要約は回さない", spawned == [], repr(spawned))


def test_summary_falls_back_to_llm() -> None:
    """コンソールが走っていなければ従来どおり LLM で作る（作られないのが最悪）"""
    spawned = []
    rc.request_summary_from_console = lambda p: False
    host = _Host()
    host._auto_summarize = lambda p: spawned.append(p)
    host._start_auto_summary({"auto_summary_via_console": True}, "/tmp/t.txt")
    time.sleep(0.2)
    check("LLM にフォールバックする", spawned == ["/tmp/t.txt"], repr(spawned))


def test_summary_via_console_can_be_turned_off() -> None:
    asked, spawned = [], []
    rc.request_summary_from_console = lambda p: asked.append(p) or True
    host = _Host()
    host._auto_summarize = lambda p: spawned.append(p)
    host._start_auto_summary({"auto_summary_via_console": False}, "/tmp/t.txt")
    time.sleep(0.2)
    check("false ならコンソールに頼まない", asked == [], repr(asked))
    check("false なら LLM で作る", spawned == ["/tmp/t.txt"], repr(spawned))


def test_summary_console_failure_falls_back() -> None:
    """依頼が例外を投げても議事録が消えない"""
    spawned = []
    def _boom(_p): raise RuntimeError("boom")
    rc.request_summary_from_console = _boom
    host = _Host()
    host._auto_summarize = lambda p: spawned.append(p)
    host._start_auto_summary({"auto_summary_via_console": True}, "/tmp/t.txt")
    time.sleep(0.2)
    check("例外でも LLM に落ちる", spawned == ["/tmp/t.txt"], repr(spawned))


def test_auto_flag_is_passed() -> None:
    """自動起動は手動と区別して知らせること

    ダッシュボードは会議開始で勝手に始まった分析だけ、議事録ペインと
    AI コンソールを自分で開く。手動起動では画面を動かさない。
    """
    seen: list[dict] = []

    def _start(path: str, auto: bool = False) -> bool:
        seen.append({"path": path, "auto": auto})
        return True

    host = _patch(True, _start)
    host._maybe_start_analysis("/tmp/t.txt")
    check("自動起動には auto=True を渡す", seen == [{"path": "/tmp/t.txt", "auto": True}],
          repr(seen))


def main() -> int:
    test_disabled_by_default()
    test_enabled_starts()
    test_auto_flag_is_passed()
    test_failure_is_swallowed()
    test_summary_goes_to_console_when_running()
    test_summary_falls_back_to_llm()
    test_summary_via_console_can_be_turned_off()
    test_summary_console_failure_falls_back()
    test_start_meeting_wires_maybe_start_analysis()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
