"""検出言語を切り替える API（POST /api/language）の検証

実行: uv run python tests/test_language_api.py
talk の skill が、ユーザーが英語で話したいときに切り替えるために使う。
"""
from __future__ import annotations
import io
import json
import sys

from shadow_clerk._daemon_dashboard_ops_skill import _DashboardHandlerSkillOps as Ops

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Handler(Ops):
    def __init__(self, body: object, client: str = "127.0.0.1") -> None:
        raw = json.dumps(body).encode("utf-8")
        self.client_address = (client, 1)
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        self.commands: list[str] = []
        self.recorder = type("_Rec", (), {"_execute_command": lambda _s, c: self.commands.append(c)})()

    def _send_json(self, d: dict) -> None:
        self.sent = d


def test_switch() -> None:
    h = _Handler({"language": "en"})
    h._set_language()
    check("en に切り替える", h.commands == ["set_language en"] and h.sent == {"status": "ok", "language": "en"},
          repr((h.commands, h.sent)))
    h = _Handler({"language": "auto"})
    h._set_language()
    check("auto は自動検出に戻す", h.commands == ["unset_language"] and h.sent == {"status": "ok", "language": "auto"},
          repr((h.commands, h.sent)))


def test_rejects() -> None:
    for body, label in [({"language": "xx"}, "知らない言語"), ({"language": "en; start_meeting"}, "コマンドの混入"),
                        ({"language": 1}, "文字列でない"), ({}, "指定なし")]:
        h = _Handler(body)
        h._set_language()
        check(f"{label}は拒否", h.sent.get("status") == "error" and h.commands == [], repr((h.commands, h.sent)))
    h = _Handler({"language": "en"}, client="10.0.0.9")
    h._set_language()
    check("外部からは拒否", h.sent.get("status") == "error" and h.commands == [], repr(h.sent))


if __name__ == "__main__":
    test_switch()
    test_rejects()
    sys.exit(0 if all(results) else 1)
