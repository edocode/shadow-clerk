"""Shadow-clerk daemon: 発音フィードバックの音素変換（G2P・音素認識・正規化）

音と文字を正規化済みの音素列に変換するところまでを持つ。突き合わせは _daemon_pronounce.py。
副作用は遅延ロードしたモデルの保持だけ。
"""
from __future__ import annotations

import logging
import re
from typing import Sequence

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
