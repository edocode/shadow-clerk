"""発音フィードバックの正規化・アライメント・語への帰属の検証

実行: uv run python tests/test_pronounce.py
モデル（torch）は不要。G2P を実際に呼ぶ項目は phonemizer-fork が無ければスキップする。
"""
from __future__ import annotations
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SHADOW_CLERK_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "shadow-clerk-pronounce-test"))
os.makedirs(os.environ["SHADOW_CLERK_DATA_DIR"], exist_ok=True)

from shadow_clerk.domain import Language  # noqa: E402
from shadow_clerk.domain.pronunciation import (  # noqa: E402
    FocusPhoneme, OpKind, PhonemeOp, PronounceState, PronunciationTask, WordComparison,
)
from shadow_clerk._daemon_pronounce_ipa import normalise  # noqa: E402
from shadow_clerk._daemon_pronounce import VOWELS, align, is_vowel  # noqa: E402
from pronounce_fixtures import (  # noqa: E402
    CARRIER_ACTUAL, CARRIER_EXPECTED, GLASS_EXPECTED, GLASS_TAKES,
    LIGHT_EXPECTED, LIGHT_TAKES, MODEL_INVENTORY,
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


def test_normalise_keeps_contrasts() -> None:
    # 学習者にとって意味のある対立は残す（設計書 §6.1）
    for a, b, why in (("ɹ", "l", "R と L"), ("iː", "ɪ", "長い i と短い i"),
                      ("θ", "s", "th と s"), ("b", "v", "b と v")):
        check(f"{why} をマージしない", normalise([a]) != normalise([b]),
              f"{normalise([a])} vs {normalise([b])}")
    # 非ネイティブ専用の記号。ここに信号が乗っているのでマージしてはいけない（制約3）
    check("r を ɹ にマージしない", normalise(["r"]) != normalise(["ɹ"]))
    check("a を æ にマージしない", normalise(["a"]) != normalise(["æ"]))
    check("e を他にマージしない", normalise(["e"]) == ("e",))
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


def _render(ops: tuple) -> str:
    """ops を人が読める1行にする。テストの失敗時に何が起きたか分かるように"""
    return " ".join({OpKind.SAME: f"{e}={a}", OpKind.SUB: f"{e}→{a}",
                     OpKind.DEL: f"-{e}", OpKind.INS: f"+{a}"}[k] for k, e, a in ops)


# スパイクで母音として観測した記号。実装の表のコピーでは回帰にならないので直書きする
_SPIKE_VOWELS = {"@", "R", "O", "A", "a", "e", "ɛ", "i", "u", "ʊ", "ʉ", "aɪ", "aʊ", "eɪ", "oʊ"}


def _looks_vowel(p: str) -> bool:
    return p in _SPIKE_VOWELS


def test_vowel_table_covers_model_output() -> None:
    # 表に無い記号は子音に倒れて WARNING が出る。スパイクで出た記号は全部引けること
    unknown = {p for p in MODEL_INVENTORY if p not in VOWELS and _looks_vowel(p)}
    check("スパイクの実出力が母音表で引ける", not unknown, str(sorted(unknown)))
    check("r 性母音クラスは母音", is_vowel("R"))
    check("わたり音は子音", not is_vowel("j") and not is_vowel("w"))
    check("声門閉鎖は子音", not is_vowel("ʔ"))
    check("二重母音は母音", is_vowel("aɪ"))


def test_align_shows_epenthesis() -> None:
    # 日本語話者の典型。ɡ と l の間に母音が入ったことが ins として出ること
    ops = align(GLASS_EXPECTED, GLASS_TAKES[0])     # ɡ u ɹ a f s
    check("母音挿入が ins として出る", _render(ops) == "ɡ=ɡ +u l→ɹ A→a +f s=s", _render(ops))
    ops = align(GLASS_EXPECTED, GLASS_TAKES[4])     # ɡ u l a θ
    check("l が残っていれば same になる", _render(ops) == "ɡ=ɡ +u l=l A→a s→θ", _render(ops))
    ops = align(GLASS_EXPECTED, GLASS_TAKES[3])     # u l a s
    check("語頭の脱落は del", _render(ops) == "-ɡ +u l=l A→a s=s", _render(ops))


def test_align_tie_break() -> None:
    # クラス制約を入れても同点は残る。same < sub < del < ins の辞書順最小で決める
    ops = align(GLASS_EXPECTED, GLASS_TAKES[6])     # ɡ @ d r a θ
    check("同コストは sub を ins より先に置く",
          _render(ops) == "ɡ=ɡ +@ l→d +r A→a s→θ", _render(ops))
    check("同じ入力で何度やっても同じ結果", align(GLASS_EXPECTED, GLASS_TAKES[6]) == ops)


def test_align_no_cross_class_sub() -> None:
    # 母音↔子音の置換は演算として持たない。必ず del + ins に割れる
    for take in GLASS_TAKES + LIGHT_TAKES:
        expected = GLASS_EXPECTED if take in GLASS_TAKES else LIGHT_EXPECTED
        bad = [(e, a) for k, e, a in align(expected, take)
               if k is OpKind.SUB and is_vowel(e) != is_vowel(a)]
        check(f"クラスをまたぐ sub が出ない（{' '.join(take)}）", not bad, str(bad))


def test_align_middle_articulation() -> None:
    # タップと l が両方出るテイク。素朴なラベルでは表現できないが、op 列なら素直に読める
    ops = align(LIGHT_EXPECTED, LIGHT_TAKES[0])     # r l aɪ
    check("r と l が両方見える", _render(ops) == "+r l=l aɪ=aɪ -t", _render(ops))


def test_align_empty_actual() -> None:
    # Review Focus 1: 無音・ノイズだけのセグメント。例外を出さず全 del になること
    ops = align(GLASS_EXPECTED, ())
    check("実測が空なら全部 del",
          [k for k, _, _ in ops] == [OpKind.DEL] * 4, _render(ops))
    check("期待が空なら全部 ins",
          [k for k, _, _ in align((), ("a", "b"))] == [OpKind.INS] * 2)
    check("両方空なら op も空", align((), ()) == ())


if __name__ == "__main__":
    test_task_parse()
    test_json_shape()
    test_normalise_keeps_contrasts()
    test_normalise_order()
    test_normalise_known_limit()
    test_vowel_table_covers_model_output()
    test_align_shows_epenthesis()
    test_align_tie_break()
    test_align_no_cross_class_sub()
    test_align_middle_articulation()
    test_align_empty_actual()
    sys.exit(0 if all(results) else 1)
