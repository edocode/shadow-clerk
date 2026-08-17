"""SSE の詰まったクライアント検出・回収の end-to-end 検証

実行: uv run python tests/test_sse_stuck_client.py （所要 約2分）
実ソケット・実 HTTP サーバーを使う。実デバイス・実 daemon プロセスは不要
（FakeRecorder + 実物の FileWatcher/DashboardHandler をこのプロセス内で
ThreadingHTTPServer に載せ、127.0.0.1 の実ポートで待ち受ける）。

検証すること:
  1. 通常のクライアントは接続でき、サーバーのクライアント数に反映される
  2. 相手が読み出しを止めてソケットバッファが本当に埋まると、
     write() がブロックし続けず、ソケット書き込みタイムアウトで検出されて
     クライアントが確実に取り除かれる（サーバーのクライアント数が0に戻る）
  3. ブラウザ相当の「読み続けるクライアント」は、2分弱の接続中、15秒
     keepalive を挟んでも切断されずイベントを受信し続けられる

「読み出しを止める」だけでは TCP は送信側/受信側のカーネルバッファに
数百KB〜数MBを溜め込めてしまい、write() は簡単には本当にブロックしない
(sysctl net.ipv4.tcp_wmem/tcp_rmem 参照)。そこで、キュー件数上限
(_CLIENT_QUEUE_MAXSIZE=200) には遠く及ばない件数だが、1件が
カーネルバッファの合計容量を確実に超えるほど巨大な (数MB) ペイロードを
1回だけ broadcast する。これにより「アプリ側キューが満杯になって
切断される経路 (_broadcast の queue.Full 処理)」ではなく、
「実ソケットの write が本当にブロックしてタイムアウトする経路
(_SSE_WRITE_TIMEOUT_SEC)」だけを狙って発火させる。
"""
from __future__ import annotations
import json
import socket
import threading
import time
from http.server import ThreadingHTTPServer

from shadow_clerk._daemon_dashboard_base import _SSE_WRITE_TIMEOUT_SEC
from shadow_clerk._daemon_dashboard_handler import DashboardHandler
from shadow_clerk._daemon_log_buffer import FileWatcher, LogBuffer

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


rec = FakeRecorder()
log_buffer = LogBuffer()
file_watcher = FileWatcher(rec, log_buffer)

DashboardHandler.recorder = rec
DashboardHandler.log_buffer = log_buffer
DashboardHandler.file_watcher = file_watcher
DashboardHandler.gcal_monitor = None


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):  # noqa: ANN001
        pass  # テスト用にコネクションエラーのトレースバックは抑制する


ThreadingHTTPServer.allow_reuse_address = True
server = _QuietServer(("127.0.0.1", 0), DashboardHandler)
host, port = server.server_address
server_thread = threading.Thread(target=server.serve_forever, name="test-dashboard", daemon=True)
server_thread.start()


def client_count() -> int:
    return len(file_watcher._clients)  # pylint: disable=protected-access


def open_sse_socket() -> socket.socket:
    """/api/events へ生ソケットで接続し、レスポンスヘッダを読み飛ばして返す"""
    sock = socket.create_connection((host, port), timeout=5.0)
    req = f"GET /api/events HTTP/1.1\r\nHost: {host}:{port}\r\n\r\n"
    sock.sendall(req.encode())
    buf = b""
    sock.settimeout(5.0)
    while b"\r\n\r\n" not in buf:
        buf += sock.recv(4096)
    return sock


