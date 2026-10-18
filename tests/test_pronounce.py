"""発音フィードバックの正規化・アライメント・語への帰属の検証

実行: uv run python tests/test_pronounce.py
モデル（torch）は不要。G2P を実際に呼ぶ項目は phonemizer-fork が無ければスキップする。
"""
from __future__ import annotations
import os
import sys
import tempfile

os.environ.setdefault("SHADOW_CLERK_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "shadow-clerk-pronounce-test"))
os.makedirs(os.environ["SHADOW_CLERK_DATA_DIR"], exist_ok=True)

from shadow_clerk.domain import Language  # noqa: E402
from shadow_clerk.domain.pronunciation import (  # noqa: E402
    FocusPhoneme, OpKind, PhonemeOp, PronounceState, PronunciationTask, WordComparison,
)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_task_parse() -> None:
    task = PronunciationTask.parse(
        {"text": "Turn right at the light.", "lang": "en",
         "focus": [{"word": "light", "phoneme": "l"}, {"word": "right", "phoneme": "ɹ"}]})
    check("課題文を読む", task.text == "Turn right at the light.")
    check("言語を読む", task.language is Language.EN)
    check("focus を読む", task.focus == (FocusPhoneme("light", "l"), FocusPhoneme("right", "ɹ")))
    check("index の既定は 0", task.focus[0].index == 0 and task.focus[0].phoneme_index == 0)
    task = PronunciationTask.parse(
        {"text": "The cat sat on the mat.", "lang": "en",
         "focus": [{"word": "the", "phoneme": "ð", "index": 1}]})
    check("index を読む", task.focus[0].index == 1)
    check("focus は空でもよい",
          PronunciationTask.parse({"text": "Hello.", "lang": "en", "focus": []}).focus == ())
    for bad, why in (
        ("not an object", "dict でない"),
        ({"text": "", "lang": "en", "focus": []}, "課題文が空"),
        ({"text": "Hi.", "lang": "xx", "focus": []}, "知らない言語"),
        ({"text": "Hi.", "lang": "en", "focus": [{"word": "hi"}]}, "phoneme が無い"),
        ({"text": "Hi.", "lang": "en", "focus": [{"word": "hi", "phoneme": "h", "index": -1}]}, "index が負"),
    ):
        try:
            PronunciationTask.parse(bad)
            check(f"不正な body を弾く（{why}）", False)
        except ValueError:
            check(f"不正な body を弾く（{why}）", True)


def test_json_shape() -> None:
    comp = WordComparison(
        "light", ("l", "aɪ", "t"), ("r", "aɪ"),
        (PhonemeOp(OpKind.SUB, "l", "r", True),
         PhonemeOp(OpKind.SAME, "aɪ", "aɪ", False),
         PhonemeOp(OpKind.DEL, "t", "", False)))
    data = comp.to_json()
    check("語の JSON の形",
          data == {"word": "light", "expected": ["l", "aɪ", "t"], "actual": ["r", "aɪ"],
                   "ops": [{"kind": "sub", "expected": "l", "actual": "r", "focus": True},
                           {"kind": "same", "expected": "aɪ", "actual": "aɪ", "focus": False},
                           {"kind": "del", "expected": "t", "actual": "", "focus": False}]},
          repr(data))
    check("判定・スコアを含まない",
          not ({"distance", "score", "ok", "passed", "inserted"} & set(data)), repr(sorted(data)))
    check("state は Enum", PronounceState.ARMED.value == "armed")


if __name__ == "__main__":
    test_task_parse()
    test_json_shape()
    sys.exit(0 if all(results) else 1)
