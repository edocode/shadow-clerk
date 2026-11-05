"""画面キャプチャ受け取りエンドポイントの検証

実行: uv run python tests/test_screenshot_ops.py
daemon も音声デバイスも不要（tmp ディレクトリ内で完結する）。
"""
from __future__ import annotations
import base64
import datetime
import io
import json
import os
import tempfile

from shadow_clerk._daemon_dashboard_ops_screenshot import _DashboardHandlerScreenshotOps as Ops
from shadow_clerk._daemon_screen_capture import ScreenCaptureError

results: list[bool] = []



def _at(root: str, name: str) -> str:
    """記録のファイルはその回のフォルダ（区分 / 会議名）、それ以外は root 直下"""
    from shadow_clerk._transcript_layout import TranscriptLayout
    return TranscriptLayout(root).path(name) or os.path.join(root, name)

def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


NOW = datetime.datetime(2026, 9, 7, 14, 21, 44)
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 32).decode()


class _FakeHandler(Ops):
    """_save_screenshot を呼ぶための最小の器"""

    def __init__(self, body: dict, client: str = "127.0.0.1",
                 output_path: str = "", origin: str | None = None) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.client_address = (client, 12345)
        self.headers = {"Content-Length": str(len(raw))}
        if origin is not None:
            self.headers["Origin"] = origin
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        # daemon では DashboardHandler.recorder がクラス属性で入る
        self.recorder = type("_Rec", (), {"output_path": output_path,
                                          "_output_dir": os.path.dirname(output_path) or tempfile.gettempdir()})()

    def _send_json(self, data) -> None:
        self.sent = data


# --- ファイル名 ---

check("1. 会議中は transcript の stem を引き継ぐ",
      Ops._screenshot_filename(
          "/data/transcript-202609071358@SFA営業管理ツールの件.txt", NOW)
      == "shot-202609071358@SFA営業管理ツールの件-142144.png")

check("2. 会議外は日付ベースの名前になる",
      Ops._screenshot_filename("", NOW) == "shot-20260907-142144.png")

check("3. transcript- で始まらないパスは日付ベースに落ちる",
      Ops._screenshot_filename("/data/daily-20260907.txt", NOW)
      == "shot-20260907-142144.png")

# --- transcript 追記 ---

with tempfile.TemporaryDirectory() as d:
    tp = _at(d, "transcript-202609071358@t.txt")
    with open(tp, "w", encoding="utf-8") as f:
        f.write("[2026-09-07 14:20:00] [自分] 既存の発言\n")

    ok = Ops._screenshot_append_transcript(tp, NOW, "shot-x.png", "Teams", "https://teams.example/x")
    lines = open(tp, encoding="utf-8").read().splitlines()
    check("4. 追記が成功する", ok)
    check("5. 既存行を壊さない", lines[0] == "[2026-09-07 14:20:00] [自分] 既存の発言")
    check("6. 話者ラベルは [画面]", "[画面]" in lines[-1], lines[-1])
    check("7. 時刻形式が transcript と同じ",
          lines[-1].startswith("[2026-09-07 14:21:44] "))
    check("8. 要約が読めるよう接頭辞が付く", "画面キャプチャ: shot-x.png" in lines[-1])
    check("9. タイトルと URL が入る",
          "Teams" in lines[-1] and "https://teams.example/x" in lines[-1])

    ok = Ops._screenshot_append_transcript(tp, NOW, "shot-y.png", "a|b", "http://e/?x=1|2")
    check("10. 区切りの | は値の中から除去される",
          open(tp, encoding="utf-8").read().splitlines()[-1].count(" | ") == 2)

    check("11. 追記先が無ければ False を返す",
          Ops._screenshot_append_transcript(
              os.path.join(d, "no", "such.txt"), NOW, "s.png", "", "") is False)

# --- 追記先の解決 ---

import shadow_clerk._daemon_dashboard_ops_screenshot as _ops_mod

with tempfile.TemporaryDirectory() as d:
    _saved_session_file = _ops_mod.SESSION_FILE
    meeting = _at(d, "transcript-202609071358@m.txt")
    daily = _at(d, "transcript-20260907.txt")
    for f in (meeting, daily):
        open(f, "w", encoding="utf-8").close()

    # 会議モード: .clerk_session が会議 transcript を指す
    _ops_mod.SESSION_FILE = _at(d, ".clerk_session")
    with open(_ops_mod.SESSION_FILE, "w", encoding="utf-8") as f:
        f.write(meeting)
    h = _FakeHandler({}, output_path=daily)
    check("12. 会議モードでは .clerk_session を優先する",
          h._screenshot_target_transcript() == meeting)

    # 日次モード: .clerk_session が無いので recorder の出力先へ
    _ops_mod.SESSION_FILE = _at(d, "no-session")
    h = _FakeHandler({}, output_path=daily)
    check("13. 会議モードでなければ recorder の出力先に書く",
          h._screenshot_target_transcript() == daily)

    # .clerk_session が指す先が消えている場合も出力先に落ちる
    _ops_mod.SESSION_FILE = _at(d, ".clerk_session")
    with open(_ops_mod.SESSION_FILE, "w", encoding="utf-8") as f:
        f.write(_at(d, "gone.txt"))
    h = _FakeHandler({}, output_path=daily)
    check("14. セッションの指す先が無ければ出力先に落ちる",
          h._screenshot_target_transcript() == daily)

    # どちらも無ければ空
    _ops_mod.SESSION_FILE = _at(d, "no-session")
    h = _FakeHandler({}, output_path="")
    check("15. 書ける先が無ければ空文字列",
          h._screenshot_target_transcript() == "")

    _ops_mod.SESSION_FILE = _saved_session_file

