"""SSE クライアントキューの上限と満杯時の挙動の検証（ユニットレベル）

実行: uv run python tests/test_sse_queue_bound.py
実ソケット不要。FileWatcher に偽 recorder を渡し、add_client()/_broadcast() を
直接呼んで検査する。

背景: 以前は add_client() が queue.Queue() を無制限で作り、_broadcast() は
`except Exception: pass` で put_nowait の失敗を握り潰していた。無制限キュー
では put_nowait が失敗しないため、読み出しが止まったクライアント (ブラウザの
タブ凍結・スリープ等) 向けのイベントが際限なく溜まり続け、daemon が数日で
2GB 常駐という形でメモリリークしていた。
"""
from __future__ import annotations
import logging
import queue
import threading
import time

from shadow_clerk._daemon_log_buffer import FileWatcher, LogBuffer, _CLIENT_QUEUE_MAXSIZE

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class FakeRecorder:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.levels: dict = {}
        self.output_path = "/dev/null"
        self._command_mode = False


# --- 1. add_client() が返すキューは無制限ではない ---
rec = FakeRecorder()
fw = FileWatcher(rec, LogBuffer())
q1 = fw.add_client()
check("1. キューに maxsize が設定されている", q1.maxsize == _CLIENT_QUEUE_MAXSIZE,
      f"maxsize={q1.maxsize}")

# 初期投入 (recorder_status) が1件入っているはずなので、それを取り出しておく
q1.get_nowait()

# --- 2. キューを上限まで満たしても _broadcast はブロックしない・例外を出さない ---
t0 = time.monotonic()
for i in range(_CLIENT_QUEUE_MAXSIZE):
    fw._broadcast("test", f"payload-{i}")
elapsed = time.monotonic() - t0
check("2. 上限ちょうどまでは全クライアントに配信され続ける（生存）",
      len(fw._clients) == 1, f"clients={len(fw._clients)}")
check("3. 上限までの配信は瞬時に終わる（producer がブロックしない）",
      elapsed < 1.0, f"{elapsed:.3f}秒")
check("4. キューは上限まで溜まっている", q1.qsize() == _CLIENT_QUEUE_MAXSIZE,
      f"qsize={q1.qsize()}")

# --- 5/6. 上限を超えて配信すると、例外を出さずクライアントが取り除かれる ---
t0 = time.monotonic()
fw._broadcast("test", "overflow")
elapsed = time.monotonic() - t0
check("5. 満杯後の配信もブロックしない（producer は即座に戻る）",
      elapsed < 1.0, f"{elapsed:.3f}秒")
check("6. 満杯になったクライアントは以後の配信対象から外される",
      len(fw._clients) == 0, f"clients={len(fw._clients)}")
check("7. キューの中身は溢れさせず上限のまま（古いイベントを保持）",
      q1.qsize() == _CLIENT_QUEUE_MAXSIZE, f"qsize={q1.qsize()}")

# --- 8. 満杯 (queue.Full) は「想定内」として warning ログを出さない ---
class _CountingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


logger = logging.getLogger("shadow-clerk")
handler = _CountingHandler()
logger.addHandler(handler)
try:
    rec2 = FakeRecorder()
    fw2 = FileWatcher(rec2, LogBuffer())
    q2 = fw2.add_client()
    q2.get_nowait()
    for i in range(_CLIENT_QUEUE_MAXSIZE + 1):
        fw2._broadcast("test", f"payload-{i}")
    warnings = [r for r in handler.records if r.levelno >= logging.WARNING]
    check("8. queue.Full による満杯は warning ログを出さない（想定内の切断）",
          len(warnings) == 0, f"warnings={[w.getMessage() for w in warnings]}")
finally:
    logger.removeHandler(handler)

# --- 9. put_nowait が想定外の例外を出した場合はログに残り、クライアントは外される ---
class _BoomQueue:
    """put_nowait が queue.Full 以外の例外を出す状況を模擬する"""
    def put_nowait(self, item: object) -> None:
        raise RuntimeError("boom")


rec3 = FakeRecorder()
fw3 = FileWatcher(rec3, LogBuffer())
boom_q = _BoomQueue()
fw3._clients.append(boom_q)  # type: ignore[arg-type]

handler2 = _CountingHandler()
logger.addHandler(handler2)
try:
    fw3._broadcast("test", "payload")
    warnings2 = [r for r in handler2.records if r.levelno >= logging.WARNING]
    check("9. 想定外の例外は warning ログに残る（黙って握り潰さない）",
          len(warnings2) == 1, f"warnings={[w.getMessage() for w in warnings2]}")
    check("10. 想定外の例外を出したクライアントも配信対象から外される",
          boom_q not in fw3._clients, f"clients残存={boom_q in fw3._clients}")
finally:
    logger.removeHandler(handler2)

# --- 11. 上限未満の通常運用ではクライアントは維持され、順序も保たれる ---
rec4 = FakeRecorder()
fw4 = FileWatcher(rec4, LogBuffer())
q4 = fw4.add_client()
q4.get_nowait()
for i in range(5):
    fw4._broadcast("test", f"n{i}")
received = [q4.get_nowait()[1] for _ in range(5)]
check("11. 通常運用ではイベントが到着順に保たれる",
      received == [f"n{i}" for i in range(5)], f"{received}")
check("12. 通常運用ではクライアントは切断されない", len(fw4._clients) == 1)

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
