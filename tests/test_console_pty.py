"""AI Console の PTY セッション検証

実行: uv run python tests/test_console_pty.py
daemon も音声デバイスも不要。bash を PTY で起動する。
"""
from __future__ import annotations
import fcntl
import json
import os
import re
import tempfile
import threading
import time

os.environ.setdefault(
    "SHADOW_CLERK_DATA_DIR",
    os.path.join(tempfile.gettempdir(), "shadow-clerk-console-test"))
os.makedirs(os.environ["SHADOW_CLERK_DATA_DIR"], exist_ok=True)

import shadow_clerk._daemon_console as console_mod  # noqa: E402
from shadow_clerk._daemon_console import ConsoleSession, sanitized_env  # noqa: E402
from shadow_clerk._daemon_constants import (  # noqa: E402
    CONSOLE_READY_TIMEOUT_SEC, CONSOLE_TICK_SEC, VIRTUAL_ROWS,
)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def wait_for(pred, timeout: float = 5.0) -> bool:
    """pred() が True になるまで待つ。PTY は非同期なので固定 sleep にしない"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return False


def grid_text(sess: ConsoleSession) -> str:
    return "\n".join(sess.screen.display)


def test_env_sanitized() -> None:
    os.environ["CLAUDE_CODE_CHILD_SESSION"] = "x"
    os.environ["CLAUDECODE"] = "1"
    os.environ["CLAUDE_PID"] = "999"
    os.environ["ANTHROPIC_API_KEY"] = "keep-me"
    env = sanitized_env()
    check("CLAUDE_CODE_* を除去する", "CLAUDE_CODE_CHILD_SESSION" not in env)
    check("CLAUDECODE を除去する", "CLAUDECODE" not in env)
    check("CLAUDE_PID を除去する", "CLAUDE_PID" not in env)
    check("ANTHROPIC_* は残す", env.get("ANTHROPIC_API_KEY") == "keep-me")
    check("TERM を設定する", env.get("TERM") == "xterm-256color")


def test_echo_reaches_grid() -> None:
    sess = ConsoleSession()
    started = sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    check("bash が起動する", started)
    sess.write("echo HELLO_CONSOLE\r")
    ok = wait_for(lambda: "HELLO_CONSOLE" in grid_text(sess))
    check("echo の出力が grid に反映される", ok)
    check("max_row が進む", sess.max_row > 0, f"max_row={sess.max_row}")
    sess.stop()
    check("stop で is_running が False になる", not sess.is_running())


def test_rows_below_cursor_reach_client() -> None:
    """カーソルより下に描かれる行が配信されること

    TUI は入力枠の下辺や "auto mode on" のヒントをカーソルより下に描く。
    max_row は cursor.y の高水位なので、そこで dirty を切ると、それらの行は
    dirty を消されて一度もクライアントに届かない。
    """
    sess = ConsoleSession()
    sent: list[dict] = []
    sess.set_broadcaster(lambda kind, data: sent.append(json.loads(data)))
    # 3 行書いてカーソルを 1 行目に戻す = 2,3 行目がカーソルより下になる
    sess._stream.feed("top\r\n\x1b[7mBOTTOM_BORDER\x1b[27m\r\nHINT_ROW\x1b[2;1H")
    sess.max_row = max(sess.max_row, sess.screen.cursor.y)
    sess._emit_diff()
    check("カーソルより下の行も max_row に入る", sess.max_row >= 2,
          f"max_row={sess.max_row} cursor_y={sess.screen.cursor.y}")
    diffs = [m for m in sent if "rows" in m]
    rows = diffs[-1]["rows"] if diffs else {}
    text = " ".join("".join(t for t, _ in runs) for runs in rows.values())
    check("下辺の行が配信される", "BOTTOM_BORDER" in text, text[:80])
    check("ヒント行が配信される", "HINT_ROW" in text, text[:80])

    # 窓の外まで無条件に伸ばさない (pyte は reset で 1 万行 dirty にする)
    sess2 = ConsoleSession()
    sess2._stream.feed("\x1b[400;1Hdeep\x1b[1;1H")
    sess2.max_row = 0
    sess2._extend_max_row_below_cursor()
    check("窓の外の行までは伸ばさない", sess2.max_row <= console_mod.CONSOLE_BELOW_CURSOR_ROWS,
          f"max_row={sess2.max_row}")


def test_cols_survive_child_restart() -> None:
    """子を起こし直しても列数を引き継ぐこと

    子は会議のたびに起動し直る一方、ブラウザは幅が変わったときしか列数を
    送らない。start() が DEFAULT_COLS に戻すと、新しい子は 120 桁のまま
    固定され、ペインの右側が空いたままになる。
    """
    import struct as _struct
    import termios as _termios

    def winsize_cols(fd: int) -> int:
        packed = fcntl.ioctl(fd, _termios.TIOCGWINSZ, b"\0" * 8)
        return _struct.unpack("HHHH", packed)[1]

    # 覚えている列数は別テストと共有の記録に入るので、ここでは隔離する
    saved_file = console_mod.CONSOLE_COLS_FILE
    tmp = tempfile.TemporaryDirectory()
    console_mod.CONSOLE_COLS_FILE = os.path.join(tmp.name, "console.cols")

    sess = ConsoleSession()
    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    check("記録が無ければ既定の列数で開く",
          winsize_cols(sess._master_fd) == console_mod.DEFAULT_COLS,
          str(winsize_cols(sess._master_fd)))
    sess.resize(200)
    check("resize が PTY に伝わる", winsize_cols(sess._master_fd) == 200)
    check("grid も同じ列数になる", sess.screen.columns == 200, str(sess.screen.columns))
    sess.stop()
    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    check("起こし直しても列数を引き継ぐ", winsize_cols(sess._master_fd) == 200,
          str(winsize_cols(sess._master_fd)))
    check("起こし直した grid も引き継ぐ", sess.screen.columns == 200, str(sess.screen.columns))
    sess.stop()
    console_mod.CONSOLE_COLS_FILE = saved_file
    tmp.cleanup()


def test_stop_kills_process_group() -> None:
    """SIGTERM がプロセスグループ全体に届くことを確かめる。

    子が孫を産むと (claude はサブプロセスを起こす)、親だけ落としても
    孫が PTY を掴んだまま残る。start_new_session=True + killpg が効いて
    いるかは、孫が消えることでしか確認できない。
    """
    sess = ConsoleSession()
    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    sess.write("sleep 300 & echo PGID_$!\r")
    ok = wait_for(lambda: "PGID_" in grid_text(sess))
    check("孫プロセスを起こせた", ok)
    match = re.search(r"PGID_(\d+)", grid_text(sess))
    grandchild = int(match.group(1)) if match else 0
    check("孫の PID を取れた", grandchild > 0, str(grandchild))
    sess.stop()

    def _gone() -> bool:
        try:
            os.kill(grandchild, 0)
        except (ProcessLookupError, PermissionError):
            return True
        return False

    check("stop で孫プロセスも落ちる", wait_for(_gone, 5.0))


def test_stop_escalates_to_sigkill() -> None:
    """直下の子が SIGTERM で即死しても、セッションに残る孫には SIGKILL が届く。

    直下の子(bash -c スクリプト)は SIGTERM の既定動作で即死ぬ。
    `set -m` でジョブ制御を有効にした背景ジョブは別 pgrp に入るため、
    直下の子の死亡時にカーネルが前面 pgrp へ送る自動 SIGHUP の対象にも
    ならない(実測済み)。孫は明示的に SIGTERM を trap して無視するので、
    継続判定を「直下の子(proc)の生死」ではなく「セッションに残っている
    pid の有無」にしていなければ、この孫は SIGKILL を受け取らず永久に
    取り残される。
    """
    sess = ConsoleSession()
    script = (
        "set -m; "
        "(bash -c 'trap \"\" TERM; exec sleep 300') & echo TRAPPED_$!; "
        "exec sleep 300"
    )
    started = sess.start(["bash", "-c", script], os.getcwd())
    check("スクリプトが起動する", started)
    ok = wait_for(lambda: "TRAPPED_" in grid_text(sess))
    check("SIGTERM を無視する孫を起こせた", ok)
    match = re.search(r"TRAPPED_(\d+)", grid_text(sess))
    trapped = int(match.group(1)) if match else 0
    check("孫の PID を取れた", trapped > 0, str(trapped))
    sess.stop(timeout=1.0)

    def _gone() -> bool:
        try:
            os.kill(trapped, 0)
        except (ProcessLookupError, PermissionError):
            return True
        return False

    check("直下の子が先に死んでも孫は SIGKILL で落ちる", wait_for(_gone, 5.0))


def test_screen_geometry() -> None:
    sess = ConsoleSession()
    check("grid の行数が VIRTUAL_ROWS", sess.screen.lines == VIRTUAL_ROWS,
          f"lines={sess.screen.lines}")


def test_snapshot_and_broadcast() -> None:
    sess = ConsoleSession()
    seen: list[tuple[str, str]] = []
    sess.set_broadcaster(lambda ev, data: seen.append((ev, data)))
    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    sess.write("echo SNAP_OK\r")
    ok = wait_for(lambda: any("SNAP_OK" in d for _, d in seen))
    check("差分が broadcast される", ok)
    check("イベント名は console", all(ev == "console" for ev, _ in seen) and bool(seen))
    snap = sess.snapshot()
    check("snapshot に running が入る", snap["running"] is True)
    check("snapshot に cursor が入る", len(snap["cursor"]) == 2, repr(snap["cursor"]))
    sess.stop()
    ok = wait_for(lambda: any('"running": false' in d.replace(" ", " ")
                              or '"running":false' in d for _, d in seen), 3.0)
    check("停止が broadcast される", ok)


def test_cursor_up_overwrite() -> None:
    """TUI の再描画と同じ動きを PTY で再現する。

    2行出したあと cursor up で戻って上書きしたとき、grid 側に古い版が
    残らないことを確かめる。ここが壊れると Console に重複表示が出る。
    """
    sess = ConsoleSession()
    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    sess.write("printf 'OLDLINE\\nsecond\\n\\033[2A\\033[KNEWLINE\\n'\r")
    ok = wait_for(lambda: "NEWLINE" in grid_text(sess))
    check("上書き後の行が出る", ok)
    # bash のエコーバックで打鍵内容そのもの (literal "OLDLINE" を含む
    # コマンド文字列) が入力行に残るのは正常な挙動。ここで見たいのは
    # printf が実際に出力した行 (単独行として "OLDLINE") が cursor up +
    # 上書きで消えているかどうかであり、コマンドのエコー行と混同しない
    ok = wait_for(
        lambda: not any(line.strip() == "OLDLINE" for line in sess.screen.display),
        2.0)
    check("上書き前の行が残らない", ok, grid_text(sess)[:200])
    sess.stop()


def test_beyond_virtual_rows() -> None:
    """VIRTUAL_ROWS を超えてもクラッシュせず、grid がリセットされ、
    リセット後も末尾が正しく描画される。

    実時間で 10000 行書かせるのは重いので、VIRTUAL_ROWS を一時的に
    小さくして境界を早く踏ませる。ConsoleSession.__init__ / _emit_diff は
    _daemon_console モジュールのグローバル VIRTUAL_ROWS を実行のたびに
    参照する(import 時に値を束縛しない)ので、モジュール属性の上書きが
    そのまま効く。
    """
    original_rows = console_mod.VIRTUAL_ROWS
    console_mod.VIRTUAL_ROWS = 60
    try:
        sess = ConsoleSession()
        seen: list[tuple[str, str]] = []
        sess.set_broadcaster(lambda ev, data: seen.append((ev, data)))
        sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
        n = console_mod.VIRTUAL_ROWS + 50
        sess.write(f"for i in $(seq 1 {n}); do echo L$i; done\r")
        ok = wait_for(lambda: f"L{n}" in grid_text(sess), 30.0)
        check("VIRTUAL_ROWS 超でも末尾が描画される", ok)
        check("プロセスは生きている", sess.is_running())
        # for ループは 100ms の tick 間隔より速く終わりうるので、境界越えの
        # 検出は次の tick 到来まで遅れる。reset の broadcast をポーリングで待つ
        reset_seen = wait_for(lambda: any(
            ev == "console" and json.loads(data).get("full")
            for ev, data in seen), 3.0)
        check("grid のリセット(full snapshot)が起きた", reset_seen)
        # リセットは書かれた内容そのもの(L{n} 含む)を消す(スクロールバック
        # 消失は spec が許容済み)。リセット後もセッションが壊れておらず、
        # 新しい出力が末尾に正しく描画され続けることを別の目印で確認する
        sess.write("echo POST_RESET_OK\r")
        ok2 = wait_for(lambda: "POST_RESET_OK" in grid_text(sess), 5.0)
        check("リセット後も新しい出力が末尾に正しく描画される", ok2)
        check("リセット後は max_row が小さく戻っている(全10000行の再描画を抱えていない)",
              sess.max_row < console_mod.VIRTUAL_ROWS - 1, f"max_row={sess.max_row}")
        sess.stop()
    finally:
        console_mod.VIRTUAL_ROWS = original_rows


def test_start_after_child_self_exit_no_leak() -> None:
    """子が自分で終了した(is_running()=False, stop() 未呼び出し)状態で
    start() を呼んでも、console-tick スレッドと fd がリークしないことを
    確認する(C1)。

    is_running() が唯一の掃除ゲートなので、修正前は start() が
    self._master_fd を上書きし tick スレッドをもう1本起こす。3回繰り返し、
    tick スレッド数と open fd 数が反復しても増えないことを見る。

    broadcaster を設定するのは本番同等の配線にするため。未設定だと
    _emit_diff が fn is None で即 return し、tick スレッドが一度も
    self._lock に触れなくなるので、start() が stop() をロック内で呼ぶ
    (test_start_reentrant_lock_does_not_hold_lock_across_stop 参照) 競合を
    このテストは構造的に踏めない。
    """
    sess = ConsoleSession()
    sess.set_broadcaster(lambda ev, data: None)
    tick_counts: list[int] = []
    fd_counts: list[int] = []
    for i in range(3):
        started = sess.start(["bash", "-c", "exit 0"], os.getcwd())
        check(f"start が成功する (iter {i})", started)
        ok = wait_for(lambda: not sess.is_running(), 5.0)
        check(f"子プロセスが自ら終了する (iter {i})", ok)
        # 修正前のコードでは古い tick スレッドがここでまだ回っている余地がある
        time.sleep(CONSOLE_TICK_SEC * 5)
        tick_counts.append(
            len([t for t in threading.enumerate() if t.name == "console-tick"]))
        fd_counts.append(len(os.listdir("/proc/self/fd")))
    check("console-tick スレッドは反復しても1本のまま", tick_counts == [1, 1, 1],
          str(tick_counts))
    check("open fd は反復しても増えない", fd_counts[-1] <= fd_counts[0],
          str(fd_counts))
    sess.stop()


def test_start_reentrant_lock_does_not_hold_lock_across_stop() -> None:
    """start() が self._lock を保持したまま stop() を呼んでいないことを
    決定的に検証する回帰テスト。

    C1 (子が自分で終了したあと再起動すると fd と tick スレッドがリークする)
    を直すために start() は「_proc が None でなければ先に stop() する」を
    行うが、この呼び出しが with self._lock: の内側にあると、stop() が
    tick.join()/reader.join() で待つ相手 (console-tick の _emit_diff、
    console-reader の一部経路) が同じロックを取りに来るため join が
    進まなくなる (_lock は RLock なので start() 自身の再入は素通りするが、
    join は「別スレッドがロックを手放す」のを待つ操作であり、そのロックを
    start() 自身が握ったままなので手放されない)。

    実スレッドのスケジューリング(tick が「ちょうど _emit_diff の途中で
    ロック待ちしている瞬間」)に賭けると、CONSOLE_TICK_SEC(0.1秒)と
    stop() の join timeout(数秒)の兼ね合い次第で再現したりしなかったり
    する不安定なテストになる。そこで self._lock を「現在の再入深さ」を
    記録するトラッキング用の RLock に差し替える。RLock は同一スレッドの
    再入でのみ深さが2以上になり得る(別スレッドは深さ0まで解放されるまで
    acquire 自体がブロックされ、記録上も割り込めない)ので、
    「start() が stop() を呼ぶ間のどこかで深さが2以上に達したか」を見れば、
    スレッドの実行タイミングに一切依存せず「start() がロックを持ったまま
    stop() を呼んだか」を直接、決定的に判定できる。
    """
    sess = ConsoleSession()
    sess.set_broadcaster(lambda ev, data: None)

    class _TrackingRLock:
        """threading.RLock を包み、acquire 直後の再入深さを記録するだけの二重委譲"""

        def __init__(self) -> None:
            self._real = threading.RLock()
            self._depth = 0
            self.depths: list[int] = []

        def acquire(self, *args: object, **kwargs: object) -> bool:
            got = self._real.acquire(*args, **kwargs)
            if got:
                self._depth += 1
                self.depths.append(self._depth)
            return got

        def release(self) -> None:
            self._depth -= 1
            self._real.release()

        def __enter__(self) -> "_TrackingRLock":
            self.acquire()
            return self

        def __exit__(self, *args: object) -> None:
            self.release()

    tracker = _TrackingRLock()
    sess._lock = tracker  # type: ignore[assignment]  # pylint: disable=protected-access

    started = sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    check("(前提)1回目の start が成功する", started)
    ok = wait_for(lambda: sess.is_running(), 3.0)
    check("(前提)子プロセスが起動している", ok)

    # 子が自分で終了した状態を模す。stop() を経由させず proc.kill() で
    # 直接殺すことで、is_running()=False かつ self._proc は非 None のまま
    # (=C1 が対象にした「stop() 未呼び出しで死んだセッション」の状態) にする
    sess._proc.kill()  # pylint: disable=protected-access
    ok = wait_for(lambda: not sess.is_running(), 5.0)
    check("(前提)子プロセスが is_running()=False になる(stop() 未経由)", ok)

    tracker.depths.clear()
    t0 = time.monotonic()
    started2 = sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    elapsed = time.monotonic() - t0
    check("2回目の start が成功する", started2)
    max_depth = max(tracker.depths) if tracker.depths else 0
    check(
        "start() が stop() を呼んでいる間、自分自身は self._lock を保持していない"
        "(観測された再入深さの最大値が2未満)",
        max_depth < 2, f"depths={tracker.depths}")
    check("start() が数秒スタックしない(ロックを手放してから stop() を呼んでいる)",
          elapsed < 1.0, f"elapsed={elapsed:.2f}")

    tick_threads = [t for t in threading.enumerate() if t.name == "console-tick"]
    check("start() 完了時点で console-tick スレッドは1本だけ",
          len(tick_threads) == 1, str(len(tick_threads)))
    sess.stop()


def test_send_after_ready() -> None:
    """set_broadcaster した本番同等の配線でも ready 判定が働くことを確認する。

    以前は screen.buffer の非空判定を使っており、tick スレッドの
    _emit_diff() 自身が render_rows 経由で screen.buffer[0] を実体化
    させてしまうため、broadcaster を差すと子プロセスの実出力を待たずに
    ready 誤判定していた(15秒のタイムアウトフォールバックには乗っていた
    ので READY_SENT 自体は届いていたが、判定ロジックとしては壊れていた)。
    """
    sess = ConsoleSession()
    sess.set_broadcaster(lambda ev, data: None)
    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    t0 = time.monotonic()
    sess.send_after_ready("echo READY_SENT\r")
    ok = wait_for(lambda: "READY_SENT" in grid_text(sess), 20.0)
    elapsed = time.monotonic() - t0
    check("ready を待ってから送られる", ok)
    check("ready 判定のタイムアウトにフォールバックしていない (bash 起動直後に判定できる)",
          elapsed < CONSOLE_READY_TIMEOUT_SEC - 1.0, f"elapsed={elapsed:.2f}")
    sess.stop()


def test_emit_diff_does_not_fake_readiness() -> None:
    """_emit_diff 自身の副作用 (render_rows が screen.buffer[0] を実体化する)
    が ready 判定を誤って進めないことを確認する。

    screen.dirty は初期状態で全行入っており、_emit_diff は
    y <= self.max_row (初期値 0) に絞るので、子プロセスを起動すらせずに
    _emit_diff() を1回呼ぶだけで screen.buffer が非空になる。これは
    子プロセスの実際の出力とは無関係な副作用であり、ready 判定用の
    フラグ (_has_output) はこれに影響されてはならない。
    """
    sess = ConsoleSession()
    sess.set_broadcaster(lambda ev, data: None)
    check("emit_diff 前は screen.buffer が空", not sess.screen.buffer)
    sess._emit_diff()  # pylint: disable=protected-access
    check("emit_diff 1回で screen.buffer が実体化する(既知の pyte 副作用)",
          bool(sess.screen.buffer))
    check("それでも ready 判定用フラグは立たない(子プロセスの出力ではないため)",
          not sess._has_output)  # pylint: disable=protected-access


def test_stop_start_no_duplicate_tick_thread() -> None:
    """stop() が tick スレッドの終了を待たずに返ると、直後の start() の
    _tick_stop.clear() が古いスレッドのループ判定を書き換えてしまい、
    新旧2本の tick スレッドが同時に走りうる。

    自然な実行タイミングでは古いスレッドは _tick_stop.set() 直後の
    Event.wait() からほぼ即座に目覚めて終了するため、単純に stop() →
    start() を繰り返すだけではこの競合を安定して再現できない
    (実測: 30回連続で再現せず)。またこの環境では対象の対話 bash が
    SIGTERM では終了せず、SIGKILL 後もこのプロセスが reap するまで
    zombie として `_session_pids` に residual に見え続けるため、
    stop() の実行時間そのものは数秒かかる(いずれも本タスクの対象外の
    既存の挙動で、変更しない)。単純な所要時間の比較では tick スレッド
    待ちと無関係なこの遅さと区別できないため、_emit_diff で tick
    スレッドを明示的に足止めしたうえで、「kill 処理(_session_pids の
    最初の呼び出し)が、足止めした tick スレッドを解放する前に始まって
    しまわないか」を直接観測して検証する。
    """
    sess = ConsoleSession()
    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    old_tick = sess._tick  # pylint: disable=protected-access
    sess.write("printf 'L1\\nL2\\nL3\\n'\r")
    ok = wait_for(lambda: sess.max_row > 0, 3.0)
    check("(前提)最初のセッションで max_row が進んでいる", ok, f"max_row={sess.max_row}")

    tick_blocked = threading.Event()
    release_tick = threading.Event()
    original_emit_diff = sess._emit_diff  # pylint: disable=protected-access

    def slow_emit_diff() -> None:
        tick_blocked.set()
        release_tick.wait(10.0)
        original_emit_diff()

    sess._emit_diff = slow_emit_diff  # type: ignore[method-assign]  # pylint: disable=protected-access
    check("旧 tick スレッドが _emit_diff で足止めされた", tick_blocked.wait(2.0))
    check("(前提)最初のセッションで _has_output が立っている",
          sess._has_output)  # pylint: disable=protected-access

    kill_started = threading.Event()
    original_session_pids = sess._session_pids  # pylint: disable=protected-access

    def watched_session_pids(sid: int) -> list[int]:
        kill_started.set()
        return original_session_pids(sid)

    sess._session_pids = watched_session_pids  # type: ignore[method-assign]  # pylint: disable=protected-access

    stop_thread = threading.Thread(target=sess.stop, daemon=True)
    stop_thread.start()
    started_before_release = kill_started.wait(0.5)
    check("stop() は足止め中の tick スレッドを解放するまでプロセスの kill 処理を始めない",
          not started_before_release)
    release_tick.set()
    check("release 後、kill 処理が始まる", kill_started.wait(10.0))
    stop_thread.join(15.0)
    check("release 後 stop() が完了する", not stop_thread.is_alive())
    check("stop() が返った時点で古い tick スレッドは終了している",
          not old_tick.is_alive())

    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    check("start() で _has_output がリセットされる(前セッションの出力を引きずらない)",
          not sess._has_output)  # pylint: disable=protected-access
    check("start() で max_row がリセットされる", sess.max_row == 0,
          f"max_row={sess.max_row}")
    time.sleep(CONSOLE_TICK_SEC * 5)
    tick_threads = [t for t in threading.enumerate() if t.name == "console-tick"]
    check("console-tick スレッドは1本だけ", len(tick_threads) == 1,
          str(len(tick_threads)))
    sess.stop()


def test_stop_joins_reader_thread() -> None:
    """stop() が reader スレッドを join することを確認する。

    対話 bash 経由で検証しようとすると2つの交絡がある。
    (1) 対話 bash は SIGTERM では終了せず SIGKILL への escalation を要する
    (test_stop_start_no_duplicate_tick_thread のコメント参照) ため、
    proc kill 自体に数秒かかり、その所要時間を「join を待った時間」と
    見間違えやすい。
    (2) 子が生きている間 reader は「fd が閉じるまでブロックする os.read」
    ではなく「子の死亡で EOF を返す os.read」で自然に終了しうるため、
    stop() 後に reader が死んでいるかを見るだけでは、それが明示的な
    join の効果なのか子プロセスの死亡によるものなのか区別できない
    (実測: is_alive() ガードが False のまま join 自体が一切呼ばれず
    素通りするケースがあった)。

    そこで `yes` (SIGTERM を無視せず即死し、データを継続して出し続ける
    コマンド) を子にして reader を確実に稼働させたまま、reader の
    デコード処理をこちらの制御下で足止めする。これで stop() が
    reader.is_alive() を見た瞬間に必ず True になることを保証したうえで、
    reader.join() が実際に呼ばれたかどうかを直接観測する。
    """
    sess = ConsoleSession()
    started = sess.start(["yes", "TICK"], os.getcwd())
    check("(前提)yes が起動する", started)
    ok = wait_for(lambda: "TICK" in grid_text(sess))
    check("(前提)reader が実際に読み取っている", ok)
    reader_thread = sess._reader  # pylint: disable=protected-access

    decode_blocked = threading.Event()
    release_decode = threading.Event()
    original_decode = sess._decoder.decode  # pylint: disable=protected-access

    def slow_decode(*args: object, **kwargs: object) -> str:
        decode_blocked.set()
        release_decode.wait(10.0)
        return original_decode(*args, **kwargs)

    sess._decoder.decode = slow_decode  # type: ignore[method-assign]  # pylint: disable=protected-access
    check("reader がデコードで足止めされた(=確実に稼働中)", decode_blocked.wait(2.0))
    check("(前提)足止め中の reader はまだ生きている", reader_thread.is_alive())

    join_calls: list[float | None] = []
    original_join = reader_thread.join

    def watched_join(timeout: float | None = None) -> None:
        join_calls.append(timeout)
        original_join(timeout)

    reader_thread.join = watched_join  # type: ignore[method-assign]
    sess.stop(timeout=0.5)
    check("stop() は(足止め中で確実に alive な)reader.join を呼ぶ",
          len(join_calls) > 0, f"calls={join_calls}")
    release_decode.set()
    check("release 後 reader は終了する", wait_for(lambda: not reader_thread.is_alive(), 3.0))


def test_singleton() -> None:
    from shadow_clerk._daemon_console import get_console
    check("get_console はシングルトン", get_console() is get_console())


def test_cols_persist_across_daemon_restart() -> None:
    """列数はデーモンをまたいで覚えていること

    子は会議のたびに、デーモンも日に何度も起動し直る。ブラウザは幅が変わった
    ときしか送らないので、覚えていないと新しい子は毎回 DEFAULT_COLS で描き、
    その履歴が「横幅が固定」に見える。
    """
    saved = console_mod.CONSOLE_COLS_FILE
    with tempfile.TemporaryDirectory() as d:
        console_mod.CONSOLE_COLS_FILE = os.path.join(d, "console.cols")
        check("記録が無ければ既定値",
              console_mod._load_cols() == console_mod.DEFAULT_COLS)
        sess = ConsoleSession()
        sess.resize(213)
        check("resize で書き出す", console_mod._load_cols() == 213,
              str(console_mod._load_cols()))
        check("新しいセッションが引き継ぐ", ConsoleSession()._cols == 213)
        console_mod._save_cols(9999)
        check("壊れた値は範囲に丸める", console_mod._load_cols() == 500,
              str(console_mod._load_cols()))
        with open(console_mod.CONSOLE_COLS_FILE, "w", encoding="utf-8") as f:
            f.write("not a number")
        check("読めない記録は既定値に落ちる",
              console_mod._load_cols() == console_mod.DEFAULT_COLS)
    console_mod.CONSOLE_COLS_FILE = saved


def test_child_gets_controlling_terminal() -> None:
    """子が PTY を制御端末として持つこと

    setsid しただけでは PTY に前面プロセスグループが無く (tcgetpgrp が 0)、
    TIOCSWINSZ を投げてもカーネルは SIGWINCH を送る相手を持たない。
    幅を変えても TUI が描き直さないのはこれが原因だった。
    """
    sess = ConsoleSession()
    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    ok = wait_for(lambda: sess.max_row >= 0 and sess._proc is not None, 3.0)
    check("子が起動する", ok)
    try:
        fg = os.tcgetpgrp(sess._master_fd)
    except OSError as e:
        fg = -e.errno
    check("PTY に前面プロセスグループがある", fg > 0, str(fg))
    check("それが子のプロセスグループ", fg == os.getpgid(sess._proc.pid),
          f"{fg} vs {os.getpgid(sess._proc.pid)}")
    sess.stop()


def test_resize_matches_child_and_grid() -> None:
    """grid と子の winsize が同じ幅になること"""
    import struct as _struct
    import termios as _termios
    saved_file = console_mod.CONSOLE_COLS_FILE
    tmp = tempfile.TemporaryDirectory()
    console_mod.CONSOLE_COLS_FILE = os.path.join(tmp.name, "console.cols")
    sess = ConsoleSession()
    sess.start(["bash", "--norc", "--noprofile", "-i"], os.getcwd())
    sess.resize(90)
    packed = fcntl.ioctl(sess._master_fd, _termios.TIOCGWINSZ, b"\0" * 8)
    check("子の winsize が新しい幅", _struct.unpack("HHHH", packed)[1] == 90)
    check("grid も同じ幅", sess.screen.columns == 90, str(sess.screen.columns))
    sess.stop()
    console_mod.CONSOLE_COLS_FILE = saved_file
    tmp.cleanup()


def main() -> int:
    test_env_sanitized()
    test_screen_geometry()
    test_singleton()
    test_echo_reaches_grid()
    test_stop_kills_process_group()
    test_stop_escalates_to_sigkill()
    test_snapshot_and_broadcast()
    test_cursor_up_overwrite()
    test_send_after_ready()
    test_emit_diff_does_not_fake_readiness()
    test_stop_start_no_duplicate_tick_thread()
    test_beyond_virtual_rows()
    test_rows_below_cursor_reach_client()
    test_cols_survive_child_restart()
    test_cols_persist_across_daemon_restart()
    test_child_gets_controlling_terminal()
    test_resize_matches_child_and_grid()
    test_stop_joins_reader_thread()
    test_start_after_child_self_exit_no_leak()
    test_start_reentrant_lock_does_not_hold_lock_across_stop()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
