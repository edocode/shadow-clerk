"""Shadow-clerk daemon: AI Console の疑似端末 (PTY) トランスポート

`ConsoleSession` から **OS 依存の部分だけ**を切り出したもの。上位は
「bytes を読む・書く・大きさを変える・止める」しか知らない。

POSIX は `pty.openpty()` + `subprocess.Popen`、Windows は ConPTY (`pywinpty`)。
`pty` / `termios` / `fcntl` は Windows に存在しないので、**import は各実装の
中に閉じ込める**。モジュールの先頭で読むと Windows では import した時点で
落ちる。
"""
from __future__ import annotations
import logging
import os
import subprocess
import sys
import time
from abc import ABC, abstractmethod

logger = logging.getLogger("shadow-clerk")

IS_WINDOWS = sys.platform == "win32"


class ConsolePty(ABC):
    """子プロセスを 1 つ抱えた疑似端末"""

    @abstractmethod
    def read(self, size: int) -> bytes:
        """出力を読む。子が終わって端末が閉じたら空を返す(ブロックする)"""

    @abstractmethod
    def write(self, data: bytes) -> None:
        """キー入力を書き込む"""

    @abstractmethod
    def set_winsize(self, rows: int, cols: int) -> None:
        """端末の大きさを子に伝える"""

    @abstractmethod
    def is_running(self) -> bool:
        """子がまだ生きているか"""

    @abstractmethod
    def terminate(self, timeout: float) -> None:
        """子を終わらせて端末を閉じる。冪等"""

    @property
    @abstractmethod
    def pid(self) -> int | None:
        """子の pid。終了後は None を返しうる"""


