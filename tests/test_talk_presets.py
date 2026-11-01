"""「Claude と会話」のモード（/api/talk-presets）: 組み込みのモードと、その削除

実行: uv run pytest -q tests/test_talk_presets.py
"""
from __future__ import annotations

import io
import json
import os
import tempfile

os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-talk-presets-")

from shadow_clerk._daemon_constants import BUILTIN_TALK_PRESETS, TALK_PRESETS_FILE  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_config import _DashboardHandlerConfigOps as Ops  # noqa: E402

BUILTINS = [p["name"] for p in BUILTIN_TALK_PRESETS]


class _Handler(Ops):
    def __init__(self, body: object = None) -> None:
        raw = json.dumps(body or {}).encode("utf-8")
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}

    def _send_json(self, d: dict) -> None:
        self.sent = d

    def _atomic_write_lines(self, path: str, lines: list[str]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)


def names() -> list[str]:
    h = _Handler()
    h._serve_talk_presets()
    return [p["name"] for p in h.sent["presets"]]


def test_builtins_save_and_delete() -> None:
    if os.path.exists(TALK_PRESETS_FILE):
        os.remove(TALK_PRESETS_FILE)
    assert names() == BUILTINS
    _Handler({"name": "acme 相談", "fields": {"topic": "x"}})._save_talk_preset()
    assert names() == [*BUILTINS, "acme 相談"]
    # 組み込みを消すと出なくなり、保存したモードの保存・削除をしても戻らない
    _Handler({"name": BUILTINS[0]})._delete_talk_preset()
    _Handler({"name": "acme 相談"})._delete_talk_preset()
    _Handler({"name": "acme 2", "fields": {}})._save_talk_preset()
    assert names() == [*BUILTINS[1:], "acme 2"]
    # 同じ名前で保存すれば、保存したほうが使われる（組み込みは重ねて出さない）
    _Handler({"name": BUILTINS[1], "fields": {"topic": "mine"}})._save_talk_preset()
    h = _Handler()
    h._serve_talk_presets()
    assert [p["name"] for p in h.sent["presets"]].count(BUILTINS[1]) == 1
    assert next(p for p in h.sent["presets"] if p["name"] == BUILTINS[1])["fields"] == {"topic": "mine"}
