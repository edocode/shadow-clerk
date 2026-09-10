"""mtg 設定エンドポイントの検証

実行: uv run python tests/test_mtg_config_ops.py
"""
from __future__ import annotations
import io
import json
import os
import tempfile

DATA = os.path.join(tempfile.gettempdir(), "shadow-clerk-mtgcfg-test")
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault("SHADOW_CLERK_DATA_DIR", DATA)
# 実際の ~/.config/mtg/config.yaml を触らないよう、テスト用の設定に固定する
os.environ["MTG_CONFIG"] = os.path.join(DATA, "mtg.yaml")
with open(os.environ["MTG_CONFIG"], "w", encoding="utf-8") as _f:
    _f.write("defaults:\n  workdir: ~/mtg-analysis\nmeetings: []\n")

from shadow_clerk._daemon_dashboard_ops_console import (  # noqa: E402
    _DashboardHandlerConsoleOps as Ops)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _FakeHandler(Ops):
    def __init__(self, body: dict | None = None, client: str = "127.0.0.1") -> None:
        raw = json.dumps(body or {}).encode("utf-8")
        self.path = "/api/mtg-config"
        self.client_address = (client, 1)
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}

    def _send_json(self, data: dict) -> None:
        self.sent = data


def test_serve_shape() -> None:
    h = _FakeHandler()
    h._serve_mtg_config()
    for key in ("path", "default_workdir", "rules"):
        check(f"{key} を返す", key in h.sent, repr(sorted(h.sent)))


def test_upsert_then_read_back() -> None:
    h = _FakeHandler({"pattern": "Board", "workdir": "/tmp"})
    h._save_mtg_config()
    check("保存が成功する", h.sent.get("status") == "ok", repr(h.sent))
    h2 = _FakeHandler()
    h2._serve_mtg_config()
    rules = h2.sent.get("rules") or []
    check("保存したルールが読める",
          any(r["pattern"] == "Board" and r["workdir"] == "/tmp" for r in rules),
          repr(rules))


def test_delete() -> None:
    _FakeHandler({"pattern": "Gone", "workdir": "/x"})._save_mtg_config()
    h = _FakeHandler({"pattern": "Gone", "delete": True})
    h._save_mtg_config()
    h2 = _FakeHandler()
    h2._serve_mtg_config()
    check("削除できる",
          all(r["pattern"] != "Gone" for r in (h2.sent.get("rules") or [])),
          repr(h2.sent.get("rules")))


def test_invalid_regex_rejected() -> None:
    h = _FakeHandler({"pattern": "[", "workdir": "/x"})
    h._save_mtg_config()
    check("不正な正規表現は保存しない", h.sent.get("status") == "error", repr(h.sent))


def test_empty_pattern_rejected() -> None:
    h = _FakeHandler({"pattern": "", "workdir": "/x"})
    h._save_mtg_config()
    check("空の pattern は保存しない", h.sent.get("status") == "error", repr(h.sent))


def test_remote_rejected() -> None:
    h = _FakeHandler({"pattern": "P", "workdir": "/x"}, client="10.0.0.1")
    h._save_mtg_config()
    check("外部からの保存を拒否する", h.sent.get("status") == "error", repr(h.sent))


def main() -> int:
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
