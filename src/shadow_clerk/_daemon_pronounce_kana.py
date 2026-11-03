"""Shadow-clerk daemon: 日本語の発音フィードバック（かな＝モーラ単位）

日本語は IPA 音素モデルでは測れない（促音・長音を区別しない）。期待読みは sudachi の読み、
実測はかな認識モデル（_daemon_kana_hint.MODEL）の出力で、どちらもモーラ列にして突き合わせる
（improvement/pronunciation-feedback.md「日本語の再検証」）。

モーラの表記:
- 拗音は1モーラ（`きょ`）。促音 `っ`、撥音 `ん`、長音 `ー` はそれぞれ1モーラ
- 長音は書き方（おう/おお/ー）によらず `ー`。かなモデルは表記どおりに書くので発音に寄せて揃える
- 助詞の「は」「へ」は表記のまま。かなモデルも発音（わ・え）ではなく表記どおりに書く
- 無声化しうる位置のモーラには U+0325 を付ける（`し̥`）。モデルは無声化した し を す と聞く
  （「ました」が「ますた」）ので、そこだけ同じ音とみなす。ほかの i/u 違い（つ/ち など）は
  学習者の誤りそのものなので、まとめない
"""
from __future__ import annotations

import importlib.util
import threading
from functools import lru_cache
from typing import Any, Sequence

from shadow_clerk._daemon_kana_hint import VOWEL_OF, hiragana, is_kana, phonetic
from shadow_clerk._daemon_pronounce_ipa import G2PError

LONG = "ー"
DEVOICED = "̥"
_SMALL = frozenset("ゃゅょぁぃぅぇぉゎ")
_VOWELS = frozenset("あいうえお")
# 無声化しうるモーラ（無声子音 + i/u）
_DEVOICEABLE = frozenset({"き", "く", "し", "す", "ち", "つ", "ひ", "ふ", "ぴ", "ぷ", "しゅ", "ちゅ", "きゅ"})
# 無声化したときモデルが聞き違える相手。実声で確かめたものだけを置く（意味のある対立を潰さない）
_DEVOICED_HEARD_AS: dict[str, str] = {"し": "す", "す": "し"}
# 無声子音で始まるモーラの頭文字（か・さ・た・は・ぱ行）と促音
_VOICELESS_ONSET = frozenset("かきくけこさしすせそたちつてとはひふへほぱぴぷぺぽっ")
# 学習者が扱う「語」は助動詞まで含む（行き/まし/た → 行きました）。ただし前が活用する語のときだけで、
# 名詞の後の「です」は分けておく（天気/です）
_INFLECTING = frozenset({"動詞", "形容詞", "助動詞"})
_SYMBOL_POS = frozenset({"補助記号", "空白"})
_lock = threading.Lock()


def has_sudachi() -> bool:
    """日本語の読みが取れるか。daemon 起動時に重い import をしないよう find_spec で見る"""
    return (importlib.util.find_spec("sudachipy") is not None
            and importlib.util.find_spec("sudachidict_core") is not None)


@lru_cache(maxsize=1)
def _tokenizer() -> Any:
    from sudachipy import Dictionary, SplitMode

    return Dictionary(dict="core").tokenizer(mode=SplitMode.C)


def morae(kana: str) -> tuple[str, ...]:
    """発音に寄せたひらがなをモーラに割る。直前と同じ母音だけのモーラは長音 `ー` にする"""
    out: list[str] = []
    for c in phonetic(hiragana(kana)):
        if c in _SMALL and out:
            out[-1] += c
        elif out and c in _VOWELS and VOWEL_OF.get(out[-1][-1]) == c:
            out.append(LONG)
        else:
            out.append(c)
    return tuple(out)


def mark_devoicing(seq: Sequence[str]) -> tuple[str, ...]:
    """無声化しうるモーラに印を付ける。無声子音の前と、文末の「す」（です・ます）"""
    out = list(seq)
    for i, mora in enumerate(seq):
        if mora not in _DEVOICEABLE:
            continue
        nxt = seq[i + 1] if i + 1 < len(seq) else None
        if (nxt is not None and nxt[0] in _VOICELESS_ONSET) or (nxt is None and mora == "す"):
            out[i] = mora + DEVOICED
    return tuple(out)


def sub_cost(expected: str, actual: str) -> int:
    """置換のコスト。無声化の印があるモーラは、印の無い形と、モデルの聞き違え（し/す）を同じ音とみなす"""
    if expected == actual:
        return 0
    if expected.endswith(DEVOICED):
        base = expected[:-1]
        if actual == base or actual == _DEVOICED_HEARD_AS.get(base):
            return 0
    return 1


def expected_words(text: str) -> tuple[tuple[str, ...], tuple[tuple[str, ...], ...]]:
    """課題文を語に割り、語ごとの期待モーラ列を返す。読みがかなにならない語があれば G2PError"""
    if not has_sudachi():
        raise G2PError("pronounce extra is not installed")
    with _lock:   # sudachi のトークナイザはスレッド間で共有しない
        tokens = [(m.surface(), m.reading_form(), m.part_of_speech()) for m in _tokenizer().tokenize(text)]
    words: list[str] = []
    readings: list[str] = []
    attach_next = False
    prev_pos = ""
    for surface, reading, pos in tokens:
        if pos[0] in _SYMBOL_POS:
            attach_next, prev_pos = False, ""
            continue
        kana = hiragana(reading)
        if not kana or not is_kana(kana):
            raise G2PError(f"cannot read {surface!r} as kana: {reading!r}")
        attach = (attach_next or pos[0] == "接尾辞"
                  or (prev_pos in _INFLECTING and (pos[0] == "助動詞" or pos[1] == "接続助詞")))
        if words and attach:
            words[-1] += surface
            readings[-1] += kana
        else:
            words.append(surface)
            readings.append(kana)
        attach_next, prev_pos = pos[0] == "接頭辞", pos[0]
    per_word = [morae(r) for r in readings]
    # 無声化は語をまたいで決まる（「行きました」の し は た の前）ので、連結してから印を付けて割り戻す
    marked = mark_devoicing([m for seq in per_word for m in seq])
    out: list[tuple[str, ...]] = []
    at = 0
    for seq in per_word:
        out.append(marked[at:at + len(seq)])
        at += len(seq)
    return tuple(words), tuple(out)


def actual_morae(decoded: str) -> tuple[str, ...]:
    """かな認識モデルの出力（語区切りの `|` や空白を含む）をモーラ列にする"""
    return morae("".join(c for c in decoded if is_kana(c)))