# --- リクエスト検証 ---

h = _FakeHandler({"image": f"data:image/png;base64,{PNG}"}, client="192.168.1.50")
h._save_screenshot()
check("16. localhost 以外は拒否する",
      h.sent.get("status") == "error" and "localhost" in h.sent.get("message", ""),
      h.sent.get("message", ""))

h = _FakeHandler({"image": "data:image/jpeg;base64,AAAA"})
h._save_screenshot()
check("17. png 以外の data URL を拒否する", h.sent.get("status") == "error")

h = _FakeHandler({"image": "data:image/png;base64,これはbase64ではない"})
h._save_screenshot()
check("18. 壊れた base64 を拒否する", h.sent.get("status") == "error")

h = _FakeHandler({"image": f"data:image/png;base64,{base64.b64encode(b'').decode()}"})
h._save_screenshot()
check("19. 空の画像を拒否する", h.sent.get("status") == "error")

h = _FakeHandler({})
h._save_screenshot()
check("20. image が無いリクエストを拒否する", h.sent.get("status") == "error")

# --- 画面全体（source: screen）は daemon が撮る ---

EXT = _ops_mod.EXTENSION_ORIGINS[0]
with tempfile.TemporaryDirectory() as d:
    _saved_session_file = _ops_mod.SESSION_FILE
    _ops_mod.SESSION_FILE = os.path.join(d, "no-session")
    daily = os.path.join(d, "transcript-20260907.txt")
    with open(daily, "w", encoding="utf-8") as f:
        f.write("[2026-09-07 14:20:00] [自分] 既存の発言\n")
    grabbed: list[int] = []

    def _grab() -> bytes:
        grabbed.append(1)
        return b"\x89PNG screen"

    def _screen(origin: str | None, grab=_grab) -> _FakeHandler:
        h = _FakeHandler({"source": "screen"}, output_path=daily, origin=origin)
        h._grab_screen = grab  # type: ignore[method-assign]
        h._save_screenshot()
        return h

    h = _screen(EXT)
    saved = os.path.join(d, h.sent.get("file", "?"))
    check("28. 同梱の拡張からの画面全体は daemon が撮って保存する",
          h.sent.get("status") == "ok" and open(saved, "rb").read() == b"\x89PNG screen", repr(h.sent))
    with open(daily, encoding="utf-8") as f:
        last = f.read().splitlines()[-1]
    check("29. 画面全体の [画面] 行には「画面全体」と書く", "| 画面全体" in last, last)
    grabbed.clear()
    for i, origin in ((30, None), (31, "chrome-extension://abcdefghijklmnopabcdefghijklmnop"),
                      (32, "http://127.0.0.1:8765")):
        h = _screen(origin)
        check(f"{i}. 同梱の拡張以外からの画面全体は撮らずに拒否する ({origin})",
              h.sent.get("status") == "error" and not grabbed, repr(h.sent))

    def _fail() -> bytes:
        raise ScreenCaptureError("screenshot portal declined (response 2)")
    h = _screen(EXT, _fail)
    check("33. 撮れなかった理由を返す",
          h.sent == {"status": "error", "message": "screenshot portal declined (response 2)"}, repr(h.sent))
    _ops_mod.SESSION_FILE = _saved_session_file

# --- GET: 保存したキャプチャを返す ---


class _GetHandler(Ops):
    """_serve_screenshot を呼ぶための最小の器"""

    def __init__(self, name: str) -> None:
        self.path = "/api/screenshot?file=" + __import__("urllib.parse").parse.quote(name)
        self.wfile = io.BytesIO()
        self.status = 0

    def send_error(self, code: int, *_: object) -> None:
        self.status = code

    def send_response(self, code: int, *_: object) -> None:
        self.status = code

    def send_header(self, *_: object) -> None:
        pass

    def end_headers(self) -> None:
        pass


with tempfile.TemporaryDirectory() as d:
    _GetHandler.recorder = type("_Rec", (), {"_output_dir": d})()
    shot = "shot-202609071358@定例-142144.png"
    with open(_at(d, shot), "wb") as f:
        f.write(b"\x89PNG")
    with open(_at(d, "config.yaml"), "w", encoding="utf-8") as f:
        f.write("a: 1\n")
    h = _GetHandler(shot)
    h._serve_screenshot()
    check("21. 保存したキャプチャを返す", h.status == 200 and h.wfile.getvalue() == b"\x89PNG")
    for i, bad in enumerate(["config.yaml", "shot-../config.yaml.png", "shot-x/../../a.png",
                             "shot-none.png", ""], 22):
        h = _GetHandler(bad)
        h._serve_screenshot()
        check(f"{i}. キャプチャ以外・存在しない名前は 404 ({bad!r})",
              h.status == 404 and not h.wfile.getvalue())
    # リネーム後: ファイル名の会議名は古いまま、transcript と同じ（新しい会議の）フォルダにある
    renamed = os.path.join(d, "private", "新定例")
    os.makedirs(renamed)
    os.replace(_at(d, shot), os.path.join(renamed, shot))
    h = _GetHandler(shot)
    h.path += "&transcript=" + __import__("urllib.parse").parse.quote("transcript-202609071358@新定例.txt")
    h._serve_screenshot()
    check("27. transcript のフォルダから引く（リネーム後も見つかる）", h.status == 200 and h.wfile.getvalue() == b"\x89PNG")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
