"""聞き間違い候補の記録の検証

実行: uv run python tests/test_misheard.py
daemon は不要。実際のデータディレクトリは触らない。
"""
from __future__ import annotations
import io
import json
import os
import tempfile

DATA = os.path.join(tempfile.gettempdir(), "shadow-clerk-misheard-test")
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault("SHADOW_CLERK_DATA_DIR", DATA)

from shadow_clerk.domain import misheard  # noqa: E402
from shadow_clerk.domain.misheard import HEADER, MAX_ENTRIES, MAX_FIELD_LEN  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_console import (  # noqa: E402
    _DashboardHandlerConsoleOps as Ops)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def _path(name: str) -> str:
    p = os.path.join(DATA, name)
    if os.path.exists(p):
        os.remove(p)
    return p


class _FakeHandler(Ops):
    def __init__(self, body: dict | None = None, client: str = "127.0.0.1",
                 origin: str | None = None) -> None:
        raw = json.dumps(body or {}).encode("utf-8")
        self.path = "/api/misheard"
        self.client_address = (client, 1)
        self.headers = {"Content-Length": str(len(raw)), "Host": "localhost:8765"}
        if origin is not None:
            self.headers["Origin"] = origin
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}

    def _send_json(self, data: dict) -> None:
        self.sent = data


def test_append_and_load() -> None:
    p = _path("a.tsv")
    added = misheard.append([{"actual": "工数", "heard": "個数", "note": "推定"}], p)
    check("追加できる", [e.to_row() for e in added] == ["工数\t個数\t推定"],
          str([e.to_row() for e in added]))
    check("ヘッダ付きで書き出す",
          open(p, encoding="utf-8").read().startswith(HEADER + "\n"),
          repr(open(p, encoding="utf-8").read()))
    got = misheard.load(p)
    check("読み直せる", [(e.actual, e.heard, e.note) for e in got] == [("工数", "個数", "推定")])

    misheard.append([{"actual": "遷移", "heard": "繊維"}], p)
    check("追記される", len(misheard.load(p)) == 2, str(len(misheard.load(p))))


def test_duplicates_are_dropped() -> None:
    """同じ崩れは何度も現れるので、重複を捨てないと同じ行が積み上がる"""
    p = _path("d.tsv")
    misheard.append([{"actual": "工数", "heard": "個数"}], p)
    again = misheard.append([{"actual": "工数", "heard": "個数", "note": "別の備考"}], p)
    check("既にある対は足さない", again == [], str(again))
    check("行数は増えない", len(misheard.load(p)) == 1)

    batch = misheard.append([{"actual": "仕様", "heard": "使用"},
                             {"actual": "仕様", "heard": "使用"}], p)
    check("同じ送信内の重複も落とす", len(batch) == 1, str(len(batch)))
    check("備考違いは同じ対とみなす",
          len({e.key for e in misheard.load(p)}) == len(misheard.load(p)))


def test_missing_file() -> None:
    check("ファイルが無ければ空", misheard.load(os.path.join(DATA, "none.tsv")) == [])


def test_bad_input() -> None:
    p = _path("b.tsv")
    check("配列でなければ何もしない", misheard.append("工数", p) == [])
    check("dict 以外は飛ばす", misheard.append([1, None, "x"], p) == [])
    check("片方が空なら足さない",
          misheard.append([{"actual": "工数"}, {"heard": "個数"}], p) == [])

    added = misheard.append([{"actual": "工\t数", "heard": "個\n数", "note": "a\tb"}], p)
    check("タブと改行は空白に落とす", added[0].to_row() == "工 数\t個 数\ta b",
          repr(added[0].to_row()))
    check("TSV が壊れない", len(misheard.load(p)) == 1)

    misheard.append([{"actual": "あ" * 500, "heard": "い"}], p)
    check("長すぎる値は詰める",
          all(len(e.actual) <= MAX_FIELD_LEN for e in misheard.load(p)))


def test_comments_and_header_are_skipped() -> None:
    p = _path("c.tsv")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"{HEADER}\n# メモ\n\n工数\t個数\t\n壊れた行\n")
    got = misheard.load(p)
    check("ヘッダ・コメント・空行・片欠けを飛ばす",
          [(e.actual, e.heard) for e in got] == [("工数", "個数")], str(got))


def test_cap() -> None:
    p = _path("cap.tsv")
    misheard.append([{"actual": f"a{i}", "heard": "x"} for i in range(MAX_ENTRIES + 50)], p)
    check("件数の上限を守る", len(misheard.load(p)) == MAX_ENTRIES,
          str(len(misheard.load(p))))


def test_endpoints() -> None:
    real = os.path.join(DATA, "misheard.tsv")
    if os.path.exists(real):
        os.remove(real)
    h = _FakeHandler()
    h._serve_misheard()
    check("GET は空でも返る", h.sent.get("entries") == [], str(h.sent))

    h = _FakeHandler({"entries": [{"actual": "遷移", "heard": "繊維", "note": "推定"}]},
                     origin="http://localhost:8765")
    h._save_misheard()
    check("POST で足せる", len(h.sent.get("added", [])) == 1, str(h.sent))

    h = _FakeHandler()
    h._serve_misheard()
    check("GET で読める", h.sent.get("entries") == [
        {"actual": "遷移", "heard": "繊維", "note": "推定"}], str(h.sent))

    h = _FakeHandler({"entries": [{"actual": "遷移", "heard": "繊維"}]},
                     origin="http://localhost:8765")
    h._save_misheard()
    check("重複は added が空で返る", h.sent.get("added") == [], str(h.sent))


def test_guards() -> None:
    h = _FakeHandler({"entries": [{"actual": "a", "heard": "b"}]}, client="192.168.1.50")
    h._save_misheard()
    check("localhost 以外は拒否", h.sent.get("status") == "error", str(h.sent))

    h = _FakeHandler({"entries": [{"actual": "a", "heard": "b"}]},
                     origin="http://evil.example")
    h._save_misheard()
    check("クロスオリジンは拒否", h.sent.get("status") == "error", str(h.sent))


def test_docs_point_at_the_file() -> None:
    """型の説明と、貯める場所が分かれていること"""
    skill = open("skills/mtg/SKILL.md", encoding="utf-8").read()
    quirks = open("skills/mtg/references/transcript-quirks.md", encoding="utf-8").read()
    check("SKILL に読み書きの手順がある",
          "/api/misheard" in skill and "推定" in skill)
    check("quirks は具体的な対を持たない", "| 工数 | 個数" not in quirks)
    check("quirks がファイルを指す", "/api/misheard" in quirks and "misheard.tsv" in quirks)


def main() -> int:
    test_append_and_load()
    test_duplicates_are_dropped()
    test_missing_file()
    test_bad_input()
    test_comments_and_header_are_skipped()
    test_cap()
    test_endpoints()
    test_guards()
    test_docs_point_at_the_file()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
