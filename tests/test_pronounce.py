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
from shadow_clerk._daemon_pronounce_ipa import (  # noqa: E402
    G2PError, PhonemeRecogniser, expected_ipa, has_espeak, has_torch, normalise, split_words,
)
from shadow_clerk._daemon_pronounce import CONSONANTS, VOWELS, align, compare, is_vowel  # noqa: E402
from pronounce_fixtures import (  # noqa: E402
    CARRIER_ACTUAL, CARRIER_EXPECTED, CARRIER_WORDS, GLASS_EXPECTED, GLASS_TAKES,
    LIGHT_EXPECTED, LIGHT_TAKES, MODEL_INVENTORY,
)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def _raises(fn, arg, exc: type[BaseException]) -> bool:
    try:
        fn(arg)
    except exc:
        return True
    except Exception:
        return False
    return False


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


def test_class_table_covers_model_output() -> None:
    # 表に無い記号は子音に倒れて WARNING が出る。スパイクで出た記号は全部引けること
    unknown = MODEL_INVENTORY - VOWELS - CONSONANTS
    check("スパイクの実出力が音素クラス表で引ける", not unknown, str(sorted(unknown)))
    check("母音表と子音表が重なっていない", not (VOWELS & CONSONANTS),
          str(sorted(VOWELS & CONSONANTS)))
    check("r 性母音クラスは母音", is_vowel("R"))
    check("わたり音は子音", not is_vowel("j") and not is_vowel("w"))
    check("二重母音は母音", is_vowel("aɪ"))
    check("既知の子音では警告を出さない", not is_vowel("s") and not is_vowel("θ"))
    check("どちらにも無い記号は子音として扱う", not is_vowel("ǁ"))


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


def test_split_words() -> None:
    check("空白で割り、前後の句読点を落とす",
          split_words("Turn right at the light.") == ("Turn", "right", "at", "the", "light"),
          repr(split_words("Turn right at the light.")))
    check("語中のアポストロフィは残す", split_words("It's fine.") == ("It's", "fine"),
          repr(split_words("It's fine.")))
    check("語中のハイフンは残す", split_words("A well-known fact.") == ("A", "well-known", "fact"))
    check("曲がったアポストロフィを直の字体に畳む",
          split_words("It’s fine.") == ("It's", "fine"),
          repr(split_words("It’s fine.")))
    check("引用符・括弧を落とす", split_words('He said "right" (loudly).') ==
          ("He", "said", "right", "loudly"), repr(split_words('He said "right" (loudly).')))
    check("曲がった単引用符の囲みを落とす",
          split_words("‘hello’ world") == ("hello", "world"),
          repr(split_words("‘hello’ world")))
    check("直の単引用符の囲みも落とす",
          split_words("'hello' world") == ("hello", "world"),
          repr(split_words("'hello' world")))
    check("語中のアポストロフィは残る",
          split_words("It's fine.") == ("It's", "fine"), repr(split_words("It's fine.")))
    check("曲がった二重引用符の囲みを落とす",
          split_words("He said “hi”.") == ("He", "said", "hi"),
          repr(split_words("He said “hi”.")))
    check("原形のまま返す（小文字化しない）", split_words("Turn")[0] == "Turn")


def test_compare_attributes_insertion() -> None:
    # "Say glass again." の実測1本。+@ は ɡ の直後なので glass に付く（Say でも again でもない）
    per_word = (CARRIER_EXPECTED[0:2], CARRIER_EXPECTED[2:6], CARRIER_EXPECTED[6:10])
    comps = compare(CARRIER_WORDS, per_word, CARRIER_ACTUAL, ())
    by_word = {c.word: c for c in comps}
    check("語の数だけ WordComparison が返る", len(comps) == 3, repr([c.word for c in comps]))
    glass_ins = [op for op in by_word["glass"].ops if op.kind is OpKind.INS]
    check("挿入された @ は glass に付く",
          [op.actual for op in glass_ins] == ["@"], repr([op.to_json() for op in glass_ins]))
    check("Say に挿入は付かない", not [op for op in by_word["say"].ops if op.kind is OpKind.INS])
    check("again に挿入は付かない", not [op for op in by_word["again"].ops if op.kind is OpKind.INS])
    check("glass の実測列が切り出される",
          by_word["glass"].actual == ("ɡ", "@", "ɹ", "a", "s"), repr(by_word["glass"].actual))
    check("again は無傷", all(op.kind is OpKind.SAME for op in by_word["again"].ops),
          repr([op.to_json() for op in by_word["again"].ops]))


