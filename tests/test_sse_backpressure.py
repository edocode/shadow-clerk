"""SSE クライアントキューの背圧（上限・切断）の検証

実行: uv run python tests/test_sse_backpressure.py
実デバイス・実 HTTP 不要。FileWatcher に偽 recorder を渡してキューの
挙動だけを直接検査する。
"""
from __future__ import annotations
import queue
import threading

from shadow_clerk._daemon_constants import SSE_QUEUE_MAXSIZE
from shadow_clerk._daemon_log_buffer import FileWatcher, LogBuffer, _SSE_CLOSE_EVENT

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class FakeRecorder:
    def __init__(self) -> None:
        self.stop_event = threading.Event()


rec = FakeRecorder()
fw = FileWatcher(rec, LogBuffer())

q_keep_up = fw.add_client()  # 都度ドレインする「追いついている」クライアント役
q_drop = fw.add_client()     # 一切ドレインしない「追いつけない」クライアント役

# add_client() が積む初回の recorder_status はテスト対象のカウントに含めない
q_keep_up.get_nowait()
q_drop.get_nowait()

received_keep_up: list[tuple[str, str]] = []
for i in range(SSE_QUEUE_MAXSIZE):
    fw._broadcast("log", f'{{"i":{i}}}')  # pylint: disable=protected-access
    while True:
        try:
            received_keep_up.append(q_keep_up.get_nowait())
        except queue.Empty:
            break

check("事前確認: q_drop がキュー上限まで積まれている(Full)", q_drop.full(),
      f"qsize={q_drop.qsize()}/{SSE_QUEUE_MAXSIZE}")
check("事前確認: 追いついているクライアントは溜めていない", q_keep_up.qsize() == 0,
      f"qsize={q_keep_up.qsize()}")
check("追いついているクライアントは全 N 件受信している",
      len(received_keep_up) == SSE_QUEUE_MAXSIZE, f"{len(received_keep_up)}")

with fw._clients_lock:  # pylint: disable=protected-access
    check("上限ちょうどではまだ切断されない",
          q_drop in fw._clients and q_keep_up in fw._clients)  # pylint: disable=protected-access

# 上限を超える1件を broadcast する → q_drop 側は put_nowait が queue.Full に
# なり、_broadcast がこのクライアントを切断する
fw._broadcast("log", '{"overflow": true}')  # pylint: disable=protected-access

with fw._clients_lock:  # pylint: disable=protected-access
    clients_after = list(fw._clients)  # pylint: disable=protected-access
check("上限を超えたクライアントは _clients から外れる", q_drop not in clients_after)
check("他のクライアントは _clients に残る", q_keep_up in clients_after)

# 外されたクライアントのキューを最後まで読み、末尾が終了の合図であることを確認
items: list[tuple[str, str]] = []
try:
    while True:
        items.append(q_drop.get_nowait())
except queue.Empty:
    pass
check("外されたクライアントのキューに終了の合図が入っている",
      bool(items) and items[-1][0] == _SSE_CLOSE_EVENT, f"last={items[-1] if items else None}")

# 他のクライアントは影響を受けず、引き続きイベントを受け取れる。
# 直前の overflow 用イベントも q_keep_up には正しく届いているはずなので、
# それを読み捨ててから次のイベントを確認する
try:
    overflow_got = q_keep_up.get_nowait()
except queue.Empty:
    overflow_got = None
check("他のクライアントは overflow の契機となったイベントも受け取っている",
      overflow_got == ("log", '{"overflow": true}'), f"{overflow_got}")

fw._broadcast("log", '{"after": 1}')  # pylint: disable=protected-access
try:
    got = q_keep_up.get_nowait()
except queue.Empty:
    got = None
check("他のクライアントは影響を受けずイベントを受け取り続ける",
      got == ("log", '{"after": 1}'), f"{got}")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
