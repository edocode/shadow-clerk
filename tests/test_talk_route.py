"""PipeWireRoute の検証（偽の pw-dump と偽のコマンド実行）

実行: uv run python tests/test_talk_route.py
"""
from __future__ import annotations
import json
import sys
import time

from shadow_clerk._daemon_talk_route import NullRoute, PipeWireRoute
from shadow_clerk.domain import RouteTarget

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


OWN_PID = 4242


def _node(nid: int, **props: object) -> dict:
    return {"id": nid, "type": "PipeWire:Interface:Node", "info": {"props": props}}


def _port(pid: int, node: int, name: str, direction: str) -> dict:
    return {"id": pid, "type": "PipeWire:Interface:Port",
            "info": {"direction": "input" if direction == "in" else "output",
                     "props": {"port.name": name, "port.direction": direction, "node.id": node}}}


def _client(cid: int, pid: int) -> dict:
    return {"id": cid, "type": "PipeWire:Interface:Client", "info": {"props": {"application.process.id": pid}}}


def _link(lid: int, out: int, inp: int) -> dict:
    return {"id": lid, "type": "PipeWire:Interface:Link", "info": {"output-port-id": out, "input-port-id": inp}}


def _graph(meeting_node: int = 10, links: list[dict] | None = None) -> list[dict]:
    return [
        _client(1, OWN_PID), _client(2, 999),
        # daemon 自身: PID がノードに付くもの（pulse 経由）と、client にしか付かないもの（ALSA 経由）
        _node(5, **{"media.class": "Stream/Input/Audio", "application.name": "python3", "node.name": "python3",
                    "application.process.id": OWN_PID, "client.id": 1}),
        _node(6, **{"media.class": "Stream/Input/Audio", "application.name": "PipeWire ALSA [python3.13]",
                    "node.name": "alsa_capture.python3.13", "client.id": 1}),
        _node(meeting_node, **{"media.class": "Stream/Input/Audio", "application.name": "Chromium",
                               "media.name": "WebRTC", "node.name": "Chromium input", "client.id": 2}),
        _node(20, **{"media.class": "Stream/Output/Audio", "application.name": "Chromium", "node.name": "out"}),
        _node(30, **{"media.class": "Stream/Output/Audio", "application.name": "pw-cat", "node.name": "shadow-clerk-talk"}),
        _port(31, 30, "output_MONO", "out"),
        _port(meeting_node * 100 + 1, meeting_node, "input_FL", "in"),
        _port(meeting_node * 100 + 2, meeting_node, "input_FR", "in"),
        _port(61, 6, "input_FL", "in"),
    ] + (links or [])


class _Runner:
    def __init__(self, graph: list[dict]) -> None:
        self.graph = graph
        self.calls: list[list[str]] = []
        self.fail_dump = False

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        if argv[0] == "pw-dump":
            if self.fail_dump:
                raise OSError("pw-dump missing")
            return json.dumps(self.graph)
        if argv[:2] == ["pw-link", "-d"]:
            return ""
        if argv[0] == "pw-link":
            self.graph.append(_link(900 + len(self.calls), int(argv[1]), int(argv[2])))
            return ""
        raise AssertionError(argv)

    def links(self) -> list[list[str]]:
        return [c for c in self.calls if c[0] == "pw-link" and c[1] != "-d"]


def _route(runner: _Runner) -> PipeWireRoute:
    return PipeWireRoute(runner=runner, pid=OWN_PID, poll_sec=0.05, which=lambda c: "/usr/bin/" + c)


def test_targets_exclude_self() -> None:
    r = _route(_Runner(_graph()))
    got = r.targets()
    check("録音ストリームだけを候補にし、daemon 自身は除く",
          got == [RouteTarget("Chromium", 10, "Chromium — WebRTC")], repr(got))
    check("pw-dump が失敗したら空", PipeWireRoute(runner=lambda a: (_ for _ in ()).throw(OSError("x")),
                                                 pid=OWN_PID).targets() == [])


def test_connect_links_every_input_port() -> None:
    runner = _Runner(_graph())
    r = _route(runner)
    r.connect("Chromium", "shadow-clerk-talk:output_MONO")
    try:
        check("会議アプリの全入力ポートにつなぐ", runner.links() == [["pw-link", "31", "1001"], ["pw-link", "31", "1002"]],
              repr(runner.links()))
        check("daemon 自身の録音にはつながない", all(c[2] != "61" for c in runner.links()))
        check("status は接続中", r.status() == {"app": "Chromium", "connected": True}, repr(r.status()))
        time.sleep(0.15)
        check("つないだあとは張り直さない", len(runner.links()) == 2, repr(runner.links()))
    finally:
        r.disconnect()
    unlinks = [c for c in runner.calls if c[:2] == ["pw-link", "-d"]]
    check("disconnect で張ったリンクを外す", sorted(map(tuple, unlinks)) == [("pw-link", "-d", "31", "1001"), ("pw-link", "-d", "31", "1002")],
          repr(unlinks))
    check("disconnect 後は未接続", r.status() == {"app": "", "connected": False})
    r.disconnect()
    check("disconnect は二度呼べる", True)


def test_reconnect_when_stream_reopens() -> None:
    runner = _Runner(_graph())
    r = _route(runner)
    r.connect("Chromium", "shadow-clerk-talk:output_MONO")
    try:
        runner.graph[:] = _graph(meeting_node=11)  # マイクを開き直してノード ID が変わった（古いリンクも消えた）
        time.sleep(0.2)
        check("新しいストリームにつなぎ直す", ["pw-link", "31", "1101"] in runner.links(), repr(runner.links()))
        check("つなぎ直したら接続中", r.status()["connected"])
        runner.graph[:] = [o for o in _graph(meeting_node=11) if o.get("id") not in (11, 1101, 1102)]
        time.sleep(0.2)
        check("会議アプリが録音をやめたら未接続", not r.status()["connected"], repr(r.status()))
    finally:
        r.disconnect()


def test_dump_failure_marks_disconnected() -> None:
    runner = _Runner(_graph())
    r = _route(runner)
    r.connect("Chromium", "shadow-clerk-talk:output_MONO")
    try:
        runner.fail_dump = True
        time.sleep(0.2)
        check("pw-dump が失敗したら未接続（落ちない）", not r.status()["connected"])
    finally:
        r.disconnect()


def test_available_and_null() -> None:
    check("ツールがそろえば使える", _route(_Runner([])).available())
    missing = PipeWireRoute(runner=_Runner([]), pid=OWN_PID, which=lambda c: None if c == "pw-link" else "/x")
    check("ツールが欠ければ使えない", not missing.available())
    n = NullRoute()
    n.connect("x", "y")
    n.disconnect()
    check("NullRoute は何もしない", not n.available() and n.targets() == []
          and n.status() == {"app": "", "connected": False})


if __name__ == "__main__":
    test_targets_exclude_self()
    test_connect_links_every_input_port()
    test_reconnect_when_stream_reopens()
    test_dump_failure_marks_disconnected()
    test_available_and_null()
    sys.exit(0 if all(results) else 1)
