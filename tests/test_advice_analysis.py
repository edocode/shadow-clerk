"""advice / analysis の配信検証

実行: uv run python tests/test_advice_analysis.py
"""
from __future__ import annotations
import io
import json
import os
import tempfile

DATA = os.path.join(tempfile.gettempdir(), "shadow-clerk-advice-test")
os.makedirs(DATA, exist_ok=True)
os.environ.setdefault("SHADOW_CLERK_DATA_DIR", DATA)

from shadow_clerk._daemon_dashboard_ops_console import (  # noqa: E402
    _DashboardHandlerConsoleOps as Ops)
from shadow_clerk._transcript_name import TranscriptName  # noqa: E402
from shadow_clerk._daemon_dashboard_base import _DashboardHandlerBase as Base  # noqa: E402
from shadow_clerk._daemon_dashboard_html import _HTML_TEMPLATE as _HTML  # noqa: E402
from shadow_clerk._daemon_dashboard_js_panels import _JS_TEMPLATE_PANELS as _JS  # noqa: E402
from shadow_clerk._i18n_ja import STRINGS_JA as _JA  # noqa: E402
from shadow_clerk._i18n_en import STRINGS_EN as _EN  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _FakeHandler(Ops):
    def __init__(self, query: str = "", client: str = "127.0.0.1") -> None:
        self.path = "/api/advice" + (f"?{query}" if query else "")
        self.client_address = (client, 1)
        self.headers = {"Content-Length": "0"}
        self.rfile = io.BytesIO(b"")
        self.sent: dict = {}
        self.recorder = type("_Rec", (), {
            "output_path": os.path.join(DATA, "transcript-202608271610@Board.txt"),
            "_output_dir": DATA})()

    def _send_json(self, data: dict) -> None:
        self.sent = data


def test_filenames() -> None:
    """命名は TranscriptName が持つ。ここが唯一の規則であることを固定する"""
    tn = TranscriptName.parse("transcript-202608271610@Board.txt")
    check("advice のファイル名", tn.advice_filename == "advice-202608271610@Board.md",
          tn.advice_filename)
    daily = TranscriptName.parse("transcript-20260827.txt")
    check("analysis のファイル名（会議名なし）",
          daily.analysis_filename == "analysis-20260827.md", daily.analysis_filename)


def test_generated_paths_endpoint() -> None:
    """スキルが命名規則を持たずに済むよう、絶対パスを返す"""
    h = _FakeHandler("file=transcript-202608271610@Board.txt")
    h._serve_generated_paths()
    d = h.sent
    check("status ok", d.get("status") == "ok", repr(d))
    check("summary の絶対パス",
          d.get("summary") == os.path.join(DATA, "summary-202608271610@Board.md"), repr(d))
    check("advice の絶対パス",
          d.get("advice") == os.path.join(DATA, "advice-202608271610@Board.md"), repr(d))
    check("analysis の絶対パス",
          d.get("analysis") == os.path.join(DATA, "analysis-202608271610@Board.md"), repr(d))
    check("会議名を返す", d.get("meeting") == "Board", repr(d.get("meeting")))
    check("exists に4種そろう", set(d.get("exists", {})) ==
          {"transcript", "summary", "advice", "analysis"}, repr(d.get("exists")))


def test_generated_paths_rejects_bad_name() -> None:
    h = _FakeHandler("file=../../etc/passwd")
    h._serve_generated_paths()
    check("パスを含む指定を拒否する", h.sent.get("status") == "error", repr(h.sent))
    h = _FakeHandler("file=notes.md")
    h._serve_generated_paths()
    check("transcript でない名前を拒否する", h.sent.get("status") == "error", repr(h.sent))


def test_generated_paths_rejects_remote() -> None:
    h = _FakeHandler("file=transcript-202608271610@Board.txt", client="10.0.0.9")
    h._serve_generated_paths()
    check("外部からの取得を拒否する", h.sent.get("status") == "error", repr(h.sent))


