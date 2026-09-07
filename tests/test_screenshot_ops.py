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

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


NOW = datetime.datetime(2026, 9, 7, 14, 21, 44)
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 32).decode()


class _FakeHandler(Ops):
    """_save_screenshot を呼ぶための最小の器"""

    def __init__(self, body: dict, client: str = "127.0.0.1",
                 output_path: str = "") -> None:
        raw = json.dumps(body).encode("utf-8")
        self.client_address = (client, 12345)
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        # daemon では DashboardHandler.recorder がクラス属性で入る
        self.recorder = type("_Rec", (), {"output_path": output_path})()

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
    tp = os.path.join(d, "transcript-202609071358@t.txt")
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
    meeting = os.path.join(d, "transcript-202609071358@m.txt")
    daily = os.path.join(d, "transcript-20260907.txt")
    for f in (meeting, daily):
        open(f, "w", encoding="utf-8").close()

    # 会議モード: .clerk_session が会議 transcript を指す
    _ops_mod.SESSION_FILE = os.path.join(d, ".clerk_session")
    with open(_ops_mod.SESSION_FILE, "w", encoding="utf-8") as f:
        f.write(meeting)
    h = _FakeHandler({}, output_path=daily)
    check("12. 会議モードでは .clerk_session を優先する",
          h._screenshot_target_transcript() == meeting)

    # 日次モード: .clerk_session が無いので recorder の出力先へ
    _ops_mod.SESSION_FILE = os.path.join(d, "no-session")
    h = _FakeHandler({}, output_path=daily)
    check("13. 会議モードでなければ recorder の出力先に書く",
          h._screenshot_target_transcript() == daily)

    # .clerk_session が指す先が消えている場合も出力先に落ちる
    _ops_mod.SESSION_FILE = os.path.join(d, ".clerk_session")
    with open(_ops_mod.SESSION_FILE, "w", encoding="utf-8") as f:
        f.write(os.path.join(d, "gone.txt"))
    h = _FakeHandler({}, output_path=daily)
    check("14. セッションの指す先が無ければ出力先に落ちる",
          h._screenshot_target_transcript() == daily)

    # どちらも無ければ空
    _ops_mod.SESSION_FILE = os.path.join(d, "no-session")
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

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