try:
    # --- 1. 通常のクライアントが接続できる ---
    before = client_count()
    sock1 = open_sse_socket()
    time.sleep(0.2)
    after_connect = client_count()
    check("1. 接続前はクライアント0", before == 0, f"{before}")
    check("2. 接続後はクライアント1", after_connect == 1, f"{after_connect}")

    # --- 2. 相手が読み出しを止めた後、巨大な1件を broadcast して
    #     実ソケットの write を本当にブロックさせ、タイムアウトで回収されるか ---
    # ここで sock1 からの読み出しをやめる（close はしない = 相手は消えたが
    # ソケットは繋がったまま、という障害状況を模擬する）
    huge_payload = json.dumps({"pad": "x" * (8 * 1024 * 1024)})  # 8MiB
    t0 = time.monotonic()
    file_watcher._broadcast("test", huge_payload)  # pylint: disable=protected-access

    deadline = t0 + _SSE_WRITE_TIMEOUT_SEC + 15.0
    while time.monotonic() < deadline and client_count() > 0:
        time.sleep(0.5)
    elapsed = time.monotonic() - t0
    final_count = client_count()
    check("3. 詰まったクライアントは有界な時間内にサーバーのクライアント数から消える",
          final_count == 0,
          f"{elapsed:.1f}秒後 client_count={final_count} "
          f"(write timeout={_SSE_WRITE_TIMEOUT_SEC}秒)")
    check("4. 回収までの時間はソケットタイムアウト相当のオーダーで有界",
          elapsed < _SSE_WRITE_TIMEOUT_SEC + 15.0, f"{elapsed:.1f}秒")
    sock1.close()

    # --- 5. 読み続ける通常クライアントは長時間切断されず、15秒 keepalive も
    #     問題なく越えられる ---
    sock2 = open_sse_socket()
    time.sleep(0.2)  # add_client() はヘッダ送信の後に実行されるため反映を待つ
    check("5. 2つ目の接続でもクライアント1", client_count() == 1, f"{client_count()}")

    received_events: list[tuple[str, str]] = []
    stop_reader = threading.Event()

    def _reader() -> None:
        sock2.settimeout(1.0)
        buf = b""
        while not stop_reader.is_set():
            try:
                chunk = sock2.recv(65536)
            except TimeoutError:
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                frame, buf = buf.split(b"\n\n", 1)
                if frame.startswith(b":"):
                    received_events.append(("keepalive", frame.decode(errors="replace")))
                elif frame:
                    received_events.append(("event", frame.decode(errors="replace")))

    reader_th = threading.Thread(target=_reader, name="sse-reader", daemon=True)
    reader_th.start()

    TEST_DURATION_SEC = 75.0  # 15秒 keepalive を跨ぐのに十分な長さ
    # 20〜40秒の区間はわざと無配信にする。5秒おきの配信だけを続けると
    # get(timeout=15) が毎回イベントで満たされ、本物の keepalive
    # (`: keepalive`) が一度も送られないまま検証が終わってしまうため
    QUIET_GAP_START, QUIET_GAP_END = 20.0, 40.0
    t_start = time.monotonic()
    sent = 0
    while (elapsed_loop := time.monotonic() - t_start) < TEST_DURATION_SEC:
        in_quiet_gap = QUIET_GAP_START <= elapsed_loop < QUIET_GAP_END
        if not in_quiet_gap and int(elapsed_loop) % 5 == 0:
            file_watcher._broadcast(  # pylint: disable=protected-access
                "level", json.dumps({"mic": {"rms": 1.0}}))
            sent += 1
        time.sleep(1.0)

    stop_reader.set()
    reader_th.join(timeout=5.0)

    keepalives = [e for e in received_events if e[0] == "keepalive"]
    events = [e for e in received_events if e[0] == "event"]
    check("6. 通常クライアントは約75秒間、切断されずに接続を維持できる",
          not reader_th.is_alive(), "reader が正常終了")
    check("7. その間 keepalive コメントを少なくとも1回受信する",
          len(keepalives) >= 1, f"keepalive件数={len(keepalives)}")
    check("8. その間、実イベントも受信できている",
          len(events) >= 1, f"event件数={len(events)} sent={sent}")
    check("9. 長時間接続してもクライアントは誤って切断されない",
          client_count() == 1, f"{client_count()}")

    sock2.close()
    # ソケットを閉じただけでは、サーバー側は次に write() を試みるまで
    # 切断に気づかない（get(timeout=15) で待っている間は無反応）。
    # さらに close 直後の最初の write は、相手からの RST がまだ届いておらず
    # 成功してしまうことがあるため、複数回 broadcast して切断検出（finally
    # での remove_client()）を待つ
    deadline10 = time.monotonic() + 5.0
    while time.monotonic() < deadline10 and client_count() > 0:
        file_watcher._broadcast("test", json.dumps({"noop": True}))  # pylint: disable=protected-access
        time.sleep(0.2)
    check("10. ソケットを閉じれば正常にクライアントが取り除かれる",
          client_count() == 0, f"{client_count()}")

finally:
    rec.stop_event.set()
    server.shutdown()
    server.server_close()

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
