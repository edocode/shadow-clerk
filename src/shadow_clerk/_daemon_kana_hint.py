"""Shadow-clerk daemon: 聞き間違いの目印（kana_hint）

文字起こしの読み（形態素解析）と、かな認識モデルが音から聞き取ったかなを突き合わせ、
食い違う語の直後に `(音のかな?)` を添える（domain/kana_hint.py）。置き換えはしない。

かな認識の素の出力は崩れることがあるので、食い違いをそのまま添えはしない。CTC の強制スコアで
「文字起こしの読みより、音のかなの方がはっきり音に合う」ときだけ添える。
日本語の文字起こしのときだけ動く。音声はどこにも残さない。
"""
from __future__ import annotations

import importlib.util
import logging
import threading
from dataclasses import dataclass
from typing import Any

from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_pronounce_ipa import PhonemeRecogniser, has_torch
from shadow_clerk.domain.kana_hint import hint

logger = logging.getLogger("shadow-clerk")

MODEL = "vumichien/wav2vec2-large-xlsr-japanese-hiragana"
# 音のかなが、文字起こしの読みより対数確率で何以上よく合えば添えるか。使い捨ての実測
# （improvement/kana-mishear-correction.md）では、確かな食い違いは +12 以上、怪しいものは +3 以下だった
MIN_MARGIN = 8.0
# 長音の書き方違いを並べる上限
_MAX_SPELLINGS = 64
# 内容語でない品詞。ここだけの食い違い（助詞の脱落・挿入など）は聞き間違いとして扱わない
_FUNCTION_POS = frozenset({"助詞", "助動詞", "補助記号", "空白"})
_SYMBOL_POS = frozenset({"補助記号", "空白"})

_VOWEL: dict[str, str] = {}
for _vowel, _row in (("あ", "あかさたなはまやらわがざだばぱぁゃ"), ("い", "いきしちにひみりぎじぢびぴぃ"),
                     ("う", "うくすつぬふむゆるぐずづぶぷぅゅゔ"), ("え", "えけせてねへめれげぜでべぺぇ"),
                     ("お", "おこそとのほもよろをごぞどぼぽぉょ")):
    _VOWEL.update(dict.fromkeys(_row, _vowel))


def _hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def _is_kana(s: str) -> bool:
    return all("ぁ" <= c <= "ゖ" or c == "ー" for c in s)


def phonetic(kana: str) -> str:
    """ひらがなの表記揺れを発音に寄せる。を→お、ぢづ→じず、ー と長音の う/い → 直前の母音。
    1 字ずつ置き換えるだけなので、位置は元の文字列と対応したまま"""
    out: list[str] = []
    for c in kana.translate(str.maketrans("をぢづ", "おじず")):
        prev = _VOWEL.get(out[-1]) if out else None
        if (c == "ー" and prev) or (c == "う" and prev == "お") or (c == "い" and prev == "え"):
            c = prev
        out.append(c)
    return "".join(out)


def spellings(reading: str, before: str = "") -> list[str]:
    """発音に寄せた読みから、長音の書き方違い（おお/おう/おー など）を並べる。
    かなモデルは表記どおりのかなを学習しているので、どの書き方で出すかは語ごとに違う"""
    variants = [""]
    prev = _VOWEL.get(before[-1:])
    for c in reading:
        alts = [c]
        if c == prev:
            alts += ["ー"] + (["う"] if c == "お" else []) + (["い"] if c == "え" else [])
        variants = [v + a for v in variants for a in alts][:_MAX_SPELLINGS]
        prev = _VOWEL.get(c)
    return variants


@dataclass(frozen=True)
class _Morpheme:
    begin: int      # 文字起こしの中の位置
    end: int
    reading: str    # 発音に寄せたひらがな
    pos: str        # 品詞の大分類

    @property
    def content(self) -> bool:
        return self.pos not in _FUNCTION_POS


def morphemes(tokenizer: Any, text: str) -> list[_Morpheme] | None:
    """形態素と読み。読みがかなにならない語（辞書に無い漢字など）があれば None"""
    out: list[_Morpheme] = []
    for m in tokenizer.tokenize(text):
        pos = m.part_of_speech()[0]
        if pos in _SYMBOL_POS:
            out.append(_Morpheme(m.begin(), m.end(), "", pos))
            continue
        # 助詞の「は」「へ」はそのまま。かなモデルも発音（わ・え）ではなく表記どおりに書く
        kana = _hira(m.reading_form())
        if not kana or not _is_kana(kana):
            return None
        out.append(_Morpheme(m.begin(), m.end(), phonetic(kana), pos))
    return out


