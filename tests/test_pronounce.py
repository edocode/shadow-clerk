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
from shadow_clerk._daemon_pronounce_ipa import normalise  # noqa: E402

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


def test_normalise_keeps_contrasts() -> None:
    # 学習者にとって意味のある対立は残す（設計書 §6.1）
    for a, b, why in (("ɹ", "l", "R と L"), ("iː", "ɪ", "長い i と短い i"),
                      ("θ", "s", "th と s"), ("b", "v", "b と v")):
        check(f"{why} をマージしない", normalise([a]) != normalise([b]),
              f"{normalise([a])} vs {normalise([b])}")
    # 非ネイティブ専用の記号。ここに信号が乗っているのでマージしてはいけない（制約3）
    check("r を ɹ にマージしない", normalise(["r"]) != normalise(["ɹ"]))
    check("a を æ にマージしない", normalise(["a"]) != normalise(["æ"]))
    check("ɹ を r 性母音にマージしない", normalise(["ɹ"]) != normalise(["ɚ"]))


def test_normalise_order() -> None:
    # 適用順: 分割 → 除去 → 寄せ → マージ → 圧縮。順序を変えると結果が変わる
    check("長音を先に落としてからマージする（ɜː → R）", normalise(["ɜː"]) == ("R",), repr(normalise(["ɜː"])))
    check("声調の数字を先に落とす（ɑ5 → O）", normalise(["ɑ5"]) == ("O",), repr(normalise(["ɑ5"])))
    check("ɑ も O になる", normalise(["ɑ"]) == ("O",))
    check("ASCII 異体を寄せる（ai → aɪ）", normalise(["ai5"]) == ("aɪ",), repr(normalise(["ai5"])))
    check("強勢記号を落とす", normalise(["ˈɡ"]) == ("ɡ",), repr(normalise(["ˈɡ"])))
    check("複合単位を分割する", normalise(["ɔːɹ"]) == ("O", "ɹ"), repr(normalise(["ɔːɹ"])))
    check("同一記号の連続を圧縮する", normalise(["s", "s", "ɪ", "z"]) == ("s", "@", "z"),
          repr(normalise(["s", "s", "ɪ", "z"])))


def test_normalise_known_limit() -> None:
    # 既知の制約。ɪ ʌ ə は1つのクラスに潰れるので bit と but は区別できない（設計書 §6.1）
    check("bit と but は同じになる（既知の制約）",
          normalise(["b", "ɪ", "t"]) == normalise(["b", "ʌ", "t"]))


if __name__ == "__main__":
    test_task_parse()
    test_json_shape()
    test_normalise_keeps_contrasts()
    test_normalise_order()
    test_normalise_known_limit()
    sys.exit(0 if all(results) else 1)
