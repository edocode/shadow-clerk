"""Shadow-clerk: clerk-util の GUI（デーモンの状態表示と起動・停止・再起動）

tkinter は使うときだけ読み込む。状態判定とログ追尾はここで純粋な関数として持ち、
GUI を開かずにテストできるようにする。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from enum import Enum

__all__ = ["DaemonState", "LogTail", "StartAttempt", "detect_scale", "resolve_scale",
           "resolve_state", "spawn_detached",
           "START_TIMEOUT_SEC", "STOP_TIMEOUT_SEC"]

# 起動を指示してから「稼働中」にならなければ失敗と言い切るまでの秒数。
# 初回起動は ASR モデルの取得を伴うので長めに取る（進捗はログ欄に出る）
START_TIMEOUT_SEC = 90.0
# 停止を指示してからプロセスが消えるまで待つ秒数
STOP_TIMEOUT_SEC = 30.0


class DaemonState(Enum):
    """GUI に出すデーモンの状態"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


def resolve_state(*, alive: bool, api_ok: bool, pending: str | None, elapsed: float) -> DaemonState:
    """プロセスの生死・API の応答・指示中の操作から表示する状態を決める。

    alive だけでは「起動中」と「稼働中」を区別できない。PID が生きていても
    ASR モデルを読み込んでいる間は /api/status が応答しないため、両方を見る。

    pending は "start" / "stop" / None、elapsed はその指示からの経過秒数。
    """
    if pending == "stop":
        if not alive:
            return DaemonState.STOPPED
        return DaemonState.FAILED if elapsed > STOP_TIMEOUT_SEC else DaemonState.STOPPING
    if pending == "start":
        if alive and api_ok:
            return DaemonState.RUNNING
        return DaemonState.FAILED if elapsed > START_TIMEOUT_SEC else DaemonState.STARTING
    if not alive:
        return DaemonState.STOPPED
    return DaemonState.RUNNING if api_ok else DaemonState.STARTING


# 初回に遡って読むバイト数。これを超える古いログは見ない
_TAIL_BYTES = 65536


class LogTail:
    """daemon.log の末尾を追う。初回は末尾だけ、以降は増えた分だけ返す。

    バイナリで開いてバイト単位のオフセットを持つ。テキストモードの seek は
    文字位置なので、日本語を含むログでは getsize のバイト数とずれる
    """

    def __init__(self, path: str, max_lines: int = 200) -> None:
        self._path = path
        self._max_lines = max_lines
        self._offset: int | None = None  # None = まだ一度も読んでいない
        self._partial = b""  # 改行がまだ来ていない書きかけの行

    def read_new(self) -> list[str]:
        """前回より後に書かれた完結した行を返す。ファイルが無ければ空"""
        try:
            with open(self._path, "rb") as f:
                size = f.seek(0, os.SEEK_END)
                if self._offset is None:
                    start = max(0, size - _TAIL_BYTES)
                    f.seek(start)
                    chunk = f.read()
                    if start > 0:
                        # 行の途中（多バイト文字の途中かもしれない）から読んでいるので
                        # 最初の改行までは捨てる
                        nl = chunk.find(b"\n")
                        chunk = chunk[nl + 1:] if nl >= 0 else b""
                elif size < self._offset:
                    # 作り直された。オフセットを残すと以降ずっと無言になる
                    self._offset, self._partial = 0, b""
                    f.seek(0)
                    chunk = f.read()
                else:
                    f.seek(self._offset)
                    chunk = f.read()
                self._offset = f.tell()
        except OSError:
            return []
        return self._split(chunk)[-self._max_lines:]

    def _split(self, chunk: bytes) -> list[str]:
        parts = (self._partial + chunk).split(b"\n")
        self._partial = parts.pop()  # 改行で終わっていれば空になる
        return [p.decode("utf-8", "replace").rstrip("\r") for p in parts]


