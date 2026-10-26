"""mtg 設定エンドポイントの検証

実行: uv run python tests/test_meeting_config_ops.py
"""
from __future__ import annotations
import io
import json
import os
import tempfile

DATA = os.path.join(tempfile.gettempdir(), "shadow-clerk-meetingcfg-test")
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault("SHADOW_CLERK_DATA_DIR", DATA)
# 実際の ~/.config/mtg/config.yaml を触らないよう、テスト用の設定に固定する
os.environ["MEETING_CONFIG"] = os.path.join(DATA, "mtg.yaml")
with open(os.environ["MEETING_CONFIG"], "w", encoding="utf-8") as _f:
    _f.write("defaults:\n  workdir: ~/meeting-analysis\nmeetings: []\n")

from shadow_clerk._daemon_dashboard_ops_console import (  # noqa: E402
    _DashboardHandlerConsoleOps as Ops)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _FakeHandler(Ops):
    def __init__(self, body: dict | None = None, client: str = "127.0.0.1") -> None:
        raw = json.dumps(body or {}).encode("utf-8")
        self.path = "/api/meeting-config"
        self.client_address = (client, 1)
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}

    def _send_json(self, data: dict) -> None:
        self.sent = data


def test_serve_shape() -> None:
    h = _FakeHandler()
    h._serve_meeting_config()
    for key in ("path", "default_workdir", "rules"):
        check(f"{key} を返す", key in h.sent, repr(sorted(h.sent)))


def test_upsert_then_read_back() -> None:
    h = _FakeHandler({"pattern": "Board", "workdir": "/tmp"})
    h._save_meeting_config()
    check("保存が成功する", h.sent.get("status") == "ok", repr(h.sent))
    h2 = _FakeHandler()
    h2._serve_meeting_config()
    rules = h2.sent.get("rules") or []
    check("保存したルールが読める",
          any(r["pattern"] == "Board" and r["workdir"] == "/tmp" for r in rules),
          repr(rules))


def test_delete() -> None:
    _FakeHandler({"pattern": "Gone", "workdir": "/x"})._save_meeting_config()
    h = _FakeHandler({"pattern": "Gone", "delete": True})
    h._save_meeting_config()
    h2 = _FakeHandler()
    h2._serve_meeting_config()
    check("削除できる",
          all(r["pattern"] != "Gone" for r in (h2.sent.get("rules") or [])),
          repr(h2.sent.get("rules")))


def test_invalid_regex_rejected() -> None:
    h = _FakeHandler({"pattern": "[", "workdir": "/x"})
    h._save_meeting_config()
    check("不正な正規表現は保存しない", h.sent.get("status") == "error", repr(h.sent))


def test_empty_pattern_rejected() -> None:
    h = _FakeHandler({"pattern": "", "workdir": "/x"})
    h._save_meeting_config()
    check("空の pattern は保存しない", h.sent.get("status") == "error", repr(h.sent))


def test_remote_rejected() -> None:
    h = _FakeHandler({"pattern": "P", "workdir": "/x"}, client="10.0.0.1")
    h._save_meeting_config()
    check("外部からの保存を拒否する", h.sent.get("status") == "error", repr(h.sent))


def test_meeting_settings() -> None:
    h = _FakeHandler({"meetings": ["週次定例", "1on1 alice"], "set": {"publish": False, "publish_advice": True, "analyze": False}})
    h._save_meeting_settings()
    check("まとめて保存できる", h.sent.get("status") == "ok", repr(h.sent))
    h = _FakeHandler()
    h.path = "/api/meeting-settings?meeting=%E9%80%B1%E6%AC%A1%E5%AE%9A%E4%BE%8B&meeting=other"
    h._serve_meeting_settings()
    got = {m["name"]: m for m in h.sent.get("meetings", [])}
    check("会議ごとの値を返す",
          got["週次定例"]["publish"] is False and got["週次定例"]["publish_advice"] is True
          and got["週次定例"]["shared"] is False and got["other"]["matched"] == "(defaults)"
          and got["other"]["publish_advice"] is False, repr(got))
    check("AI分析の有無を返す", got["週次定例"]["analyze"] is False and got["other"]["analyze"] is True, repr(got))
    for body, label in (({"meetings": [], "set": {}}, "会議なし"), ({"meetings": ["x"], "set": {"publish_to": "x"}}, "不正な値"),
                        ({"meetings": [3], "set": {}}, "文字列でない会議名")):
        h = _FakeHandler(body)
        h._save_meeting_settings()
        check(f"{label}は拒否", h.sent.get("status") == "error", repr(h.sent))
    h = _FakeHandler({"meetings": ["x"], "set": {"publish": True}}, client="10.0.0.1")
    h._save_meeting_settings()
    check("外部からのまとめて保存を拒否する", h.sent.get("status") == "error", repr(h.sent))


def main() -> int:
    test_meeting_settings()
    test_serve_shape()
    test_upsert_then_read_back()
    test_delete()
    test_invalid_regex_rejected()
    test_empty_pattern_rejected()
    test_remote_rejected()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
