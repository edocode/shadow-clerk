"""音声キャプチャ・ウォッチドッグの回帰テスト

実機の PortAudio ストリームを開いて次を検証する。

1. マイク/モニター両方のフレームが流れること
2. フレーム途絶を検知して自動再接続し、フレームが再開すること
   （サスペンド復帰でモニターが無言で死ぬ現象からの復帰）
3. デフォルト Sink 変更を検知して張り替えること

実行:
    uv run python tests/test_audio_capture_watchdog.py

所要 約90秒。実際に音声デバイスを開くため、マイクとモニターが利用できる
環境が必要。システムの音声設定は一切変更しない（デフォルト Sink 変更の
検知はスタブで模擬する）。

このプロジェクトにはテストフレームワークが無いため、単体で走るスクリプト
として書いてある。終了コード 0 が成功。
"""
from __future__ import annotations
import argparse
import logging
import os
import queue
import tempfile
import threading
import time

# 実データディレクトリを触らないよう、import 前に隔離する
os.environ.setdefault(
    "SHADOW_CLERK_DATA_DIR",
    os.path.join(tempfile.gettempdir(), "shadow-clerk-watchdog-test"))
os.makedirs(os.environ["SHADOW_CLERK_DATA_DIR"], exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

from shadow_clerk import _daemon_recorder_capture as cap  # noqa: E402
from shadow_clerk._daemon_audio import detect_backend  # noqa: E402

opened: list[cap._CaptureStream] = []
_orig_open = cap._CaptureStream.open


def _tracking_open(self: cap._CaptureStream) -> bool:
    ok = _orig_open(self)
    if ok:
        opened.append(self)
    return ok


cap._CaptureStream.open = _tracking_open


class _SupervisorErrorDetector(logging.Handler):
    """監視ループの「予期しないエラー」を検出する。

    Host は Recorder.__init__ を通さず属性を手で用意するため、本体に新しい
    属性が増えるとこのテストだけ AttributeError を起こす。監視ループはそれを
    握り潰して再試行するので、放置すると「テストは動いているが実際には毎周
    例外を出している」状態に静かに腐る。実際に 2 度それが起きたので検出する。
    """

    def __init__(self) -> None:
        super().__init__()
        self.errors: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.ERROR:
            self.errors.append(record.getMessage())


class Host(cap._RecorderCaptureMixin):
    """キャプチャ機能だけを持つ最小ホスト（Transcriber の読み込みを避ける）

    属性は `_RecorderCaptureMixin.__init__` が用意するもののうち、キャプチャ
    に必要な分だけを再現している。本体に属性が増えたらここにも足すこと
    （足し忘れは _SupervisorErrorDetector が検出する）。
    """

    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        self.args = argparse.Namespace(mic=None, monitor=None)
        self.stop_event = threading.Event()
        self.mic_queue: queue.Queue = queue.Queue()
        self.monitor_queue: queue.Queue = queue.Queue()
        self.backend_name, self.backend = detect_backend("auto")
        self.use_mic = self.use_monitor = False
        self._pinned_names: dict[str, str] = {}
        self._monitor_backend: threading.Thread | None = None
        self._manual_device_refresh = False
        self._device_snapshot: dict = {"mic": [], "monitor": [], "updated_at": None}
        self._return_backoff: dict = {}
        self._monitor_restart = threading.Event()
        self._monitor_backend_requested: str | None = None


def drain(host: Host) -> tuple[int, int]:
    n = (host.mic_queue.qsize(), host.monitor_queue.qsize())
    for q in (host.mic_queue, host.monitor_queue):
        while not q.empty():
            q.get_nowait()
    return n


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    return ok


def main() -> int:
    detector = _SupervisorErrorDetector()
    logging.getLogger("shadow-clerk").addHandler(detector)

    host = Host()
    thread = threading.Thread(target=host._audio_capture_thread, daemon=True)
    thread.start()
    results = []
    try:
        time.sleep(4)
        if detector.errors:
            # Host の属性不足が最も多い原因。この先のチェックは分かりにくい
            # 別のエラーで落ちるので、ここで理由を明示して止める
            print("[FAIL] 監視ループが起動直後から例外を出している。"
                  "Host に足りない属性がないか確認すること:")
            for msg in detector.errors[:3]:
                print(f"    {msg}")
            return 1
        mic, mon = drain(host)
        results.append(check("1. 初期キャプチャ", mic > 0 and mon > 0,
                             f"mic={mic} monitor={mon}"))
        results.append(check("1b. use_mic/use_monitor", host.use_mic and host.use_monitor,
                             f"use_mic={host.use_mic} use_monitor={host.use_monitor}"))

        print("\n--- モニターのストリームを停止 (サスペンドで死んだ状態を模擬) ---")
        # 実際にコールバックを止める。last_frame を書き換えるだけでは生きた
        # コールバックが即座に上書きしてしまい、途絶を再現できない。
        target = next(s for s in opened if s.label == "monitor")
        target._stream.stop()
        before = len(opened)

        # 検知(最大 STALL+CHECK) → クローズ → 再列挙 → 再オープンまで待つ
        deadline = time.monotonic() + cap.STREAM_STALL_SEC + cap.STREAM_CHECK_INTERVAL + 20
        while time.monotonic() < deadline and len(opened) <= before:
            time.sleep(0.5)
        results.append(check("2. 途絶を検知して再接続した", len(opened) > before,
                             f"ストリーム生成回数 {before} → {len(opened)}"))

        drain(host)
        time.sleep(3)
        mic, mon = drain(host)
        results.append(check("3. 再接続後にフレーム再開", mic > 0 and mon > 0,
                             f"mic={mic} monitor={mon}"))
        results.append(check("3b. use_monitor 復帰", host.use_monitor,
                             f"use_monitor={host.use_monitor}"))

        print("\n--- デフォルト Sink 変更検知 (get_default_sink_name をスタブ) ---")
        mon_stream = next(s for s in reversed(opened) if s.label == "monitor")
        results.append(check("4. sink を記録している", mon_stream.sink is not None,
                             f"sink={mon_stream.sink}"))
        cap.get_default_sink_name = lambda: "alsa_output.dummy_other_sink"
        deadline = time.monotonic() + 20
        before = len(opened)
        while time.monotonic() < deadline and len(opened) <= before:
            time.sleep(0.5)
        results.append(check("5. Sink 変更を検知して再接続", len(opened) > before,
                             f"ストリーム生成回数 {before} → {len(opened)}"))
    finally:
        host.stop_event.set()
        thread.join(timeout=10)
        print(f"\nスレッド終了: {not thread.is_alive()}")

    results.append(check("6. 監視ループが例外を出していない", not detector.errors,
                         f"{len(detector.errors)}件: {detector.errors[:2]}"))

    print(f"\n=== {sum(results)}/{len(results)} PASS ===")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
