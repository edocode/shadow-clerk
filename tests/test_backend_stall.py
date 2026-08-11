"""バックエンド経路（pw-record/parec）の停滞検知の検証

実行: uv run python tests/test_backend_stall.py
実デバイス不要。フレームを出さない偽コマンドで停滞を模擬する。
"""
from __future__ import annotations
import queue
import sys
import threading
import time

from shadow_clerk import _daemon_audio as audio
from shadow_clerk._daemon_constants import FRAME_SIZE

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


# 停滞判定を短くして待ち時間を抑える
_orig_stall = audio.STREAM_STALL_SEC
audio.STREAM_STALL_SEC = 1.0
try:
    # --- 1. フレームを一切出さないプロセスからは STALL 後に戻る ---
    q: queue.Queue = queue.Queue()
    stop = threading.Event()
    t0 = time.monotonic()
    audio._capture_pcm_stream(
        [sys.executable, "-c", "import time; time.sleep(30)"], "test", q, stop)
    elapsed = time.monotonic() - t0
    check("1. 無音のまま停滞したら戻る", 1.0 <= elapsed < 5.0, f"{elapsed:.1f}秒で戻った")
    check("2. フレームは流れていない", q.empty(), f"{q.qsize()}件")

    # --- 3. フレームを出し続ける間は戻らない ---
    q2: queue.Queue = queue.Queue()
    stop2 = threading.Event()
    producer = (
        "import sys,time\n"
        f"buf = b'\\x01\\x00' * {FRAME_SIZE}\n"
        "for _ in range(30):\n"
        "    sys.stdout.buffer.write(buf); sys.stdout.buffer.flush(); time.sleep(0.05)\n"
    )
    th = threading.Thread(
        target=audio._capture_pcm_stream,
        args=([sys.executable, "-c", producer], "test", q2, stop2), daemon=True)
    th.start()
    time.sleep(1.5)
    alive_while_flowing = th.is_alive()
    got = q2.qsize()
    stop2.set()
    th.join(timeout=5)
    check("3. フレームが流れている間は戻らない", alive_while_flowing)
    check("4. フレームがキューに入る", got > 5, f"{got}件")
    check("5. stop_event で終了する", not th.is_alive())
finally:
    audio.STREAM_STALL_SEC = _orig_stall

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
