"""スパイクで実測した音素列。発音フィードバックの回帰データ

出典: improvement/pronunciation-feedback.md
すべて正規化後（_daemon_pronounce_ipa.normalise を通した形）。
元の録音は再現できないので、ここが唯一の原本。
"""
from __future__ import annotations

# 期待IPA（espeak-ng の G2P → 正規化後）
GLASS_EXPECTED = ("ɡ", "l", "A", "s")
LIGHT_EXPECTED = ("l", "aɪ", "t")
# "Say glass again." を語ごとに G2P して連結したもの
CARRIER_EXPECTED = ("s", "eɪ", "ɡ", "l", "A", "s", "@", "ɡ", "eɪ", "n")
CARRIER_WORDS = ("say", "glass", "again")
CARRIER_WORD_LENGTHS = (2, 4, 4)   # say / glass / again の期待音素数

# 日本語話者が "glass" を単体で言ったときの実測（誇張テイクを含む）
GLASS_TAKES = (
    ("ɡ", "u", "ɹ", "a", "f", "s"),
    ("ɡ", "u", "ɹ", "a", "θ"),
    ("ɡ", "u", "dʒ", "a", "s"),
    ("u", "l", "a", "s"),
    ("ɡ", "u", "l", "a", "θ"),
    ("k", "@", "d", "l", "a", "θ"),
    ("ɡ", "@", "d", "r", "a", "θ"),
    ("k", "r", "ʉ", "h", "a"),
    ("k", "@", "l", "a"),
    ("k", "a", "θ"),
)

# "light" の実測。r と l が両方出るテイクを含む（中間的な調音）
LIGHT_TAKES = (
    ("r", "l", "aɪ"),
    ("r", "aɪ", "t"),
    ("l", "aɪ", "t"),
    ("n", "r", "aɪ", "t"),
)

# "Say glass again." の実測1本（語頭連結に母音が挿入されている）
CARRIER_ACTUAL = ("s", "eɪ", "ɡ", "@", "ɹ", "a", "s", "@", "ɡ", "eɪ", "n")

# スパイクでモデルが実際に出した記号の全体（正規化後）。音素クラス表の網羅性の回帰に使う
MODEL_INVENTORY = frozenset({
    "@", "R", "O", "A", "a", "e", "ɛ", "i", "u", "ʊ", "ʉ", "aɪ", "aʊ", "eɪ", "oʊ",
    "b", "d", "dʒ", "f", "h", "j", "k", "l", "m", "n", "ŋ", "p", "r", "ɹ", "s",
    "ʃ", "t", "tʃ", "θ", "ð", "v", "w", "z", "ʒ", "ɡ",
})