class StartAttempt:
    """分離起動した子プロセスと、その早すぎる終了を説明するための stderr。

    デーモンはログファイルを開く前に stderr へ書いてから終わることがある
    （多重起動の「既に起動しています (pid=...)」など）。daemon.log には何も
    残らないので、最初の数行は GUI 側で預かっておく
    """

    def __init__(self, proc: subprocess.Popen | None, err_path: str, failure: str = "") -> None:
        self._proc = proc
        self._err_path = err_path
        self._failure = failure

    def poll_failure(self) -> str | None:
        """子が失敗して終了していれば理由を返す。動いている間と、正常に抜けた場合は None。

        終了コード 0 は失敗ではない。clerk-daemon -d は二重 fork（Windows は
        DETACHED_PROCESS で起こし直し）して親が 0 で抜けるので、起動が成功した
        ときほどこの子は即座にいなくなる。本当に立ち上がらなかった場合は
        resolve_state のタイムアウトが拾う
        """
        if self._failure:
            return self._failure
        if self._proc is None or self._proc.poll() is None or self._proc.returncode == 0:
            return None
        return self._stderr_text() or f"exit code {self._proc.returncode}"

    def terminate(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()

    def _stderr_text(self) -> str:
        try:
            with open(self._err_path, "rb") as f:
                return f.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""


def spawn_detached(argv: list[str], env: dict[str, str] | None = None) -> StartAttempt:
    """argv を親から切り離して起動する。GUI を閉じてもデーモンは残る。

    stderr は一時ファイルに流す。パイプにすると、誰も読まないまま子が
    書き続けたときにバッファが埋まって止まる
    """
    fd, err_path = tempfile.mkstemp(prefix="clerk-start-", suffix=".err")
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": fd}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(argv, env=env, close_fds=True, **kwargs)
    except OSError as e:
        return StartAttempt(None, err_path, failure=f"{argv[0]}: {e}")
    finally:
        os.close(fd)
    return StartAttempt(proc, err_path)


# --- GUI 本体（tkinter はここでだけ使う。読み込みも開くときまで遅らせる） ---

# Tk が 1pt = 1/72in と思い込む既定値。これに表示倍率を掛ける
_TK_BASE_SCALING = 96.0 / 72.0
# 既定の窓の大きさ（倍率 1.0 のときの論理ピクセル）
_WIN_W, _WIN_H = 620, 460


def detect_scale() -> float:
    """画面の表示倍率。取れなければ 1.0。

    GNOME の xwayland-native-scaling では X クライアントにネイティブ画素が渡り、
    Tk は 96dpi だと思い込む。HiDPI では文字も窓も半分の大きさになるので、
    コンポジタが使っている倍率を聞いて自分で補正する
    """
    try:
        out = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.DisplayConfig",
             "--object-path", "/org/gnome/Mutter/DisplayConfig",
             "--method", "org.gnome.Mutter.DisplayConfig.GetCurrentState"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=3, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return 1.0
    # 論理モニタのタプル先頭: (x, y, scale, transform, primary, [...])
    scales = [float(m) for m in re.findall(r"\(-?\d+, -?\d+, ([0-9.]+), \d+, (?:true|false), \[\(", out)]
    return max(scales) if scales else 1.0


# Tk が初期化時に作る名前付きフォント。倍率を掛け直す対象
_NAMED_FONTS = ("TkDefaultFont", "TkTextFont", "TkFixedFont", "TkMenuFont", "TkHeadingFont",
                "TkCaptionFont", "TkSmallCaptionFont", "TkIconFont", "TkTooltipFont")


def scale_named_fonts(tkfont: object, scale: float) -> None:
    """名前付きフォントの大きさに倍率を掛ける。

    これらは size=-12 のようにピクセルで作られているため `tk scaling` では
    一切変わらない。窓だけ大きくして文字が据え置きになるのを防ぐ
    """
    if scale == 1.0:
        return
    for name in _NAMED_FONTS:
        try:
            font = tkfont.nametofont(name)  # type: ignore[attr-defined]
        except Exception:  # そのテーマに無いフォントは飛ばす
            continue
        font.configure(size=int(round(font.cget("size") * scale)))  # 負値(px)でも符号は保たれる


def resolve_scale(config_value: object, detected: float) -> float:
    """config の gui_scale を解釈する。範囲外・数値でないものは自動検出に任せる"""
    try:
        value = float(config_value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return detected
    return value if 0.5 <= value <= 4.0 else detected


_POLL_UI_MS = 300        # 画面の更新間隔
_POLL_PROBE_SEC = 0.7    # プロセスと API を見に行く間隔（UI とは別スレッド）
_LOG_MAX_LINES = 500

_STATE_KEY = {
    DaemonState.STOPPED: "gui.state_stopped",
    DaemonState.STARTING: "gui.state_starting",
    DaemonState.RUNNING: "gui.state_running",
    DaemonState.STOPPING: "gui.state_stopping",
    DaemonState.FAILED: "gui.state_failed",
}
_STATE_COLOR = {
    DaemonState.STOPPED: "#888888",
    DaemonState.STARTING: "#c08000",
    DaemonState.RUNNING: "#1a8a3a",
    DaemonState.STOPPING: "#c08000",
    DaemonState.FAILED: "#c02020",
}


class _Probe:
    """プロセスの生死と API の応答を別スレッドで見続ける。

    /api/status はタイムアウトまで待たされることがある。UI スレッドで
    呼ぶとその間ウィンドウが固まるので、最新の結果だけを受け渡す
    """

    def __init__(self, port: int) -> None:
        import threading
        self._port = port
        self._lock = threading.Lock()
        self._alive = self._api_ok = False
        self._pid: int | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="clerk-gui-probe", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def snapshot(self) -> tuple[bool, bool, int | None]:
        with self._lock:
            return self._alive, self._api_ok, self._pid

    def _run(self) -> None:
        from shadow_clerk.clerk_util import _is_recorder_running, _read_pid
        while not self._stop.is_set():
            pid = _read_pid()
            alive = _is_recorder_running()
            api_ok = self._api_reachable() if alive else False
            with self._lock:
                self._alive, self._api_ok, self._pid = alive, api_ok, pid if alive else None
            self._stop.wait(_POLL_PROBE_SEC)

    def _api_reachable(self) -> bool:
        import urllib.request
        try:
            with urllib.request.urlopen(f"http://localhost:{self._port}/api/status", timeout=2) as r:
                return r.status == 200
        except Exception:
            return False


class _GuiApp:
    """状態・操作ボタン・ログ末尾の窓"""

    def __init__(self, daemon_args: list[str]) -> None:
        import threading
        import time
        import tkinter as tk
        import tkinter.font as tkfont
        from tkinter import ttk
        from shadow_clerk._daemon_config import load_config
        from shadow_clerk._daemon_constants import LOG_FILE
        from shadow_clerk.clerk_util import dashboard_port
        from shadow_clerk.i18n import t

        self._tk, self._time, self._threading, self._t = tk, time, threading, t
        self._daemon_args = daemon_args
        self._pending: str | None = None
        self._pending_at = 0.0
        self._attempt: StartAttempt | None = None
        self._restart_after_stop = False
        self._message = ""
        self._log_path = LOG_FILE
        self._tail = LogTail(LOG_FILE, max_lines=_LOG_MAX_LINES)
        self._probe = _Probe(dashboard_port())

        self._root = tk.Tk()
        self._root.title(t("gui.title"))
        # HiDPI 補正。これを入れないと分数スケールの画面で文字も窓も半分の大きさで出る
        scale = resolve_scale(load_config().get("gui_scale"), detect_scale())
        self._root.tk.call("tk", "scaling", _TK_BASE_SCALING * scale)
        scale_named_fonts(tkfont, scale)
        head_font = tkfont.Font(font=tkfont.nametofont("TkDefaultFont"))
        head_font.configure(size=int(round(head_font.cget("size") * 1.35)), weight="bold")
        self._root.geometry(f"{int(_WIN_W * scale)}x{int(_WIN_H * scale)}")
        self._root.minsize(int(480 * scale), int(300 * scale))

        head = ttk.Frame(self._root, padding=10)
        head.pack(fill="x")
        self._state_label = ttk.Label(head, text="", font=head_font)
        self._state_label.pack(anchor="w")
        self._message_label = ttk.Label(head, text="", wraplength=600, foreground="#c02020")
        self._message_label.pack(anchor="w", pady=(2, 8))

        buttons = ttk.Frame(head)
        buttons.pack(anchor="w")
        self._start_btn = ttk.Button(buttons, text=t("gui.start"), command=self._on_start)
        self._stop_btn = ttk.Button(buttons, text=t("gui.stop"), command=self._on_stop)
        self._restart_btn = ttk.Button(buttons, text=t("gui.restart"), command=self._on_restart)
        for b in (self._start_btn, self._stop_btn, self._restart_btn):
            b.pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text=t("gui.open_log"), command=self._on_open_log).pack(side="left", padx=(12, 0))

        body = ttk.Frame(self._root, padding=(10, 0, 10, 10))
        body.pack(fill="both", expand=True)
        self._log = tk.Text(body, height=14, wrap="none", state="disabled",
                            font=tkfont.nametofont("TkFixedFont"),
                            background="#101010", foreground="#d0d0d0", insertbackground="#d0d0d0")
        scroll = ttk.Scrollbar(body, orient="vertical", command=self._log.yview)
        self._log.configure(yscrollcommand=scroll.set)
        self._log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._append_log([t("gui.no_log")] if not os.path.exists(LOG_FILE) else [])

        self._root.protocol("WM_DELETE_WINDOW", self._on_close)

    def run(self) -> None:
        self._probe.start()
        self._tick()
        self._root.mainloop()

    # --- 操作 ---

    def _on_start(self) -> None:
        from shadow_clerk.clerk_util import daemon_env, find_clerk_daemon
        self._message = ""
        self._attempt = spawn_detached(
            [find_clerk_daemon(), "-d", *self._daemon_args], env=daemon_env())
        self._set_pending("start")

    def _on_stop(self) -> None:
        self._message = ""
        self._set_pending("stop")
        self._threading.Thread(target=self._terminate, name="clerk-gui-stop", daemon=True).start()

    def _on_restart(self) -> None:
        self._restart_after_stop = True
        self._on_stop()

    def _on_open_log(self) -> None:
        if sys.platform == "win32":
            os.startfile(self._log_path)  # noqa: S606  # pylint: disable=no-member
        else:
            subprocess.Popen(["xdg-open", self._log_path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _on_close(self) -> None:
        self._probe.stop()
        self._root.destroy()

    def _terminate(self) -> None:
        """停止は Windows の taskkill 待ちで数秒ブロックするので UI スレッドから出す"""
        from shadow_clerk.clerk_util import _read_pid, _terminate_pid
        pid = _read_pid()
        if pid:
            try:
                _terminate_pid(pid)
            except OSError as e:
                self._message = str(e)

    def _set_pending(self, action: str) -> None:
        self._pending, self._pending_at = action, self._time.monotonic()

    # --- 画面の更新 ---

    def _tick(self) -> None:
        alive, api_ok, pid = self._probe.snapshot()
        elapsed = self._time.monotonic() - self._pending_at if self._pending else 0.0
        state = resolve_state(alive=alive, api_ok=api_ok, pending=self._pending, elapsed=elapsed)
        self._settle(state, elapsed)
        if self._pending is None:
            # settle が指示を下ろした。「起動中…」のまま失敗を出さないよう状態を引き直す
            state = resolve_state(alive=alive, api_ok=api_ok, pending=None, elapsed=0.0)
        self._render(state, pid)
        self._append_log(self._tail.read_new())
        self._root.after(_POLL_UI_MS, self._tick)

    def _settle(self, state: DaemonState, elapsed: float) -> None:
        """指示が片付いたか、失敗したかを見て pending を下ろす"""
        if self._pending == "start" and self._attempt is not None:
            reason = self._attempt.poll_failure()
            if reason:  # 子が即終了した。daemon.log に残らない stderr はここにしかない
                self._message = self._t("gui.start_failed", reason=reason)
                self._pending, self._attempt = None, None
                return
        if state is DaemonState.FAILED:
            key = "gui.start_timeout" if self._pending == "start" else "gui.stop_timeout"
            sec = START_TIMEOUT_SEC if self._pending == "start" else STOP_TIMEOUT_SEC
            self._message = self._message or self._t(key, sec=sec)
            self._pending, self._restart_after_stop = None, False
            return
        if self._pending == "start" and state is DaemonState.RUNNING:
            self._pending, self._attempt = None, None
        elif self._pending == "stop" and state is DaemonState.STOPPED:
            self._pending = None
            if self._restart_after_stop:
                self._restart_after_stop = False
                self._on_start()

    def _render(self, state: DaemonState, pid: int | None) -> None:
        label = self._t(_STATE_KEY[state])
        if pid is not None and state in (DaemonState.RUNNING, DaemonState.STARTING, DaemonState.STOPPING):
            label = f"{label}  ({self._t('gui.pid', pid=pid)})"
        self._state_label.configure(text=f"● {label}", foreground=_STATE_COLOR[state])
        self._message_label.configure(text=self._message)
        busy = self._pending is not None
        self._start_btn.state(["disabled"] if busy or state is DaemonState.RUNNING else ["!disabled"])
        self._stop_btn.state(["disabled"] if busy or state is DaemonState.STOPPED else ["!disabled"])
        self._restart_btn.state(["disabled"] if busy else ["!disabled"])

    def _append_log(self, lines: list[str]) -> None:
        if not lines:
            return
        self._log.configure(state="normal")
        self._log.insert("end", "\n".join(lines) + "\n")
        # 古い行は捨てる。何時間も開けっぱなしにしても重くならないように
        if int(self._log.index("end-1c").split(".")[0]) > _LOG_MAX_LINES:
            self._log.delete("1.0", f"end-{_LOG_MAX_LINES}l")
        self._log.configure(state="disabled")
        self._log.see("end")


def run_gui(daemon_args: list[str]) -> None:
    """GUI を開く。tkinter が無ければ理由を出して終わる"""
    from shadow_clerk.i18n import t
    try:
        import tkinter  # noqa: F401
    except ImportError as e:
        print(t("gui.tk_missing", error=e), file=sys.stderr)
        sys.exit(1)
    _GuiApp(daemon_args).run()
