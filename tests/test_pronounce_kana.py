"""日本語の発音フィードバック（かな＝モーラ単位）の検証

実行: uv run python tests/test_pronounce_kana.py
読みの取得に sudachi が要る（pronounce extra）。無ければ該当のテストは飛ばす。
かな認識モデル（torch）は不要。偽物に差し替える。
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_pronounce_api import _FakeRecogniser, _settle, check, results  # noqa: E402
from shadow_clerk import _daemon_pronounce_kana as kana  # noqa: E402
from shadow_clerk._daemon_pronounce import ArmError, PronounceDriver, align  # noqa: E402
from shadow_clerk._daemon_pronounce_ipa import G2PError  # noqa: E402
from shadow_clerk.domain import OpKind, PronunciationTask  # noqa: E402

S = "し" + kana.DEVOICED   # 無声化しうる し


def test_morae() -> None:
    for src, want in (("きょう", ("きょ", "ー")), ("がっこう", ("が", "っ", "こ", "ー")),
                      ("おばあさん", ("お", "ば", "ー", "さ", "ん")), ("れびゅー", ("れ", "びゅ", "ー")),
                      ("せんせい", ("せ", "ん", "せ", "ー")), ("キッテヲ", ("き", "っ", "て", "お")),
                      ("おばさん", ("お", "ば", "さ", "ん"))):
        check(f"モーラ: {src}", kana.morae(src) == want, repr(kana.morae(src)))
    check("認識結果の区切りや空白は捨てる",
          kana.actual_morae("きょうは | いい てんき") == ("きょ", "ー", "は", "い", "ー", "て", "ん", "き"),
          repr(kana.actual_morae("きょうは | いい てんき")))


def test_devoicing() -> None:
    check("無声子音の前の し に印", kana.mark_devoicing(("ま", "し", "た")) == ("ま", S, "た"))
    check("文末の す に印", kana.mark_devoicing(("で", "す")) == ("で", "す" + kana.DEVOICED))
    check("有声音の前には付けない", kana.mark_devoicing(("し", "ま")) == ("し", "ま"))
    check("文中の す の後が有声なら付けない", kana.mark_devoicing(("す", "な")) == ("す", "な"))
    check("無声化した し は す と同じ音", kana.sub_cost(S, "す") == 0 and kana.sub_cost(S, "し") == 0)
    check("無声化の印が無ければ し と す は違う", kana.sub_cost("し", "す") == 1)
    check("無声化しても別の子音は違う", kana.sub_cost(S, "ち") == 1)
    check("つ/ち は無声化しても別の音（学習者の誤りを隠さない）",
          kana.sub_cost("つ" + kana.DEVOICED, "ち") == 1 and kana.sub_cost("つ" + kana.DEVOICED, "つ") == 0)
    ops = align(("ま", S, "た"), ("ま", "す", "た"), kana.sub_cost)
    check("アライメントは same にする", [op[0] for op in ops] == [OpKind.SAME] * 3, repr(ops))
    check("same でも聞こえた音は残す", ops[1] == (OpKind.SAME, S, "す"), repr(ops[1]))


def test_expected_words() -> None:
    if not kana.has_sudachi():
        print("[SKIP] sudachi が無い")
        return
    words, per_word = kana.expected_words("切手を買いに郵便局へ行きました。")
    check("動詞の後の助動詞は前の語にまとめ、格助詞は分ける",
          words == ("切手", "を", "買い", "に", "郵便局", "へ", "行きました"), repr(words))
    check("を は お、へ は表記のまま", per_word[1] == ("お",) and per_word[5] == ("へ",), repr(per_word))
    check("無声化は語をまたいで決める（切手 の き は っ の前）",
          per_word[0] == ("き" + kana.DEVOICED, "っ", "て") and per_word[6] == ("い", "き", "ま", S, "た"),
          repr(per_word))
    words, _ = kana.expected_words("おばあさんとおじさん")
    check("接頭辞・接尾辞は語にまとめる", words == ("おばあさん", "と", "おじさん"), repr(words))
    words, per_word = kana.expected_words("今日はいい天気です")
    check("名詞の後の です は分ける", words == ("今日", "は", "いい", "天気", "です"), repr(words))
    check("助詞の は は表記のまま", per_word[1] == ("は",), repr(per_word))
    check("文末の です は無声化", per_word[-1] == ("で", "す" + kana.DEVOICED), repr(per_word))
    try:
        kana.expected_words("Zxqv")
        check("かなで読めない語は G2PError", False)
    except G2PError:
        check("かなで読めない語は G2PError", True)


class _FakeKana(_FakeRecogniser):
    """かな認識の偽物。pcm に渡した文字列をそのまま復号結果として返す"""

    def decode(self, pcm) -> str:
        return str(pcm)


def _driver() -> tuple[PronounceDriver, list]:
    made: list = []

    def factory(lang):
        made.append(lang)
        return _FakeKana()
    drv = PronounceDriver(recogniser_factory=factory)
    drv._unavailable = lambda: None                  # type: ignore[assignment]
    return drv, made


def test_driver_japanese() -> None:
    if not kana.has_sudachi():
        print("[SKIP] sudachi が無い")
        return
    drv, made = _driver()
    out = drv.arm(PronunciationTask.parse({
        "text": "わたしは切手といいました", "lang": "ja",
        "focus": [{"word": "切手", "phoneme": "っ"}]}))
    check("日本語でアームできる", out["status"] == "ok", repr(out))
    check("期待列はモーラ", {"word": "切手", "ipa": ["き" + kana.DEVOICED, "っ", "て"]} in out["expected"], repr(out["expected"]))
    _settle(drv)
    drv.offer("わたしは きて といいますた", "2026-11-03 10:00:00", "わたしは切手といいました")
    _settle(drv)
    attempts = drv.snapshot()["attempts"]
    check("解析結果が出る", len(attempts) == 1, repr(attempts))
    if not attempts:
        return
    by_word = {w["word"]: w for w in attempts[0]["words"]}
    kitte = by_word["切手"]["ops"]
    check("促音の脱落が del で出て、focus が付く",
          {"kind": "del", "expected": "っ", "actual": "", "focus": True} in kitte, repr(kitte))
    said = [op["kind"] for op in by_word["いいました"]["ops"]]
    check("無声化した し を す と聞いても same", said == ["same"] * len(said), repr(by_word["いいました"]))
    check("日本語のモデルを作った", made and made[-1] == "ja", repr(made))


def test_driver_switches_model() -> None:
    if not kana.has_sudachi():
        print("[SKIP] sudachi が無い")
        return
    drv, made = _driver()
    drv._expected_of = lambda word, lang: ("l", "aɪ", "t")   # type: ignore[assignment]
    drv.arm(PronunciationTask.parse({"text": "light", "lang": "en"}))
    _settle(drv)
    first = drv._recogniser
    drv.arm(PronunciationTask.parse({"text": "切手", "lang": "ja"}))
    _settle(drv)
    check("言語が変わればモデルを作り直す", made == ["en", "ja"], repr(made))
    check("前のモデルは解放する", first is not drv._recogniser and not first.loaded)


def test_driver_rejects() -> None:
    if not kana.has_sudachi():
        print("[SKIP] sudachi が無い")
        return
    drv, _ = _driver()
    for text, label in (("Zxqv です", "かなで読めない語"), ("りんごを3つ", "数字"), ("。、", "語が無い")):
        try:
            drv.arm(PronunciationTask.parse({"text": text, "lang": "ja"}))
            check(f"拒否: {label}", False)
        except ArmError:
            check(f"拒否: {label}", True)


def test_free_japanese() -> None:
    if not kana.has_sudachi():
        print("[SKIP] sudachi が無い")
        return
    drv, _ = _driver()
    drv.arm(PronunciationTask.parse({"free": True, "lang": "ja"}))
    _settle(drv)
    drv.offer("とり", "2026-11-03 10:00:01", "通り")
    _settle(drv)
    attempts = drv.snapshot()["attempts"]
    ops = attempts[0]["words"][0]["ops"] if attempts else []
    check("自由発話は文字起こしの読みと比べる（長音の脱落）",
          {"kind": "del", "expected": "ー", "actual": "", "focus": False} in ops, repr(attempts))


if __name__ == "__main__":
    test_morae()
    test_devoicing()
    test_expected_words()
    test_driver_japanese()
    test_driver_switches_model()
    test_driver_rejects()
    test_free_japanese()
    print(f"\n=== {sum(results)}/{len(results)} PASS ===")
    sys.exit(0 if all(results) else 1)
