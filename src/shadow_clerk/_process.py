"""Shadow-clerk: プロセス存在確認・識別ユーティリティ

clerk-daemon（多重起動ガード）と clerk-util（stop/status）で共用する。
"""
from __future__ import annotations
import os
import subprocess
import sys


def is_pid_alive(pid: int) -> bool:
    """プロセスが存在するか。

    Windows では os.kill(pid, 0) が TerminateProcess でプロセスを強制終了して
    しまうため、OpenProcess で確認する。
    """
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_clerk_daemon_process(pid: int) -> bool:
    """PID が生存中の clerk-daemon プロセスを指しているか。

    PID の再利用（デーモンがクラッシュして stale な daemon.pid が残り、
    同じ PID を無関係のプロセスが使う）による誤判定・誤 kill を防ぐため、
    コマンドラインを確認する（Linux は /proc/<pid>/cmdline、macOS は ps）。
    確認手段がないプラットフォームでは生存のみで判断する。
    """
    if not is_pid_alive(pid):
        return False
    if (cmdline := _cmdline(pid)) is None:
        return True
    return "clerk-daemon" in cmdline or "clerk_daemon" in cmdline


def _ps(args: list[str]) -> str | None:
    """`ps` の出力。/proc の無い POSIX (macOS) 用。失敗したら None"""
    try:
        result = subprocess.run(["ps", *args], capture_output=True, text=True, encoding="utf-8", timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def _cmdline(pid: int) -> str | None:
    """プロセスのコマンドライン。取れなければ None"""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().decode("utf-8", errors="replace").replace("\x00", " ")
    except OSError:
        pass
    if sys.platform == "win32":
        return None
    return (_ps(["-o", "command=", "-p", str(pid)]) or "").strip() or None


def all_pids() -> list[int]:
    """生存している全プロセスの pid（POSIX）"""
    if os.path.isdir("/proc"):
        return [int(name) for name in os.listdir("/proc") if name.isdigit()]
    return [int(tok) for tok in (_ps(["-A", "-o", "pid="]) or "").split()]
