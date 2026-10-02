"""会話言語の決定と system prompt の組み立ての検証

実行: uv run python tests/test_talk_prompt.py
"""
from __future__ import annotations
import sys

from shadow_clerk._daemon_talk_prompt import (
    build_system_prompt, requested_language, resolve_talk_language)
from shadow_clerk.domain import Language, TalkPersona

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _JaOnly:
    LANGUAGES = (Language.JA,)
    DEFAULT_LANGUAGE = Language.JA


class _JaEn:
    LANGUAGES = (Language.JA, Language.EN)
    DEFAULT_LANGUAGE = Language.EN


def test_language() -> None:
    check("対応言語はそのまま", resolve_talk_language("en", _JaEn()) == Language.EN)
    check("非対応はバックエンドの既定", resolve_talk_language("en", _JaOnly()) == Language.JA)
    check("未知のコードも既定", resolve_talk_language("xx", _JaEn()) == Language.EN)
    check("空も既定", resolve_talk_language("", _JaOnly()) == Language.JA)
    check("talk_language を優先",
          requested_language({"talk_language": "ja", "translate_language": "en"}) == "ja")
    check("空なら translate_language",
          requested_language({"talk_language": "", "translate_language": "en"}) == "en")


def test_prompt() -> None:
    p = build_system_prompt(Language.JA, TalkPersona("devil", "反対の立場から話す"), "新機能の設計")
    base_end = p.index("## Persona")
    check("同梱プロンプトが先頭", p.startswith("あなたは") and base_end > 0, p[:20])
    check("persona → topic の順", base_end < p.index("反対の立場") < p.index("## Topic") < p.index("新機能の設計"))
    bare = build_system_prompt(Language.JA, None, "")
    check("persona も topic も無ければ節を出さない", "## Persona" not in bare and "## Topic" not in bare)


if __name__ == "__main__":
    test_language()
    test_prompt()
    sys.exit(0 if all(results) else 1)
