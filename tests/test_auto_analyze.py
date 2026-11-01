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
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import quote

DATA = os.path.join(tempfile.gettempdir(), "shadow-clerk-autoanalyze-test")
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault("SHADOW_CLERK_DATA_DIR", DATA)

from shadow_clerk import _daemon_recorder_command as rc  # noqa: E402
from shadow_clerk import _daemon_dashboard_ops_console as oc  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_console import _DashboardHandlerConsoleOps  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_skill import _DashboardHandlerSkillOps as Ops  # noqa: E402
from shadow_clerk._daemon_recorder_command import _RecorderCommandMixin  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Host(_RecorderCommandMixin):
    """_maybe_start_analysis だけを呼ぶための最小の器"""

    def __init__(self) -> None:
        pass


@contextmanager
def _patched(mod: object, **attrs: object) -> Iterator[None]:
    """モジュール属性を差し替え、抜けるときに必ず戻す（同じプロセスの他のテストを汚さない）"""
    orig = {k: getattr(mod, k) for k in attrs}
    for k, v in attrs.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in orig.items():
            setattr(mod, k, v)


@contextmanager
def _patch(auto: bool, starter) -> Iterator[_Host]:
    with _patched(rc, load_config=lambda: {"auto_analyze": auto}, start_console_for=starter):
        yield _Host()


def test_disabled_by_default() -> None:
    calls: list[str] = []
    with _patch(False, lambda p, auto=False: calls.append(p) or True) as host:
        started = host._maybe_start_analysis("/tmp/t.txt")
    check("auto_analyze が false なら起動しない", started is False and not calls,
          repr(calls))


def test_enabled_starts() -> None:
    calls: list[str] = []

    def _start(path: str, auto: bool = False) -> bool:
        calls.append(path)
        return True

    with _patch(True, _start) as host:
        started = host._maybe_start_analysis("/tmp/t.txt")
    check("auto_analyze が true なら起動する", started is True, repr(calls))
    check("transcript のパスを渡す", calls == ["/tmp/t.txt"], repr(calls))


def test_failure_is_swallowed() -> None:
    def _boom(_path: str, auto: bool = False) -> bool:
        raise RuntimeError("boom")

    with _patch(True, _boom) as host:
        # 起動に失敗しても会議そのものは続く。例外を外に出さないこと
        started = host._maybe_start_analysis("/tmp/t.txt")
    check("起動失敗で例外を投げない", started is False)


def test_meeting_without_analysis_is_skipped() -> None:
    """会議ごとの設定で analyze: false の会議は、auto_analyze が有効でも起動しない"""
    calls: list[str] = []
    cfg = os.path.join(DATA, "meeting-analyze.yaml")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("meetings:\n  - pattern: 雑談\n    analyze: false\n")
    os.environ["MEETING_CONFIG"] = cfg
    try:
        with _patch(True, lambda p, auto=False: calls.append(p) or True) as host:
            skipped = host._maybe_start_analysis("/tmp/transcript-202610271000@雑談.txt")
            started = host._maybe_start_analysis("/tmp/transcript-202610271000@週次定例.txt")
    finally:
        del os.environ["MEETING_CONFIG"]
    check("analyze: false の会議では起動しない", skipped is False, repr(calls))
    check("ほかの会議は起動する", started is True and calls == ["/tmp/transcript-202610271000@週次定例.txt"], repr(calls))


def test_meeting_analyze_overrides_auto() -> None:
    """(auto_analyze, 会議の analyze): 未指定なら auto_analyze、オン・オフならそれに従う"""
    cfg = os.path.join(DATA, "meeting-analyze3.yaml")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("meetings:\n  - pattern: 週次定例\n    analyze: true\n  - pattern: 雑談\n    analyze: false\n")
    os.environ["MEETING_CONFIG"] = cfg
    try:
        for auto, name, want in ((True, "other", True), (False, "other", False),
                                 (False, "週次定例", True), (True, "雑談", False)):
            calls: list[str] = []
            with _patch(auto, lambda p, auto=False, calls=calls: calls.append(p) or True) as host:
                started = host._maybe_start_analysis(f"/tmp/transcript-202610311000@{name}.txt")
            check(f"auto_analyze={auto} 会議={name} → {'起動' if want else '起動しない'}",
                  started is want and bool(calls) is want, repr(calls))
    finally:
        del os.environ["MEETING_CONFIG"]


