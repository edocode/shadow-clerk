"""Shadow-clerk daemon: 発音フィードバックの音素変換（G2P・音素認識・正規化）

音と文字を正規化済みの音素列に変換するところまでを持つ。突き合わせは _daemon_pronounce.py。
副作用は遅延ロードしたモデルの保持だけ。
"""
from __future__ import annotations

import importlib.util
import logging
import re
import unicodedata
from typing import Any, Sequence

from shadow_clerk.domain import Language

logger = logging.getLogger("shadow-clerk")

# 1 分割: espeak が1記号で書く複合単位を、モデルの粒度に合わせて割る
_SPLIT: dict[str, tuple[str, ...]] = {
    "ɔːɹ": ("ɔː", "ɹ"), "ɑːɹ": ("ɑː", "ɹ"), "ɛɹ": ("ɛ", "ɹ"), "ɪɹ": ("ɪ", "ɹ"),
    "ʊɹ": ("ʊ", "ɹ"), "iːɹ": ("iː", "ɹ"), "aɪɚ": ("aɪ", "ɚ"), "aʊɚ": ("aʊ", "ɚ"),
    "əl": ("ə", "l"), "ən": ("ə", "n"), "əm": ("ə", "m"), "ɚɹ": ("ɚ",),
}
# 2 除去: 長音・強勢・声調の数字。等価クラス表より前に落とす（ɜː は ɜ→R に当たらない）
_STRIP = str.maketrans("", "", "ːˈˌ")
_TONE = re.compile(r"\d+$")
# 3 寄せ: モデルが出す ASCII 異体を IPA に揃える
_ASCII_VARIANT: dict[str, str] = {"ai": "aɪ", "au": "aʊ", "ei": "eɪ", "oi": "ɔɪ", "ou": "oʊ"}
# 4 マージ: espeak とモデルで表記が割れるものだけ。意味のある対立（ɹ/l, iː/ɪ, θ/s, b/v）は残す。
#    r a e はネイティブ発話に出ない非ネイティブ専用の記号なので、ここに入れてはいけない（制約3）
_CLASS: dict[str, str] = {
    "ə": "@", "ɐ": "@", "ʌ": "@", "ᵻ": "@", "ɨ": "@", "ɪ": "@",   # 曖昧母音・中舌
    "ɚ": "R", "ɜ": "R", "ɝ": "R", "ɹ̩": "R",                        # r 性母音
    "ɔ": "O", "o": "O", "ɑ": "O", "ɒ": "O",                        # 後舌円唇
    "æ": "A",
    "ɾ": "t", "ʔ": "t", "ɫ": "l",                                  # フラップ・声門閉鎖・暗い l
}


def normalise(seq: Sequence[str]) -> tuple[str, ...]:
    """espeak とモデルの表記の揺れを吸収する。適用順は 分割 → 除去 → 寄せ → マージ → 圧縮"""
    out: list[str] = []
    for raw in seq:
        for part in _SPLIT.get(raw, (raw,)):
            sym = _TONE.sub("", part.translate(_STRIP))
            if not sym:
                continue
            sym = _ASCII_VARIANT.get(sym, sym)
            out.append(_CLASS.get(sym, sym))
    # 5 圧縮: CTC は同じ記号を繰り返し出す。隣り合う同一記号は1つにまとめる
    return tuple(sym for i, sym in enumerate(out) if i == 0 or sym != out[i - 1])


# espeak が語の切れ目に入れる記号。1語の G2P 出力にこれが出たら、その語は扱えない
_WORD_SEPARATOR = "|"
# 課題文から落とす前後の記号。語中のアポストロフィとハイフンは残す
_EDGE_PUNCT = '.,!?;:"‘’“”()[]{}'


class G2PError(ValueError):
    """課題文を音素化できない。未導入・言語切り替えマーカー・語区切りのいずれか"""


def has_espeak() -> bool:
    """G2P が使えるか。daemon 起動時に重い import をしないよう find_spec で見る"""
    return (importlib.util.find_spec("phonemizer") is not None
            and importlib.util.find_spec("espeakng_loader") is not None)


def split_words(text: str) -> tuple[str, ...]:
    """課題文を語に割る。NFKC で曲がったアポストロフィを直してから、空白で割り前後の記号を落とす。

    返すのは原形。照合に使うキーはこれを小文字化したもの（設計書 §4.1-1、§7.1）
    """
    normalised = unicodedata.normalize("NFKC", text)
    words = (token.strip(_EDGE_PUNCT) for token in normalised.split())
    return tuple(word for word in words if word)


def _phonemizer_backend(language: Language) -> Any:
    """espeak バックエンドを作る。ホイールで入る espeak-ng を使うのでシステム依存は無い"""
    import espeakng_loader
    from phonemizer.backend import EspeakBackend
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    return EspeakBackend(_ESPEAK_LANG[language], with_stress=True)


# v1 は英語のみ。日本語はモデル側の限界で測れない（正規化後 PER 48.79%。英語は 9.10%）。
# 言語を足すのは手順ではなくゲート: コーパスでフロアを測り、閾値（PER 15%）を超えたら
# その言語は非対応と判定する（設計書 §6.3）
_ESPEAK_LANG: dict[Language, str] = {Language.EN: "en-us"}


def expected_ipa(word: str, language: Language) -> tuple[str, ...]:
    """1語だけを音素化して正規化する。文で呼ぶと the の弱形のように文脈で変わるので語ごとに呼ぶ"""
    if not has_espeak():
        raise G2PError("pronounce extra is not installed")
    if language not in _ESPEAK_LANG:
        raise G2PError(f"language {language.value} is not supported")
    # この espeak は "well-known" を語区切り無しの1語に融合して返す（実測）ので、下の語区切り検査では
    # 拾えない。融合した列は語への帰属がずれるため、ハイフン語はここで拒否する
    if "-" in word:
        raise G2PError(f"hyphenated word {word!r} cannot be attributed to a single word")
    from phonemizer.separator import Separator

    backend = _phonemizer_backend(language)
    # phone / word / syllable は互いに違う文字でなければならない
    raw = backend.phonemize([word], separator=Separator(phone=" ", word=_WORD_SEPARATOR, syllable=""))[0]
    if "(" in raw or ")" in raw:
        raise G2PError(f"espeak switched language while reading {word!r}: {raw!r}")
    if _WORD_SEPARATOR in raw.strip().strip(_WORD_SEPARATOR):
        raise G2PError(f"espeak split {word!r} into more than one word: {raw!r}")
    return normalise([p for p in raw.replace(_WORD_SEPARATOR, " ").split(" ") if p])
