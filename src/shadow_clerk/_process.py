"""Shadow-clerk: プロセス存在確認・識別ユーティリティ

clerk-daemon（多重起動ガード）と clerk-util（stop/status）で共用する。
"""
from __future__ import annotations
import os
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
    Linux では /proc/<pid>/cmdline でコマンドラインを確認する。
    確認手段がないプラットフォームでは生存のみで判断する。
    """
    if not is_pid_alive(pid):
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().decode("utf-8", errors="replace").replace("\x00", " ")
    except OSError:
        return True
    return "clerk-daemon" in cmdline or "clerk_daemon" in cmdline
