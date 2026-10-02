"""PwCatSink の検証（偽のプロセスと偽の pw-dump）

実行: uv run python tests/test_tts_pipewire.py
"""
from __future__ import annotations
import json
import sys
import threading
import time

import numpy as np

from shadow_clerk._daemon_tts import TtsError
from shadow_clerk._daemon_tts_pipewire import NODE_NAME, PWCAT_RATE, PwCatSink

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Stdin:
    def __init__(self, broken: bool = False) -> None:
        self.data = bytearray()
        self.broken = broken
        self.closed = False

    def write(self, b: bytes) -> int:
        if self.broken:
            raise BrokenPipeError()
        self.data += b
        return len(b)

    def flush(self) -> None:
        pass

    def fileno(self) -> int:
        return -1

    def close(self) -> None:
        self.closed = True


class _Proc:
    def __init__(self, argv: list[str], broken: bool = False) -> None:
        self.argv = argv
        self.stdin = _Stdin(broken)
        self.terminated = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def poll(self) -> int | None:
        return 0 if self.terminated else None


_GRAPH = [
    {"id": 30, "type": "PipeWire:Interface:Node", "info": {"props": {"node.name": NODE_NAME}}},
    {"id": 31, "type": "PipeWire:Interface:Port",
     "info": {"props": {"port.name": "output_MONO", "port.direction": "out", "node.id": 30}}},
]


def _sink(graph: list[dict] | None = None, broken_first: bool = False):
    procs: list[_Proc] = []

    def popen(argv, **kw):
        procs.append(_Proc(argv, broken=broken_first and not procs))
        return procs[-1]

    sink = PwCatSink(popen=popen, runner=lambda a: json.dumps(_GRAPH if graph is None else graph), wait_sec=0.2)
    return sink, procs


def test_start() -> None:
    sink, procs = _sink()
    port = sink.start()
    argv = procs[0].argv
    check("名前付きのノードで起動する", argv[:2] == ["pw-cat", "--playback"] and any(NODE_NAME in a for a in argv)
          and str(PWCAT_RATE) in argv, repr(argv))
    check("出力ポート名を返す", port == f"{NODE_NAME}:output_MONO", port)
    sink.stop()
    check("stop で閉じて止める", procs[0].stdin.closed and procs[0].terminated)
    sink.stop()
    check("stop は二度呼べる", True)
    sink, procs = _sink(graph=[])
    try:
        sink.start()
        check("ノードが現れなければ TtsError", False)
    except TtsError:
        check("ノードが現れなければ TtsError", procs[0].terminated)


def test_play() -> None:
    sink, procs = _sink()
    sink.start()
    pcm = np.full(24000, 0.5, dtype=np.float32)  # 24kHz で1秒
    sink.play(pcm, 24000, lambda: False)
    written = np.frombuffer(bytes(procs[0].stdin.data), dtype="<i2")
    check("48kHz の s16 に変換して書く", len(written) == PWCAT_RATE and abs(int(written[100]) - 16383) <= 1,
          f"{len(written)} {written[100] if len(written) else None}")
    calls = {"n": 0}

    def stop_after_two() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    procs[0].stdin.data.clear()
    sink.play(pcm, 24000, stop_after_two)
    check("should_stop で途中でやめる", 0 < len(procs[0].stdin.data) < PWCAT_RATE * 2, str(len(procs[0].stdin.data)))
    sink.stop()


def test_restart_once_on_broken_pipe() -> None:
    sink, procs = _sink(broken_first=True)
    sink.start()
    sink.play(np.zeros(4800, dtype=np.float32), 48000, lambda: False)
    check("落ちていたら1回だけ起動し直して書く", len(procs) == 2 and len(procs[1].stdin.data) == 9600, repr(len(procs)))
    sink.stop()


class _BlockStdin(_Stdin):
    def __init__(self) -> None:
        super().__init__()
        self.release = threading.Event()

    def write(self, b: bytes) -> int:
        self.release.wait(5)
        raise ValueError("closed")

    def close(self) -> None:
        super().close()
        self.release.set()


def test_stop_during_blocked_write() -> None:
    sink, procs = _sink()
    sink.start()
    procs[0].stdin = _BlockStdin()
    errs: list[BaseException] = []

    def run() -> None:
        try:
            sink.play(np.zeros(4800, dtype=np.float32), 48000, lambda: False)
        except BaseException as e:  # noqa: BLE001
            errs.append(e)

    th = threading.Thread(target=run)
    th.start()
    time.sleep(0.2)
    t0 = time.monotonic()
    sink.stop()
    th.join(2)
    check("書き込み中でも stop はすぐ戻る", time.monotonic() - t0 < 1.0 and not th.is_alive())
    check("止められた play は例外なく戻り、起動し直さない", not errs and len(procs) == 1, repr(errs))


def test_play_after_stop() -> None:
    sink, procs = _sink()
    sink.start()
    sink.stop()
    try:
        sink.play(np.zeros(4800, dtype=np.float32), 48000, lambda: False)
        check("stop 後の play は黙って戻る", len(procs) == 1)
    except TtsError:
        check("stop 後の play は黙って戻る", False)


def test_popen_failure() -> None:
    def popen(argv, **kw):
        raise FileNotFoundError("pw-cat")

    sink = PwCatSink(popen=popen, runner=lambda a: "[]", wait_sec=0.1)
    try:
        sink.start()
        check("popen 失敗は TtsError", False)
    except TtsError as e:
        check("popen 失敗は TtsError", isinstance(e.__cause__, FileNotFoundError))


def test_respawn_reaps_old() -> None:
    sink, procs = _sink(broken_first=True)
    sink.start()
    sink.play(np.zeros(4800, dtype=np.float32), 48000, lambda: False)
    check("起動し直すとき古いプロセスを止める", procs[0].terminated and procs[0].stdin.closed)
    sink.stop()


def test_no_module_level_fcntl() -> None:
    import shadow_clerk._daemon_tts_pipewire as m
    check("fcntl を import 時に読み込まない", "fcntl" not in vars(m))


if __name__ == "__main__":
    test_start()
    test_play()
    test_restart_once_on_broken_pipe()
    test_stop_during_blocked_write()
    test_play_after_stop()
    test_popen_failure()
    test_respawn_reaps_old()
    test_no_module_level_fcntl()
    sys.exit(0 if all(results) else 1)
