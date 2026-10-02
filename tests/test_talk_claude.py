"""常駐 claude プロセスの検証（偽 claude スクリプトを使う）

実行: uv run python tests/test_talk_claude.py
"""
from __future__ import annotations
import os
import sys
import tempfile
import threading

from shadow_clerk._daemon_talk_claude import ClaudeTalkProcess, build_claude_argv

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


# 受け取った user メッセージごとに init / 非 JSON 行 / assistant / result を返す。
# 引数 "die" なら何も読まずに終了コード 3 で落ちる
_FAKE = r'''
import json, sys
if sys.argv[1:] == ["die"]:
    sys.exit(3)
for line in sys.stdin:
    msg = json.loads(line)["message"]["content"]
    print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
    print("not json", flush=True)
    print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "x"}]}}), flush=True)
    if msg == "fail":
        print(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True}), flush=True)
    else:
        print(json.dumps({"type": "result", "subtype": "success", "result": "echo:" + msg}), flush=True)
'''


def _fake_script() -> str:
    path = os.path.join(tempfile.mkdtemp(), "fake_claude.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(_FAKE)
    return path


def test_roundtrip() -> None:
    replies: list[str] = []
    got = threading.Event()

    def on_reply(text: str) -> None:
        replies.append(text)
        if len(replies) == 2:
            got.set()

    exits: list[int | None] = []
    proc = ClaudeTalkProcess([sys.executable, _fake_script()], tempfile.gettempdir(),
                             on_reply, exits.append)
    proc.start()
    proc.send("こんにちは\n改行入り")
    proc.send("fail")
    got.wait(10)
    proc.stop()
    check("result ごとに応答を返す", replies == ["echo:こんにちは\n改行入り", ""], repr(replies))
    check("stop() では on_exit を呼ばない", exits == [], repr(exits))
    proc.stop()
    check("stop() は二度呼べる", True)


def test_exit_notified() -> None:
    done = threading.Event()
    exits: list[int | None] = []

    def on_exit(code: int | None) -> None:
        exits.append(code)
        done.set()

    proc = ClaudeTalkProcess([sys.executable, _fake_script(), "die"], tempfile.gettempdir(),
                             lambda _t: None, on_exit)
    proc.start()
    done.wait(10)
    check("予期しない終了を終了コードつきで通知", exits == [3], repr(exits))


def test_missing_binary() -> None:
    proc = ClaudeTalkProcess(["/nonexistent/claude"], tempfile.gettempdir(), lambda _t: None, lambda _c: None)
    try:
        proc.start()
        check("存在しないコマンドは OSError", False)
    except OSError:
        check("存在しないコマンドは OSError", True)


def test_argv() -> None:
    argv = build_claude_argv({"claude_cli_path": "claude", "talk_allowed_tools": "Read,Grep",
                              "talk_model": "sonnet"}, "PROMPT")
    check("stream-json で起動", argv[:6] == ["claude", "-p", "--input-format", "stream-json",
                                             "--output-format", "stream-json"], repr(argv))
    check("ツールを絞って許可", argv[argv.index("--tools") + 1] == "Read,Grep"
          and argv[argv.index("--allowedTools") + 1] == "Read,Grep")
    check("ユーザー設定を読まない", argv[argv.index("--setting-sources") + 1] == "" and "--strict-mcp-config" in argv)
    check("system prompt とモデル", argv[argv.index("--append-system-prompt") + 1] == "PROMPT"
          and argv[argv.index("--model") + 1] == "sonnet")
    bare = build_claude_argv({"claude_cli_path": "claude", "talk_allowed_tools": "", "talk_model": ""}, "P")
    check("ツールなしなら --allowedTools を付けない",
          bare[bare.index("--tools") + 1] == "" and "--allowedTools" not in bare and "--model" not in bare)


if __name__ == "__main__":
    test_roundtrip()
    test_exit_notified()
    test_missing_binary()
    test_argv()
    sys.exit(0 if all(results) else 1)
