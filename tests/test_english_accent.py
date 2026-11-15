"""練習する英語（EnglishAccent）と、英音の期待列（expected_ipa の accent）の検証

実行: uv run python tests/test_english_accent.py
"""
from __future__ import annotations

import sys

from shadow_clerk._daemon_pronounce_ipa import expected_ipa, has_espeak
from shadow_clerk.domain import EnglishAccent, Language

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_from_config() -> None:
    check("キーが無ければ米音", EnglishAccent.from_config({}) is EnglishAccent.AMERICAN)
    check("british を読む", EnglishAccent.from_config({"english_accent": "british"}) is EnglishAccent.BRITISH)
    for bad in ("British", "", None, 1, "scottish", [], {}):
        check(f"不正な値 {bad!r} は米音", EnglishAccent.from_config({"english_accent": bad}) is EnglishAccent.AMERICAN)
    check("espeak と BCP 47 の言語コード",
          (EnglishAccent.BRITISH.espeak, EnglishAccent.BRITISH.bcp47, EnglishAccent.AMERICAN.espeak,
           EnglishAccent.AMERICAN.bcp47) == ("en-gb", "en-GB", "en-us", "en-US"))


def test_gb_expected() -> None:
    if not has_espeak():
        print("[SKIP] espeak が無いため期待列は見ない")
        return
    us, gb = EnglishAccent.AMERICAN, EnglishAccent.BRITISH

    def ipa(word: str, accent: EnglishAccent) -> tuple[str, ...]:
        return expected_ipa(word, Language.EN, accent)

    check("英音の car に r が無い", ipa("car", gb) == ("k", "O"), repr(ipa("car", gb)))
    check("米音の car は今どおり", ipa("car", us) == ("k", "O", "ɹ"), repr(ipa("car", us)))
    # 寄せの表は VCTK の調整用の話者（gate.py の TUNE_SPEAKERS）でモデルの出力を見て決めた
    check("英音の trap / bath は a のまま（モデルが英音の話者で a を出す）", ipa("that", gb) == ("ð", "a", "t"), repr(ipa("that", gb)))
    check("əʊ は oʊ に寄せる（モデルが英音の話者でも oʊ を出す）", ipa("go", gb) == ("ɡ", "oʊ"), repr(ipa("go", gb)))
    check("iə は i、eə は e に寄せる", (ipa("here", gb), ipa("there", gb)) == (("h", "i"), ("ð", "e")),
          repr((ipa("here", gb), ipa("there", gb))))
    check("英音の ɜː は r 性母音にしない", ipa("world", gb) == ("w", "@", "l", "d"), repr(ipa("world", gb)))
    check("語末の -y の ɪ は i に寄せる", ipa("really", gb)[-1] == "i" and ipa("city", gb) == ipa("city", us),
          repr((ipa("really", gb), ipa("city", gb))))
    check("t / d / n の後の j（new の y）は落とす。pure の j は残す",
          ipa("new", gb) == ("n", "u") and ipa("pure", gb)[:2] == ("p", "j"), repr((ipa("new", gb), ipa("pure", gb))))
    check("米音にも j がある語（menu・annual）の j は落とさない",
          "j" in ipa("menu", gb) and "j" in ipa("annual", gb), repr((ipa("menu", gb), ipa("annual", gb))))
    check("英音の water は曖昧母音で終わる", ipa("water", gb)[-1] == "@", repr(ipa("water", gb)))
    check("違わない語は同じ", ipa("think", gb) == ipa("think", us))
    check("accent を省けば米音", expected_ipa("car", Language.EN) == ipa("car", us))


if __name__ == "__main__":
    test_from_config()
    test_gb_expected()
    sys.exit(0 if all(results) else 1)
