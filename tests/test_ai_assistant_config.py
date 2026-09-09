"""AiAssistantConfig の検証

実行: uv run python tests/test_ai_assistant_config.py
"""
from __future__ import annotations
import os
import tempfile

from shadow_clerk.domain.ai_assistant import AiAssistantConfig

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_defaults() -> None:
    c = AiAssistantConfig.from_config({})
    check("command の既定は claude", c.command == "claude", c.command)
    check("args の既定は空", c.args == (), repr(c.args))


def test_args_are_shell_split() -> None:
    c = AiAssistantConfig.from_config(
        {"ai_assistant_args": "--permission-mode 'accept edits'"})
    check("args を shlex で分解する",
          c.args == ("--permission-mode", "accept edits"), repr(c.args))


def test_argv() -> None:
    c = AiAssistantConfig.from_config(
        {"ai_assistant_command": "codex", "ai_assistant_args": "-q"})
    check("argv は command + args", c.argv() == ["codex", "-q"], repr(c.argv()))


def test_init_prompt_placeholders() -> None:
    c = AiAssistantConfig.from_config(
        {"ai_assistant_init_prompt": "/mtg {transcript} for {meeting}"})
    out = c.resolve_init_prompt("/tmp/t.txt", "Board_Meeting")
    check("{transcript} と {meeting} を展開する",
          out == "/mtg /tmp/t.txt for Board_Meeting", out)


def test_init_prompt_unknown_placeholder_is_literal() -> None:
    # 設定は人が手で書くので、未知の {} で例外にせず literal のまま残す
    c = AiAssistantConfig.from_config({"ai_assistant_init_prompt": "a {nope} b"})
    check("未知のプレースホルダは literal", c.resolve_init_prompt("t", "m") == "a {nope} b",
          c.resolve_init_prompt("t", "m"))


def test_workdir_expanduser() -> None:
    c = AiAssistantConfig.from_config({"ai_assistant_workdir": "~"})
    check("~ を展開する", c.resolve_workdir() == os.path.expanduser("~"),
          c.resolve_workdir())


def test_workdir_override_wins() -> None:
    d = tempfile.mkdtemp()
    c = AiAssistantConfig.from_config({"ai_assistant_workdir": "~"})
    check("override が優先される", c.resolve_workdir(d) == d, c.resolve_workdir(d))


def test_workdir_missing_falls_back() -> None:
    c = AiAssistantConfig.from_config({"ai_assistant_workdir": ""})
    check("未設定ならホーム", c.resolve_workdir() == os.path.expanduser("~"),
          c.resolve_workdir())
    c2 = AiAssistantConfig.from_config({"ai_assistant_workdir": "/nonexistent/xyz"})
    check("存在しないディレクトリはホームに落とす",
          c2.resolve_workdir() == os.path.expanduser("~"), c2.resolve_workdir())


def test_init_prompt_no_cross_contamination_meeting_in_transcript() -> None:
    # transcript のパスに {meeting} という文字列が含まれていても
    # {meeting} プレースホルダが二度置換されない
    c = AiAssistantConfig.from_config(
        {"ai_assistant_init_prompt": "read {transcript} about {meeting}"})
    out = c.resolve_init_prompt("/data/transcript-202609071200@{meeting}.txt", "REAL_MEETING")
    check("transcript のパスに {meeting} が含まれていても壊れない",
          out == "read /data/transcript-202609071200@{meeting}.txt about REAL_MEETING", out)


def test_init_prompt_no_cross_contamination_transcript_in_meeting() -> None:
    # meeting の値に {transcript} という文字列が含まれていても壊れない
    c = AiAssistantConfig.from_config(
        {"ai_assistant_init_prompt": "read {transcript} for {meeting}"})
    out = c.resolve_init_prompt("/data/t.txt", "{transcript}")
    check("meeting の値に {transcript} が含まれていても壊れない",
          out == "read /data/t.txt for {transcript}", out)


def test_init_prompt_language() -> None:
    """出力言語を {lang} でスキルに渡せること"""
    cfg = AiAssistantConfig(command="claude", args=(), workdir="",
                            init_prompt="/mtg {transcript} {lang}")
    check("{lang} が翻訳先言語に展開される",
          cfg.resolve_init_prompt("/d/t.txt", "MTG", "ja") == "/mtg /d/t.txt ja")
    check("言語が空でも壊れない",
          cfg.resolve_init_prompt("/d/t.txt", "MTG") == "/mtg /d/t.txt ")

    plain = AiAssistantConfig(command="claude", args=(), workdir="",
                              init_prompt="/mtg {transcript}")
    check("{lang} を書いていないプロンプトは変わらない",
          plain.resolve_init_prompt("/d/t.txt", "MTG", "ja") == "/mtg /d/t.txt")

    only = AiAssistantConfig(command="claude", args=(), workdir="",
                             init_prompt="/mtg {lang}")
    check("差し込んだ値の中の {transcript} は再展開しない",
          only.resolve_init_prompt("/d/t.txt", "MTG", "{transcript}") == "/mtg {transcript}")


def main() -> int:
    test_defaults()
    test_args_are_shell_split()
    test_argv()
    test_init_prompt_placeholders()
    test_init_prompt_unknown_placeholder_is_literal()
    test_workdir_expanduser()
    test_workdir_override_wins()
    test_workdir_missing_falls_back()
    test_init_prompt_no_cross_contamination_meeting_in_transcript()
    test_init_prompt_no_cross_contamination_transcript_in_meeting()
    test_init_prompt_language()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
