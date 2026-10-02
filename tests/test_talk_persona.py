"""TalkPersona の検証

実行: uv run python tests/test_talk_persona.py
"""
from __future__ import annotations
import sys

from shadow_clerk.domain import Speaker, TalkPersona, TranscriptLine

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_RAW = {"devil": "あえて反対の立場から突っ込む", "coach": "  質問で考えを引き出す  ",
        "empty": "   ", 3: "数字の名前", "bad": 42}


def test_from_config() -> None:
    ps = TalkPersona.all_from_config(_RAW)
    check("文字列の記述だけを拾う", set(ps) == {"devil", "coach", "3"}, repr(sorted(ps)))
    check("記述の前後空白を落とす", ps["coach"].instructions == "質問で考えを引き出す")
    check("dict 以外は空", TalkPersona.all_from_config(["x"]) == {})


def test_resolve() -> None:
    ps = TalkPersona.all_from_config(_RAW)
    check("指定なしは既定", TalkPersona.resolve(ps, None, "coach") == ps["coach"])
    check("空文字は persona なし", TalkPersona.resolve(ps, "", "coach") is None)
    check("名前指定", TalkPersona.resolve(ps, "devil", "coach") == ps["devil"])
    check("未知の名前は既定", TalkPersona.resolve(ps, "nope", "coach") == ps["coach"])
    check("既定も無ければ None", TalkPersona.resolve(ps, None, "nope") is None)


def test_claude_speaker() -> None:
    tl = TranscriptLine.parse("[2026-10-02 10:00:00] [Claude] こんにちは")
    check("[Claude] 行を Claude として読む", tl is not None and tl.speaker == Speaker.CLAUDE, repr(tl))


if __name__ == "__main__":
    test_from_config()
    test_resolve()
    test_claude_speaker()
    sys.exit(0 if all(results) else 1)