class PosixConsolePty(ConsolePty):
    """pty.openpty() + Popen。制御端末を子に持たせる"""

    def __init__(self, master_fd: int, proc: subprocess.Popen) -> None:
        self.fd: int | None = master_fd
        self.proc: subprocess.Popen | None = proc

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc is not None else None

    def read(self, size: int) -> bytes:
        fd = self.fd
        if fd is None:
            return b""
        try:
            return os.read(fd, size)
        except OSError:
            return b""  # 子が終了して master が閉じた

    def write(self, data: bytes) -> None:
        fd = self.fd
        if fd is None:
            return
        os.write(fd, data)

    def set_winsize(self, rows: int, cols: int) -> None:
        import fcntl
        import struct
        import termios
        fd = self.fd
        if fd is None:
            return
        packed = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, packed)
        except OSError as e:
            logger.warning("winsize の設定に失敗: %s", e)

    def is_running(self) -> bool:
        proc = self.proc
        return proc is not None and proc.poll() is None

    def terminate(self, timeout: float) -> None:
        """SIGTERM → timeout 秒 → SIGKILL。そのあと master を閉じる

        start_new_session=True で子(bash 等)をセッションリーダーにしているが、
        対話シェルはジョブ制御で `cmd &` を自分とは別の pgrp に飛ばす。
        pgrp 単位の killpg ではその孫が生き残るので、同じセッション ID を
        持つ全 pid を対象にする。
        """
        import signal
        proc, fd = self.proc, self.fd
        self.proc, self.fd = None, None
        if proc is not None and proc.poll() is None:
            try:
                sid: int | None = os.getsid(proc.pid)
            except ProcessLookupError:
                sid = None
            if sid is not None and sid == os.getsid(0):
                # start_new_session が効かなかった、あるいは proc が既に死んで
                # pid が再利用され、sid が偶然デーモン自身のセッションと一致
                # した場合。ここで session_pids(sid) を回すとデーモン本体や
                # ユーザーのログインシェルまで kill 対象に入ってしまうので、
                # このときだけ影響範囲を proc 自身の pgrp に限定した従来の
                # killpg にフォールバックする。
                logger.warning(
                    "AI Console のセッション ID (%s) が自プロセスと一致するため、"
                    "pgrp 単位の kill にフォールバックします (pid=%s)", sid, proc.pid)
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    try:
                        os.killpg(os.getpgid(proc.pid), sig)
                    except (ProcessLookupError, PermissionError):
                        break
                    try:
                        proc.wait(timeout=timeout)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            elif sid is not None:
                for sig in (signal.SIGTERM, signal.SIGKILL):
                    targets = self.session_pids(sid)
                    if not targets:
                        break
                    for pid in targets:
                        try:
                            os.kill(pid, sig)
                        except (ProcessLookupError, PermissionError):
                            pass
                    if self._wait_session_gone(sid, timeout):
                        break
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def _wait_session_gone(self, sid: int, timeout: float) -> bool:
        """sid に属する pid が全て消えるまで timeout 秒までポーリングする"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.session_pids(sid):
                return True
            time.sleep(0.05)
        return not self.session_pids(sid)

    def session_pids(self, sid: int) -> list[int]:
        """セッション ID が sid と一致する全 pid を /proc から集める"""
        pids = []
        for name in os.listdir("/proc"):
            if not name.isdigit():
                continue
            pid = int(name)
            try:
                if os.getsid(pid) == sid:
                    pids.append(pid)
            except (ProcessLookupError, PermissionError):
                continue
        return pids


class WindowsConsolePty(ConsolePty):
    """ConPTY (pywinpty)。fd ではなく PtyProcess を 1 つ持つ

    ConPTY には POSIX の「制御端末」「プロセスグループ」に当たるものが無い。
    大きさの変更は擬似コンソールへの API 呼び出しとして子に届き、終了は
    擬似コンソールごと閉じることで子に伝わる。
    """

    def __init__(self, proc: object) -> None:
        self.proc = proc

    @property
    def pid(self) -> int | None:
        return getattr(self.proc, "pid", None) if self.proc is not None else None

    def read(self, size: int) -> bytes:
        proc = self.proc
        if proc is None:
            return b""
        try:
            # pywinpty は内部で UTF-8 を継続デコードして str を返す。
            # 上位のパイプラインは bytes を前提にしているので戻す
            return proc.read(size).encode("utf-8")  # type: ignore[attr-defined]
        except (EOFError, OSError):
            return b""

    def write(self, data: bytes) -> None:
        proc = self.proc
        if proc is None:
            return
        proc.write(data.decode("utf-8", "replace"))  # type: ignore[attr-defined]

    def set_winsize(self, rows: int, cols: int) -> None:
        proc = self.proc
        if proc is None:
            return
        try:
            proc.setwinsize(rows, cols)  # type: ignore[attr-defined]
        except OSError as e:
            logger.warning("winsize の設定に失敗: %s", e)

    def is_running(self) -> bool:
        proc = self.proc
        if proc is None:
            return False
        try:
            return bool(proc.isalive())  # type: ignore[attr-defined]
        except OSError:
            return False

    def terminate(self, timeout: float) -> None:
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        try:
            proc.terminate(force=True)  # type: ignore[attr-defined]
        except (OSError, EOFError) as e:
            logger.warning("AI Console の終了に失敗: %s", e)
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if not proc.isalive():  # type: ignore[attr-defined]
                    return
            except OSError:
                return
            time.sleep(0.05)


def _set_controlling_tty() -> None:
    """子の側で PTY を制御端末にする。fork 後 exec 前に呼ばれる

    **これが無いと SIGWINCH が誰にも届かない。** setsid しただけでは PTY に
    前面プロセスグループが無く (tcgetpgrp が 0)、TIOCSWINSZ を投げても
    カーネルは信号を送る相手を持たない。実測: 制御端末なしで幅を変えても
    子からの出力は 0 バイト、設定すると 17432 バイトの再描画が返る。
    Ctrl-C などのジョブ制御も同じ理由で効かない。

    子プロセスの中で走るので、余計なことはせず ioctl だけにする。
    """
    import fcntl
    import termios
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


def _open_posix(argv: list[str], cwd: str, env: dict[str, str],
                rows: int, cols: int) -> ConsolePty | None:
    import pty
    try:
        master_fd, slave_fd = pty.openpty()
    except OSError as e:
        logger.error("PTY を開けません: %s", e)
        return None
    session = PosixConsolePty(master_fd, None)  # type: ignore[arg-type]
    # 大きさは exec の前に入れる。あとから入れると、子は既定の 80x24 で
    # 1 画面描いてしまい、その分が履歴に残る
    session.set_winsize(rows, cols)
    try:
        proc = subprocess.Popen(
            argv, cwd=cwd, env=env,
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            start_new_session=True, close_fds=True,
            preexec_fn=_set_controlling_tty)
    except (OSError, ValueError) as e:
        os.close(master_fd)
        os.close(slave_fd)
        logger.error("AI アシスタントの起動に失敗: %s (%s)", e, argv)
        return None
    os.close(slave_fd)  # 親側は master だけ持つ。閉じないと EOF を検知できない
    session.proc = proc
    return session


def _open_windows(argv: list[str], cwd: str, env: dict[str, str],
                  rows: int, cols: int) -> ConsolePty | None:
    try:
        from winpty import PtyProcess  # type: ignore[import-not-found]
    except ImportError:
        logger.error("AI Console には pywinpty が要ります "
                     "(uv pip install pywinpty)")
        return None
    try:
        proc = PtyProcess.spawn(argv, cwd=cwd, env=env, dimensions=(rows, cols))
    except OSError as e:
        logger.error("AI アシスタントの起動に失敗: %s (%s)", e, argv)
        return None
    return WindowsConsolePty(proc)


def open_console_pty(argv: list[str], cwd: str, env: dict[str, str],
                     cols: int, rows: int) -> ConsolePty | None:
    """疑似端末を開いて argv を起こす。失敗したら None(理由はログに出す)"""
    if IS_WINDOWS:
        return _open_windows(argv, cwd, env, rows, cols)
    return _open_posix(argv, cwd, env, rows, cols)