class _MeetingHost(_RecorderCommandMixin):
    """start_meeting の配線だけを見るための最小の器"""

    def __init__(self, output_dir: str) -> None:
        self._output_dir = output_dir
        self.transcript_lock = threading.Lock()
        self.output_path = ""
        self.current_session = None
        self._explicit_output = False
        self.args = type("_Args", (), {"output": ""})()

    def _get_default_output(self) -> str:
        return os.path.join(self._output_dir, "transcript-20261031.txt")

    def _finish_meeting(self, transcript_path: str) -> None:
        pass


class _Gcal:
    def __init__(self, name: str | None) -> None:
        self.name = name

    def get_ongoing_event_name(self) -> str | None:
        return self.name

    def get_ongoing_event_attendees(self) -> list[str]:
        return []


class _ResolveHandler(Ops):
    """GET /api/meeting-config/resolve を recorder 付きで呼ぶ器"""

    def __init__(self, recorder: object, meeting: str) -> None:
        self.recorder = recorder
        self.path = "/api/meeting-config/resolve?meeting=" + quote(meeting)
        self.client_address = ("127.0.0.1", 1)
        self.sent: dict = {}

    def _send_json(self, data: dict) -> None:
        self.sent = data


def test_calendar_name_shared() -> None:
    """名前なしの開始は、start_meeting コマンドと /api/meeting で同じ予定の名前になる"""
    for event in ("設計レビュー", None):
        host = _MeetingHost(DATA)
        host.gcal_monitor = _Gcal(event)
        host._maybe_start_analysis = lambda path: True  # type: ignore[method-assign]
        host._execute_command("start_meeting")
        by_cmd = os.path.basename(host.output_path).split("@")[1:] or [""]
        check(f"予定 {event!r}: 名前なし開始の名前とヘルパーが一致",
              host.calendar_meeting_name() == (event or "") and by_cmd[0].removesuffix(".txt") == (event or ""),
              repr((host.calendar_meeting_name(), host.output_path)))
        if os.path.exists(rc.SESSION_FILE):
            os.remove(rc.SESSION_FILE)


def test_session_override() -> None:
    """開始モーダルの選択はこの回だけ会議の設定より優先し、終われば設定に戻る"""
    cfg = os.path.join(DATA, "meeting-override.yaml")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("meetings:\n  - pattern: 雑談\n    analyze: false\n  - pattern: 週次定例\n    analyze: true\n")
    os.environ["MEETING_CONFIG"] = cfg
    try:
        for name, analyze, want in (("雑談", True, True), ("週次定例", False, False)):
            calls: list[str] = []
            with _patched(rc, load_config=lambda: {"auto_analyze": False},
                          start_console_for=lambda p, auto=False, calls=calls: calls.append(p) or True):
                host = _MeetingHost(DATA)
                host.start_meeting(name, analyze=analyze)
            check(f"{name} を analyze={analyze} で始める → {'起動' if want else '起動しない'}", bool(calls) is want, repr(calls))
            check(f"{name}: 会議中の resolve はこの回の選択 {want}", _resolve(host, name) is want)
            check(f"{name}: ほかの会議の resolve には効かない", _resolve(host, "other") is True)
            host._execute_command("end_meeting")
            check(f"{name}: 終わったら設定の値 {not want}", _resolve(host, name) is (not want))
    finally:
        del os.environ["MEETING_CONFIG"]


def _resolve(host: object, meeting: str) -> object:
    h = _ResolveHandler(host, meeting)
    h._serve_meeting_config_resolve()
    return h.sent.get("analyze")


class _ConsoleStart(_DashboardHandlerConsoleOps):
    """POST /api/console/start を recorder 付きで呼ぶ器"""

    def __init__(self, recorder: object, transcript: str) -> None:  # pylint: disable=super-init-not-called
        self.recorder = recorder
        self.body = {"transcript": transcript}
        self.sent: dict = {}

    def _console_body(self) -> dict | None:
        return self.body

    def _send_json(self, data: dict) -> None:
        self.sent = data


def test_manual_start_clears_off_override() -> None:
    """開始モーダルで外した会議でも、あとから手で頼んだら resolve は監視する側を返す"""
    with _patched(rc, load_config=lambda: {"auto_analyze": True}, start_console_for=lambda p, auto=False: True):
        host = _MeetingHost(DATA)
        host.start_meeting("週次定例", analyze=False)
    check("手で頼む前の resolve は false", _resolve(host, "週次定例") is False)
    started: list[str] = []
    with _patched(oc, start_console_for=lambda p, send_prompt=True: started.append(p) or True):
        _ConsoleStart(host, "transcript-20261031.txt")._start_console()
        check("ほかの transcript を頼んでもこの回の指定は残る", _resolve(host, "週次定例") is False)
        _ConsoleStart(host, os.path.basename(host.output_path))._start_console()
    check("開いている会議を手で頼むと resolve は true", _resolve(host, "週次定例") is True,
          repr(host.current_session))
    check("アシスタントは両方とも起動を頼まれる", len(started) == 2, repr(started))
    host._execute_command("end_meeting")


