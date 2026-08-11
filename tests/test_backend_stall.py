"""バックエンド経路（pw-record/parec）の停滞検知の検証

実行: uv run python tests/test_backend_stall.py
実デバイス不要。フレームを出さない/トリクルする/SIGTERM を無視する偽コマンドで
停滞・準停滞・強制終了を模擬する。
"""
from __future__ import annotations
import queue
import sys
import threading
import time

from shadow_clerk import _daemon_audio as audio
from shadow_clerk._daemon_constants import FRAME_SIZE, IPC_TIMEOUT_SEC

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def run_with_timeout(cmd: list[str], q: queue.Queue, stop: threading.Event,
                     stall_sec: float, join_timeout: float) -> tuple[bool, float]:
    """別スレッドで _capture_pcm_stream を実行し、(戻ったか, 経過秒) を返す。

    戻り値ではなく別スレッド経由にするのは、ハングした場合でもテスト自体は
    join_timeout で見切りをつけて先に進めるようにするため。
    """
    result: dict[str, float] = {}

    def _run() -> None:
        t0 = time.monotonic()
        audio._capture_pcm_stream(cmd, "test", q, stop, stall_sec=stall_sec)
        result["elapsed"] = time.monotonic() - t0

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout=join_timeout)
    return not th.is_alive(), result.get("elapsed", join_timeout)


# --- 1. フレームを一切出さないプロセスからは STALL 後に戻る ---
q1: queue.Queue = queue.Queue()
stop1 = threading.Event()
t0 = time.monotonic()
audio._capture_pcm_stream(
    [sys.executable, "-c", "import time; time.sleep(30)"], "test", q1, stop1,
    stall_sec=1.0)
elapsed = time.monotonic() - t0
check("1. 無音のまま停滞したら戻る", 1.0 <= elapsed < 5.0, f"{elapsed:.1f}秒で戻った")
check("2. フレームは流れていない", q1.empty(), f"{q1.qsize()}件")

# --- 3. フレームを出し続ける間は戻らない ---
q2: queue.Queue = queue.Queue()
stop2 = threading.Event()
producer = (
    "import sys,time\n"
    f"buf = b'\\x01\\x00' * {FRAME_SIZE}\n"
    "for _ in range(30):\n"
    "    sys.stdout.buffer.write(buf); sys.stdout.buffer.flush(); time.sleep(0.05)\n"
)
th2 = threading.Thread(
    target=audio._capture_pcm_stream,
    args=([sys.executable, "-c", producer], "test", q2, stop2),
    kwargs={"stall_sec": 1.0}, daemon=True)
th2.start()
time.sleep(1.5)
alive_while_flowing = th2.is_alive()
got = q2.qsize()
stop2.set()
th2.join(timeout=5)
check("3. フレームが流れている間は戻らない", alive_while_flowing)
check("4. フレームがキューに入る", got > 5, f"{got}件")
check("5. stop_event で終了する", not th2.is_alive())

# --- 6/7. トリクル（0.5秒ごとに1バイト）はフレームが完成しないまま
#     停滞判定にかかって戻る（select が1バイト到着ごとに締切を延ばす
#     実装だと、フレームが一向に完成しなくても永久に戻らない） ---
q3: queue.Queue = queue.Queue()
stop3 = threading.Event()
trickle = (
    "import sys,time\n"
    "for _ in range(60):\n"
    "    sys.stdout.buffer.write(b'\\x00'); sys.stdout.buffer.flush(); time.sleep(0.5)\n"
)
returned, elapsed3 = run_with_timeout(
    [sys.executable, "-c", trickle], q3, stop3, stall_sec=1.0, join_timeout=20.0)
check("6. トリクル（フレーム未完成）でも停滞判定で戻る", returned,
      f"returned={returned} elapsed={elapsed3:.2f}秒")
check("7. トリクル中はフレームが1件も完成しない", q3.qsize() == 0, f"{q3.qsize()}件")

# --- 8. SIGTERM を無視し stdout を閉じる子プロセスでも、terminate() が
#     効かないまま proc.wait() で無期限に待たされず、kill() で回収される ---
q4: queue.Queue = queue.Queue()
stop4 = threading.Event()
ignore_sigterm = (
    "import signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "sys.stdout.close()\n"
    "time.sleep(30)\n"
)
returned4, elapsed4 = run_with_timeout(
    [sys.executable, "-c", ignore_sigterm], q4, stop4, stall_sec=1.0,
    join_timeout=IPC_TIMEOUT_SEC + 10.0)
check("8. SIGTERM 無視でも kill() で回収されて戻る", returned4,
      f"returned={returned4} elapsed={elapsed4:.2f}秒 "
      f"(IPC_TIMEOUT_SEC={IPC_TIMEOUT_SEC})")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