def align(a: str, b: str) -> tuple[list[int], list[int]]:
    """編集距離の最短経路で a の各境界を b に写す。境界 i に対応する b の位置の最小と最大を返す
    （最大と最小が違うのは、その境界に b 側の挿入があるとき）"""
    n, m = len(a), len(b)
    d = [[i + j if i == 0 or j == 0 else 0 for j in range(m + 1)] for i in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    lo, hi = [m] * (n + 1), [0] * (n + 1)
    i, j = n, m
    while True:
        lo[i], hi[i] = min(lo[i], j), max(hi[i], j)
        if not i and not j:
            break
        if i and j and d[i][j] == d[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            i, j = i - 1, j - 1
        elif i and d[i][j] == d[i - 1][j] + 1:
            i -= 1
        else:
            j -= 1
    return lo, hi


@dataclass(frozen=True)
class Run:
    """音と食い違う、連続した形態素のかたまり"""
    first: int      # 形態素の添字
    last: int
    start: int      # 読みの中の位置
    end: int
    sound: tuple[int, int]  # 音のかなの中の位置


def mismatched_runs(morphs: list[_Morpheme], heard: str) -> list[Run]:
    """読みが音のかなと食い違う内容語のかたまり。1 字だけのかたまりは、次の助詞の手前まで広げる
    （「ど(と?)おった」より「どおった(とおった?)」の方が読める）"""
    starts = [0]
    for m in morphs:
        starts.append(starts[-1] + len(m.reading))
    reading = "".join(m.reading for m in morphs)
    lo, hi = align(reading, heard)
    bad = [bool(m.reading) and heard[hi[s]:lo[e]] != m.reading
           for m, s, e in zip(morphs, starts, starts[1:])]
    runs: list[Run] = []
    k = 0
    while k < len(morphs):
        if not bad[k]:
            k += 1
            continue
        first = k
        while k + 1 < len(morphs) and bad[k + 1]:
            k += 1
        content = any(m.content for m in morphs[first:k + 1])   # 広げた分は数えない
        if starts[k + 1] - starts[first] < 2:
            while k + 1 < len(morphs) and morphs[k + 1].reading and morphs[k + 1].pos != "助詞":
                k += 1
        s, e = starts[first], starts[k + 1]
        if content and hi[s] < lo[e]:
            runs.append(Run(first, k, s, e, (hi[s], lo[e])))
        k += 1
    return runs


class KanaHinter:
    """文字起こしの行に聞き間違いの目印を添える。モデルは有効なときに裏で読み、無効になったら解放する"""

    def __init__(self, recogniser: Any = None) -> None:
        self._recogniser = recogniser or PhonemeRecogniser(MODEL, "cpu", 0, label="kana_hint")
        self._tokenizer: Any = None
        self._loading = False
        self._warned = False

    @staticmethod
    def available() -> bool:
        return (has_torch() and importlib.util.find_spec("sudachipy") is not None
                and importlib.util.find_spec("sudachidict_core") is not None)

    def _ready(self) -> bool:
        """使えるなら True。有効で未ロードならロードを始めて False（その間の行には添えない）"""
        if not load_config().get("kana_hint"):
            if self._recogniser.loaded:
                self._recogniser.unload()
            return False
        if self._recogniser.loaded and self._tokenizer is not None:
            return True
        if not self.available():
            if not self._warned:
                logger.warning("kana_hint: kana-hint extra が入っていないので動きません")
                self._warned = True
            return False
        if not self._loading:
            self._loading = True
            threading.Thread(target=self._load, name="kana-hint-load", daemon=True).start()
        return False

    def _load(self) -> None:
        try:
            from sudachipy import Dictionary, SplitMode

            self._tokenizer = Dictionary(dict="core").tokenizer(mode=SplitMode.A)
            self._recogniser.load()
        except Exception as e:
            logger.warning("kana_hint: モデルを読み込めませんでした: %s", e)
        finally:
            self._loading = False

    def annotate(self, text: str, pcm: Any, language: str | None) -> str:
        """目印を添えた行を返す。日本語でないとき、無効なとき、失敗したときは text のまま"""
        if language != "ja" or not text.strip() or not self._ready():
            return text
        try:
            return self._annotate(text, pcm)
        except Exception as e:   # 文字起こしを止めない
            logger.warning("kana_hint: 目印を付けられませんでした: %s", e)
            return text

    def _annotate(self, text: str, pcm: Any) -> str:
        import torch

        morphs = morphemes(self._tokenizer, text)
        if not morphs:
            return text
        tokenizer = self._recogniser.processor.tokenizer
        lp = torch.log_softmax(self._recogniser.logits(pcm)[0], dim=-1)
        raw = "".join(c for c in tokenizer.decode(lp.argmax(-1).tolist()) if _is_kana(c))
        heard = phonetic(raw)
        reading = "".join(m.reading for m in morphs)
        inserts: list[tuple[int, str]] = []
        for run in mismatched_runs(morphs, heard):
            before, after = reading[:run.start], reading[run.end:]
            sound = raw[run.sound[0]:run.sound[1]]
            margin = (_score(lp, [before + sound + after], tokenizer)
                      - _score(lp, [before + v + after for v in spellings(reading[run.start:run.end], before)],
                               tokenizer))
            surface = text[morphs[run.first].begin:morphs[run.last].end]
            logger.info("kana_hint: %s(%s) ← 音 %s  差 %+.1f%s", surface, reading[run.start:run.end], sound,
                        margin, "" if margin >= MIN_MARGIN else "（添えない）")
            if margin >= MIN_MARGIN:
                inserts.append((morphs[run.last].end, hint(sound)))
        for pos, mark in reversed(inserts):
            text = text[:pos] + mark + text[pos:]
        return text


def _score(lp: Any, variants: list[str], tokenizer: Any) -> float:
    """音が読みの候補群のどれかである対数確率（CTC の強制スコアを logsumexp で束ねる）"""
    import torch
    import torch.nn.functional as F

    vocab = tokenizer.get_vocab()
    targets = [[vocab[c] for c in v if c in vocab] for v in variants]
    if max(len(t) for t in targets) > lp.shape[0]:
        return float("-inf")
    n = len(targets)
    losses = F.ctc_loss(
        lp[:, None, :].expand(-1, n, -1),
        torch.tensor([i for t in targets for i in t]),
        input_lengths=torch.full((n,), lp.shape[0], dtype=torch.long),
        target_lengths=torch.tensor([len(t) for t in targets]),
        blank=tokenizer.pad_token_id, reduction="none",
    )
    return float(torch.logsumexp(-losses, 0))