def test_serve_advice_reads_file() -> None:
    path = os.path.join(DATA, "advice-202608271610@Board.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("## 未解決\n- 期限が未定\n")
    h = _FakeHandler("file=transcript-202608271610@Board.txt")
    h._serve_advice()
    html = h.sent.get("html") or ""
    check("advice の中身を返す", "期限が未定" in html, repr(h.sent))
    check("Markdown が HTML になっている", "<h2>未解決</h2>" in html and "<li>" in html,
          repr(html))
    check("advice のファイル名を返す",
          h.sent.get("file") == "advice-202608271610@Board.md", repr(h.sent))


def test_serve_advice_missing_is_empty() -> None:
    h = _FakeHandler("file=transcript-20990101.txt")
    h._serve_advice()
    check("無ければ空文字でエラーにしない", h.sent.get("html") == "", repr(h.sent))


def test_serve_analysis_renders_markdown() -> None:
    path = os.path.join(DATA, "analysis-202608271610@Board.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("## 16:10\n- 決定した\n")
    h = _FakeHandler("file=transcript-202608271610@Board.txt")
    h._serve_analysis()
    html = h.sent.get("html") or ""
    check("analysis も HTML で返す", "<h2>16:10</h2>" in html and "決定した" in html,
          repr(html))


def test_generated_html_escapes_raw_html() -> None:
    """生成物は AI が書いた任意テキスト。ソース中の生 HTML を通してはならない"""
    path = os.path.join(DATA, "advice-202608271610@Board.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("- <script>alert(1)</script>\n- <img src=x onerror=alert(1)>\n")
    h = _FakeHandler("file=transcript-202608271610@Board.txt")
    h._serve_advice()
    html = h.sent.get("html") or ""
    check("生の <script> を通さない", "<script>" not in html, repr(html))
    check("実体参照に落ちている", "&lt;script&gt;" in html, repr(html))
    check("生の <img> を通さない", "<img" not in html, repr(html))


def test_generated_html_renders_tables() -> None:
    """commonmark プリセットは table を持たず、無効のままだと段落として扱われる。

    その場合 CommonMark が段落内の改行を空白に潰すため、テーブルが
    「| 時刻 | 発言 | |---|---| | 08:18 | …」の 1 行に崩れる（実際に起きた）。
    """
    path = os.path.join(DATA, "advice-202608271610@Board.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("| 時刻 | 発言 |\n|---|---|\n| 08:18 | あえて利上げ |\n| 08:29 | 利下げ |\n")
    h = _FakeHandler("file=transcript-202608271610@Board.txt")
    h._serve_advice()
    html = h.sent.get("html") or ""
    check("テーブルが table 要素になる", "<table>" in html and "<th>" in html, repr(html))
    check("行が潰れていない", html.count("<tr>") == 3, repr(html))
    check("1行に崩れていない", "|---|---|" not in html, repr(html))


def test_bad_filename_is_rejected() -> None:
    h = _FakeHandler("file=../../etc/passwd")
    h._serve_advice()
    check("パスを含むファイル名を拒否する", h.sent.get("html") == "", repr(h.sent))


class _FakeSummaryHandler(Base):
    """_serve_summary だけを叩く。BaseHTTPRequestHandler の __init__ は使わない"""

    def __init__(self, query: str = "") -> None:
        self.path = "/api/summary" + (f"?{query}" if query else "")
        self.sent: dict = {}
        self.recorder = type("_Rec", (), {"_output_dir": DATA})()

    def _send_json(self, data: dict) -> None:
        self.sent = data


def test_summary_is_delivered_as_html() -> None:
    """議事録も Markdown。画面には HTML を出すが、コピー用に生も要る"""
    with open(os.path.join(DATA, "summary-202608271610@Board.md"),
              "w", encoding="utf-8") as f:
        f.write("# 議事録\n\n- 決めたこと\n")
    h = _FakeSummaryHandler("file=transcript-202608271610@Board.txt")
    h._serve_summary()
    check("生の Markdown を返す", h.sent.get("content", "").startswith("# 議事録"),
          repr(h.sent.get("content")))
    html = h.sent.get("html") or ""
    check("HTML にも起こす", "<h1>" in html and "<li>" in html, repr(html))


def test_summary_missing_is_empty() -> None:
    h = _FakeSummaryHandler("file=transcript-20990101@None.txt")
    h._serve_summary()
    check("無ければ両方とも空",
          h.sent.get("content") == "" and h.sent.get("html") == "", repr(h.sent))


def test_dashboard_shows_and_copies_summary() -> None:
    """再生成しか無いと、PTY 側が書いた議事録を取り込む手段が無い"""
    check("再読み込みボタンがある",
          'onclick="loadS(curFile)"' in _HTML and "dash.summary_reload" in _HTML, "")
    check("Markdown コピーのボタンがある",
          'onclick="copySummaryMd()"' in _HTML and "dash.summary_copy" in _HTML, "")
    _load = _JS[_JS.index("async function loadS("):_JS.index("async function copySummaryMd(")]
    check("HTML で描く", "'<div class=\"md-body\">'+sumD.html" in _load, "")
    check("レンダラが落ちたら生を出す", "summary-body" in _load, "")
    check("コピー用に生を持つ", "_sumMd=sumD.content" in _load, "")
    _copy = _JS[_JS.index("async function copySummaryMd("):]
    check("クリップボードへ Markdown を渡す",
          "navigator.clipboard.writeText(_sumMd)" in _copy, "")
    # localhost 以外の http では clipboard API が無い
    check("使えないときの逃げ道がある", "ok=document.execCommand('copy')" in _copy, "")
    # 失敗しても ✓ を出すと、貼り付けて初めて空だと気づくことになる
    check("成否で印を変える", "ok?'\u2713':'\u2717'" in _copy, "")
    for k in ("dash.summary_reload", "dash.summary_copy"):
        check(f"i18n に {k} がある", k in _JA and k in _EN, "")


def main() -> int:
    test_filenames()
    test_generated_paths_endpoint()
    test_generated_paths_rejects_bad_name()
    test_generated_paths_rejects_remote()
    test_serve_advice_reads_file()
    test_serve_advice_missing_is_empty()
    test_serve_analysis_renders_markdown()
    test_generated_html_escapes_raw_html()
    test_generated_html_renders_tables()
    test_bad_filename_is_rejected()
    test_summary_is_delivered_as_html()
    test_summary_missing_is_empty()
    test_dashboard_shows_and_copies_summary()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
