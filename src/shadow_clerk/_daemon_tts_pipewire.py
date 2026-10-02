"""Shadow-clerk daemon: 名前付きの PipeWire ストリームで TTS を鳴らす（pw-cat を常駐させる）

sounddevice のストリームには名前を付けられず、会議アプリの入力に pw-link でつなぐ相手として見つけられない。
talk mode の間だけ pw-cat を1本起動し、合成した PCM を標準入力に書く。ヘッドセットへは自動接続でつながる。
"""
from __future__ import annotations

import fcntl
import json
import logging
import subprocess
import threading
import time
from typing import Any, Callable

import numpy as np

from shadow_clerk._daemon_talk_route import Runner, run_command
from shadow_clerk._daemon_tts import TtsError, resample
from shadow_clerk.i18n import t

logger = logging.getLogger("shadow-clerk")

NODE_NAME = "shadow-clerk-talk"
PWCAT_RATE = 48000
_BLOCK = PWCAT_RATE // 10      # 0.1 秒ずつ書き、合間に should_stop を見る
_PIPE_BYTES = _BLOCK * 2        # パイプのバッファを 0.1 秒ぶんに絞る。既定の 64KB だと止めても 0.7 秒鳴り続ける
_F_SETPIPE_SZ = 1031


class PwCatSink:
    def __init__(self, popen: Callable[..., Any] = subprocess.Popen, runner: Runner = run_command,
                 wait_sec: float = 2.0) -> None:
        self._popen = popen
        self._runner = runner
        self._wait_sec = wait_sec
        self._lock = threading.Lock()
        self._proc: Any = None

    def _spawn(self) -> None:
        self._proc = self._popen(
            ["pw-cat", "--playback", "--rate", str(PWCAT_RATE), "--channels", "1", "--format", "s16",
             "-P", f'{{ node.name = "{NODE_NAME}" }}', "-"],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            fcntl.fcntl(self._proc.stdin.fileno(), _F_SETPIPE_SZ, _PIPE_BYTES)
        except (OSError, ValueError) as e:
            logger.debug("talk: パイプのバッファを絞れません: %s", e)

    def _find_port(self) -> str | None:
        try:
            objs = json.loads(self._runner(["pw-dump"]))
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        nodes = {o["id"] for o in objs if o.get("type") == "PipeWire:Interface:Node"
                 and ((o.get("info") or {}).get("props") or {}).get("node.name") == NODE_NAME}
        for o in objs:
            p = (o.get("info") or {}).get("props") or {}
            if o.get("type") == "PipeWire:Interface:Port" and p.get("node.id") in nodes and p.get("port.direction") == "out":
                return f"{NODE_NAME}:{p.get('port.name')}"
        return None

    def start(self) -> str:
        with self._lock:
            self._spawn()
        deadline = time.monotonic() + self._wait_sec
        while time.monotonic() < deadline:
            port = self._find_port()
            if port:
                return port
            time.sleep(0.05)
        self.stop()
        raise TtsError(t("talk.pwcat_no_node"))

    def play(self, pcm: np.ndarray, sr: int, should_stop: Callable[[], bool]) -> None:
        data = (np.clip(resample(pcm, sr, PWCAT_RATE), -1.0, 1.0) * 32767).astype("<i2")
        for i in range(0, len(data), _BLOCK):
            if should_stop():
                return
            self._write(data[i:i + _BLOCK].tobytes())

    def _write(self, chunk: bytes) -> None:
        with self._lock:
            if self._proc is None:
                raise TtsError(t("talk.pwcat_no_node"))
            try:
                self._proc.stdin.write(chunk)
                self._proc.stdin.flush()
                return
            except (BrokenPipeError, OSError, ValueError) as e:
                logger.warning("talk: pw-cat が落ちたため起動し直します: %s", e)
            self._spawn()  # つなぎ直しは経路の監視が拾う（ノード ID が変わるため）
            try:
                self._proc.stdin.write(chunk)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as e:
                raise TtsError(str(e)) from e

    def stop(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