def test_compare_marks_focus() -> None:
    per_word = (LIGHT_EXPECTED,)
    comps = compare(("light",), per_word, LIGHT_TAKES[1], (FocusPhoneme("light", "l"),))
    ops = comps[0].ops
    check("focus の音素に当たる op だけ focus=True",
          [op.focus for op in ops] == [True, False, False], repr([op.to_json() for op in ops]))
    # 語内に同じ音素が2回あるとき、phoneme_index で何番目かを選ぶ
    comps = compare(("little",), (("l", "@", "t", "l"),), ("l", "@", "t", "r"),
                    (FocusPhoneme("little", "l", phoneme_index=1),))
    marked = [i for i, op in enumerate(comps[0].ops) if op.focus]
    check("phoneme_index で2つめの l を選ぶ", marked == [3], repr(marked))
    # 課題文に同じ語が2回出るとき、index で何番目かを選ぶ
    comps = compare(("the", "cat", "the", "mat"),
                    (("ð", "@"), ("k", "A", "t"), ("ð", "@"), ("m", "A", "t")),
                    ("ð", "@", "k", "A", "t", "z", "@", "m", "A", "t"),
                    (FocusPhoneme("the", "ð", index=1),))
    focused = [(wi, i) for wi, c in enumerate(comps) for i, op in enumerate(c.ops) if op.focus]
    check("index で2つめの the を選ぶ（語位置2の先頭 op）", focused == [(2, 0)], repr(focused))
    check("同じ語が2回出ても ops が語ごとに分かれる",
          [c.word for c in comps] == ["the", "cat", "the", "mat"]
          and [len(c.ops) for c in comps] == [2, 3, 2, 3],
          repr([(c.word, len(c.ops)) for c in comps]))
    check("focus が空なら全部 False",
          not any(op.focus for c in compare(("light",), (LIGHT_EXPECTED,), LIGHT_TAKES[1], ())
                  for op in c.ops))
    # 課題文が曲がったアポストロフィ、focus が直の字体でも一致すること
    comps = compare(split_words("It’s fine."), (("ɪ", "t", "s"), ("f", "aɪ", "n")),
                    ("ɪ", "t", "s", "f", "aɪ", "n"), (FocusPhoneme("it's", "t"),))
    check("引用符の字体が違っても focus が当たる",
          [(wi, i) for wi, c in enumerate(comps) for i, op in enumerate(c.ops) if op.focus] == [(0, 1)],
          repr([op.to_json() for c in comps for op in c.ops]))


def test_compare_word_boundary_duplicate() -> None:
    # 正規化は期待側を語ごとに、実測側を発話全体に掛ける。圧縮の範囲が違うので
    # 語境界で同じ記号が隣り合うと期待側に s が2つ残り、del が1つ出る（設計書 §4.1-4）。
    # focus に入らない限り触れないフロア誤差として許容する
    comps = compare(("glass", "sits"), (("ɡ", "l", "A", "s"), ("s", "@", "t", "s")),
                    ("ɡ", "l", "A", "s", "@", "t", "s"), ())
    by_word = {c.word: c for c in comps}
    dels = [(c.word, op.expected) for c in comps for op in c.ops if op.kind is OpKind.DEL]
    check("語境界の重複で del が1つだけ出る", dels == [("sits", "s")], repr(dels))
    check("glass は無傷", all(op.kind is OpKind.SAME for op in by_word["glass"].ops),
          repr([op.to_json() for op in by_word["glass"].ops]))
    check("語の帰属が壊れない", by_word["sits"].actual == ("@", "t", "s"),
          repr(by_word["sits"].actual))


def test_compare_empty_actual() -> None:
    # Review Focus 1: 無音セグメント。例外を出さず actual が空の WordComparison を返す
    comps = compare(("light",), (LIGHT_EXPECTED,), (), ())
    check("実測が空でも落ちない", len(comps) == 1 and comps[0].actual == (), repr(comps))
    check("全部 del になる", all(op.kind is OpKind.DEL for op in comps[0].ops))


def test_g2p() -> None:
    if not has_espeak():
        print("[SKIP] G2P のテスト（phonemizer-fork が無い）")
        return
    ipa = expected_ipa("light", Language.EN)
    check("light の期待IPA", ipa == ("l", "aɪ", "t"), repr(ipa))
    check("right の期待IPA", expected_ipa("right", Language.EN) == ("ɹ", "aɪ", "t"),
          repr(expected_ipa("right", Language.EN)))
    # ハイフン語は espeak が融合して1語にする（実測）。語区切りは末尾にしか出ないので通る
    fused = expected_ipa("well-known", Language.EN)
    check("ハイフン語は1語として通る", bool(fused) and "|" not in fused, repr(fused))
    # 語区切りの検査が効くのは、1語が複数語に展開される場合（数字など）
    try:
        expected_ipa("123", Language.EN)
        check("複数語に展開される語を拒否する", False)
    except G2PError:
        check("複数語に展開される語を拒否する", True)
    # v1 は英語のみ。検証していない言語で confident に聞こえる助言を出さない（設計書 §6.3）
    for lang in (Language.JA, Language.DE, Language.FR):
        try:
            expected_ipa("test", lang)
            check(f"未対応の言語を拒否する（{lang.value}）", False)
        except G2PError:
            check(f"未対応の言語を拒否する（{lang.value}）", True)


def test_recogniser_is_lazy() -> None:
    # daemon 起動時に torch を import しない。クラスを作るだけでは何も読み込まない
    rec = PhonemeRecogniser("facebook/wav2vec2-xlsr-53-espeak-cv-ft", "cpu", 0)
    check("作っただけでは未ロード", not rec.loaded)
    check("torch を import していない", "torch" not in sys.modules)
    check("has_torch は import せずに答える", isinstance(has_torch(), bool))
    check("未ロードで actual_ipa を呼ぶと RuntimeError", _raises(rec.actual_ipa, None, RuntimeError))
    rec.unload()
    check("未ロードで unload しても落ちない", not rec.loaded)


if __name__ == "__main__":
    test_recogniser_is_lazy()  # import 順に依存するので必ず先頭
    test_task_parse()
    test_json_shape()
    test_normalise_keeps_contrasts()
    test_normalise_order()
    test_normalise_known_limit()
    test_class_table_covers_model_output()
    test_align_shows_epenthesis()
    test_align_tie_break()
    test_align_no_cross_class_sub()
    test_align_middle_articulation()
    test_align_empty_actual()
    test_split_words()
    test_compare_attributes_insertion()
    test_compare_marks_focus()
    test_compare_word_boundary_duplicate()
    test_compare_empty_actual()
    test_g2p()
    sys.exit(0 if all(results) else 1)
