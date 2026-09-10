"""AI 分析の対象外リストの検証

実行: uv run python tests/test_forbid_analyze.py
daemon は不要。実際のデータディレクトリは触らない。
"""
from __future__ import annotations
import io
import json
import os
import tempfile

DATA = os.path.join(tempfile.gettempdir(), "shadow-clerk-forbid-test")
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault("SHADOW_CLERK_DATA_DIR", DATA)

from shadow_clerk.domain.forbid_analyze import (  # noqa: E402
    MAX_ITEMS, MAX_ITEM_LEN, ForbidAnalyze)
from shadow_clerk._daemon_dashboard_ops_console import (  # noqa: E402
    _DashboardHandlerConsoleOps as Ops)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _FakeHandler(Ops):
    def __init__(self, body: dict | None = None, client: str = "127.0.0.1",
                 origin: str | None = None) -> None:
        raw = json.dumps(body or {}).encode("utf-8")
        self.path = "/api/forbid-analyze"
        self.client_address = (client, 1)
        self.headers = {"Content-Length": str(len(raw)), "Host": "localhost:8765"}
        if origin is not None:
            self.headers["Origin"] = origin
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}

    def _send_json(self, data: dict) -> None:
        self.sent = data


# --- 読み込み ---

def test_parse() -> None:
    """`- x` も `x` も受ける。空行とコメントは落とす"""
    got = ForbidAnalyze._parse("- 個人の評価\n\n# メモ\nプライベート\n-\n  - 給与  \n")
    check("箇条書きの記号を外す", got == ("個人の評価", "プライベート", "給与"), str(got))
    check("空ファイルは制限なし", ForbidAnalyze._parse("") == ())
    check("長すぎる項目は切り詰める",
          len(ForbidAnalyze._parse("- " + "あ" * 500)[0]) == MAX_ITEM_LEN)
    check("件数の上限で止まる",
          len(ForbidAnalyze._parse("\n".join(f"- {i}" for i in range(MAX_ITEMS + 50))))
          == MAX_ITEMS)


def test_missing_file_means_no_restriction() -> None:
    """**不在は「制限なし」。** ここを取り違えると全会議の分析が止まる"""
    fa = ForbidAnalyze.load(os.path.join(DATA, "does-not-exist.txt"))
    check("ファイルが無ければ空", fa.items == ())


def test_round_trip() -> None:
    path = os.path.join(DATA, "rt.txt")
    ok = ForbidAnalyze(("個人の評価", "プライベートの内容")).save(path)
    check("保存できる", ok)
    check("書式は箇条書き",
          open(path, encoding="utf-8").read() == "- 個人の評価\n- プライベートの内容\n",
          repr(open(path, encoding="utf-8").read()))
    check("読み直すと同じ",
          ForbidAnalyze.load(path).items == ("個人の評価", "プライベートの内容"))

    ForbidAnalyze(()).save(path)
    check("空で保存すると空ファイル", open(path, encoding="utf-8").read() == "")
    check("空ファイルは制限なし", ForbidAnalyze.load(path).items == ())


def test_from_items() -> None:
    """UI から来た配列の正規化"""
    fa = ForbidAnalyze.from_items(["  個人の評価  ", "個人の評価", "", 3, None, "給与"])
    check("前後の空白を落とす", fa.items[0] == "個人の評価", str(fa.items))
    check("重複を落とす", fa.items == ("個人の評価", "給与"), str(fa.items))
    check("配列でなければ空", ForbidAnalyze.from_items("個人の評価").items == ())
    check("件数の上限を守る",
          len(ForbidAnalyze.from_items([str(i) for i in range(MAX_ITEMS + 50)]).items)
          == MAX_ITEMS)


# --- エンドポイント ---

def test_endpoints() -> None:
    h = _FakeHandler()
    h._serve_forbid_analyze()
    check("GET は status/path/items を返す",
          {"status", "path", "items"} <= set(h.sent), str(h.sent.keys()))

    h = _FakeHandler({"items": ["個人の評価", "  ", "給与"]},
                     origin="http://localhost:8765")
    h._save_forbid_analyze()
    check("POST で保存できる", h.sent.get("status") == "ok", str(h.sent))
    check("空要素は落ちる", h.sent.get("items") == ["個人の評価", "給与"], str(h.sent))

    h = _FakeHandler()
    h._serve_forbid_analyze()
    check("保存した内容が読める", h.sent.get("items") == ["個人の評価", "給与"], str(h.sent))

    h = _FakeHandler({"items": []}, origin="http://localhost:8765")
    h._save_forbid_analyze()
    h = _FakeHandler()
    h._serve_forbid_analyze()
    check("空で保存すると制限なしに戻る", h.sent.get("items") == [], str(h.sent))


def test_guards() -> None:
    """PTY へのキー入力と同じ経路 (_console_body) を通すこと"""
    h = _FakeHandler({"items": ["x"]}, client="192.168.1.50")
    h._save_forbid_analyze()
    check("localhost 以外は拒否", h.sent.get("status") == "error", str(h.sent))

    h = _FakeHandler({"items": ["x"]}, origin="http://evil.example")
    h._save_forbid_analyze()
    check("クロスオリジンは拒否", h.sent.get("status") == "error", str(h.sent))


# --- UI ---

def test_ui_wiring() -> None:
    from shadow_clerk._daemon_dashboard_js_settings import _JS_TEMPLATE_SETTINGS as J
    from shadow_clerk._i18n_ja import STRINGS_JA
    from shadow_clerk._i18n_en import STRINGS_EN
    check("設定モーダルに項目がある", "type:'forbid'" in J)
    check("定型はチェックボックス", "type='checkbox'" in J and "FORBID_PRESETS" in J)
    check("自由入力もある", "cfg_forbid_free" in J and "textarea" in J)
    check("保存は専用エンドポイントへ", "'/api/forbid-analyze'" in J)
    check("config.yaml には送らない", "if(f.type==='forbid')return;" in J)
    keys = [k for k in STRINGS_JA if k.startswith("cfg.forbid")]
    check("i18n が日英で揃っている",
          len(keys) >= 7 and all(k in STRINGS_EN for k in keys), str(len(keys)))


def main() -> int:
    test_parse()
    test_missing_file_means_no_restriction()
    test_round_trip()
    test_from_items()
    test_endpoints()
    test_guards()
    test_ui_wiring()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
