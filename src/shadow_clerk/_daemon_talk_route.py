"""Shadow-clerk daemon: Claude の声を会議アプリの入力に届ける経路

PipeWire では物理マイクに書き込めないが、ひとつの入力ポートに複数のリンクがつながると足し合わされる。
TTS の再生ストリームを会議アプリの録音ストリームにもつなげば、マイクの音と一緒に相手へ届く。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from typing import Callable, Protocol

from shadow_clerk.domain import RouteTarget

logger = logging.getLogger("shadow-clerk")

Runner = Callable[[list[str]], str]
_TOOLS = ("pw-dump", "pw-link", "pw-cat")


def run_command(argv: list[str]) -> str:
    return subprocess.run(argv, check=True, capture_output=True, text=True, timeout=5).stdout


class TalkRoute(Protocol):
    def available(self) -> bool: ...
    def targets(self) -> list[RouteTarget]: ...
    def connect(self, app: str, source_port: str) -> None: ...
    def disconnect(self) -> None: ...
    def status(self) -> dict: ...


class NullRoute:
    """届ける先なし、または PipeWire が使えない環境"""

    def available(self) -> bool:
        return False

    def targets(self) -> list[RouteTarget]:
        return []

    def connect(self, app: str, source_port: str) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def status(self) -> dict:
        return {"app": "", "connected": False}


def _props(obj: dict) -> dict:
    return (obj.get("info") or {}).get("props") or {}


class PipeWireRoute:
    def __init__(self, runner: Runner = run_command, pid: int | None = None, poll_sec: float = 1.0,
                 which: Callable[[str], str | None] = shutil.which) -> None:
        self._runner = runner
        self._pid = os.getpid() if pid is None else pid
        self._poll_sec = poll_sec
        self._which = which
        self._lock = threading.Lock()
        self._app = ""
        self._source = ""
        self._linked: set[tuple[int, int]] = set()
        self._connected = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def available(self) -> bool:
        return all(self._which(c) for c in _TOOLS)

    def _dump(self) -> list[dict]:
        return json.loads(self._runner(["pw-dump"]))

    def _is_own(self, node: dict, clients: dict[int, dict]) -> bool:
        """daemon 自身のストリームか。ALSA 経由のストリームは PID がノードではなく client に付く"""
        props = _props(node)
        pid = props.get("application.process.id")
        if pid is None:
            pid = _props(clients.get(props.get("client.id"), {})).get("application.process.id")
        return pid is not None and str(pid) == str(self._pid)

    def _streams(self, objs: list[dict]) -> list[tuple[RouteTarget, list[int]]]:
        clients = {o["id"]: o for o in objs if o.get("type") == "PipeWire:Interface:Client"}
        ports = [o for o in objs if o.get("type") == "PipeWire:Interface:Port"]
        found = []
        for o in objs:
            props = _props(o)
            if (o.get("type") != "PipeWire:Interface:Node" or props.get("media.class") != "Stream/Input/Audio"
                    or self._is_own(o, clients)):
                continue
            app = str(props.get("application.name") or props.get("node.name") or "")
            if not app:
                continue
            label = f"{app} — {props['media.name']}" if props.get("media.name") else app
            inputs = [p["id"] for p in ports
                      if _props(p).get("node.id") == o["id"] and _props(p).get("port.direction") == "in"]
            found.append((RouteTarget(app, o["id"], label), inputs))
        return found

    def _source_port_id(self, objs: list[dict]) -> int | None:
        node_name, _, port_name = self._source.partition(":")
        nodes = {o["id"] for o in objs if o.get("type") == "PipeWire:Interface:Node"
                 and _props(o).get("node.name") == node_name}
        for o in objs:
            p = _props(o)
            if (o.get("type") == "PipeWire:Interface:Port" and p.get("node.id") in nodes
                    and p.get("port.direction") == "out" and p.get("port.name") == port_name):
                return o["id"]
        return None

    def targets(self) -> list[RouteTarget]:
        try:
            return [t for t, _ in self._streams(self._dump())]
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            logger.warning("talk: PipeWire のグラフを読めません: %s", e)
            return []

    def connect(self, app: str, source_port: str) -> None:
        self.disconnect()
        with self._lock:
            self._app, self._source = app, source_port
            self._stop.clear()
        self._sync()
        self._thread = threading.Thread(target=self._watch, name="talk-route", daemon=True)
        self._thread.start()

    def _watch(self) -> None:
        while not self._stop.wait(self._poll_sec):
            self._sync()

    def _sync(self) -> None:
        """選んだアプリの録音ストリームのうち、まだつないでいない入力ポートにつなぐ"""
        with self._lock:
            if not self._app:
                return
            try:
                objs = self._dump()
            except (OSError, subprocess.SubprocessError, ValueError) as e:
                logger.warning("talk: PipeWire のグラフを読めません: %s", e)
                self._connected = False
                return
            src = self._source_port_id(objs)
            links = {((o.get("info") or {}).get("output-port-id"), (o.get("info") or {}).get("input-port-id"))
                     for o in objs if o.get("type") == "PipeWire:Interface:Link"}
            inputs = [i for t, ports in self._streams(objs) if t.app == self._app for i in ports]
            connected = False
            for inp in inputs if src is not None else []:
                if (src, inp) in links:
                    connected = True
                    continue
                try:
                    self._runner(["pw-link", str(src), str(inp)])
                except (OSError, subprocess.SubprocessError) as e:
                    logger.warning("talk: %s につなげません: %s", self._app, e)
                    continue
                self._linked.add((src, inp))
                connected = True
            self._connected = connected

    def disconnect(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._lock:
            for out, inp in self._linked:
                try:
                    self._runner(["pw-link", "-d", str(out), str(inp)])
                except (OSError, subprocess.SubprocessError) as e:
                    logger.debug("talk: リンクを外せません (%s -> %s): %s", out, inp, e)
            self._linked.clear()
            self._app, self._source, self._connected = "", "", False

    def status(self) -> dict:
        return {"app": self._app, "connected": self._connected}


def make_route() -> TalkRoute:
    if sys.platform.startswith("linux"):
        route = PipeWireRoute()
        if route.available():
            return route
    return NullRoute()