def test_manual_start_overrides_config_off() -> None:
    """会議設定でオフの会議（この回の指定なし）でも、手で頼んだら resolve は監視する側を返す"""
    cfg = os.path.join(DATA, "meeting-manual-off.yaml")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write("meetings:\n  - pattern: 雑談\n    analyze: false\n")
    os.environ["MEETING_CONFIG"] = cfg
    try:
        with _patched(rc, load_config=lambda: {"auto_analyze": True}, start_console_for=lambda p, auto=False: True):
            host = _MeetingHost(DATA)
            host.start_meeting("雑談")
        check("会議設定オフで手で頼む前の resolve は false", _resolve(host, "雑談") is False)
        with _patched(oc, start_console_for=lambda p, send_prompt=True: True):
            _ConsoleStart(host, os.path.basename(host.output_path))._start_console()
        check("会議設定オフでも手で頼むと resolve は true", _resolve(host, "雑談") is True, repr(host.current_session))
        host._execute_command("end_meeting")
        check("終わったら会議設定のオフに戻る", _resolve(host, "雑談") is False)
    finally:
        del os.environ["MEETING_CONFIG"]


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


def test_start_meeting_without_analysis() -> None:
    """語学の練習は analyze=False で始める。auto_analyze が有効でもアシスタントを起動しない"""
    calls: list[str] = []
    host = _MeetingHost(DATA)
    host._maybe_start_analysis = lambda path: calls.append(path) or True  # type: ignore[method-assign]
    host.start_meeting("英語練習", analyze=False)
    check("analyze=False ならアシスタントを起動しない", calls == [], str(calls))
    check("会議は始まる", host.output_path.endswith("@英語練習.txt") and host.current_session is not None,
          host.output_path)


def test_summary_goes_to_console_when_running() -> None:
    """コンソールが走っていれば議事録はそちらに頼み、LLM は回さない"""
    asked, spawned = [], []
    with _patched(rc, request_summary_from_console=lambda p: asked.append(p) or True):
        host = _Host()
        host._auto_summarize = lambda p: spawned.append(p)
        host._start_auto_summary({"auto_summary_via_console": True}, "/tmp/t.txt")
    check("コンソールに依頼する", asked == ["/tmp/t.txt"], repr(asked))
    check("LLM 要約は回さない", spawned == [], repr(spawned))


def test_summary_falls_back_to_llm() -> None:
    """コンソールが走っていなければ従来どおり LLM で作る（作られないのが最悪）"""
    spawned = []
    with _patched(rc, request_summary_from_console=lambda p: False):
        host = _Host()
        host._auto_summarize = lambda p: spawned.append(p)
        host._start_auto_summary({"auto_summary_via_console": True}, "/tmp/t.txt")
        time.sleep(0.2)
    check("LLM にフォールバックする", spawned == ["/tmp/t.txt"], repr(spawned))


def test_summary_via_console_can_be_turned_off() -> None:
    asked, spawned = [], []
    with _patched(rc, request_summary_from_console=lambda p: asked.append(p) or True):
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
    with _patched(rc, request_summary_from_console=_boom):
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

    with _patch(True, _start) as host:
        host._maybe_start_analysis("/tmp/t.txt")
    check("自動起動には auto=True を渡す", seen == [{"path": "/tmp/t.txt", "auto": True}],
          repr(seen))


def main() -> int:
    test_disabled_by_default()
    test_enabled_starts()
    test_auto_flag_is_passed()
    test_failure_is_swallowed()
    test_meeting_without_analysis_is_skipped()
    test_meeting_analyze_overrides_auto()
    test_summary_goes_to_console_when_running()
    test_summary_falls_back_to_llm()
    test_summary_via_console_can_be_turned_off()
    test_summary_console_failure_falls_back()
    test_start_meeting_wires_maybe_start_analysis()
    test_start_meeting_without_analysis()
    test_calendar_name_shared()
    test_session_override()
    test_manual_start_clears_off_override()
    test_manual_start_overrides_config_off()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
