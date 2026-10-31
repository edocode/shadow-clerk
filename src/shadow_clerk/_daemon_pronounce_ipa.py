"""Shadow-clerk daemon: 発音フィードバックの音素変換（G2P・音素認識・正規化）

音と文字を正規化済みの音素列に変換するところまでを持つ。突き合わせは _daemon_pronounce.py。
副作用は遅延ロードしたモデルの保持だけ。
"""
from __future__ import annotations

import importlib.util
import logging
import re
import threading
import unicodedata
from typing import Any, Sequence

import numpy as np

from shadow_clerk.domain import Language

logger = logging.getLogger("shadow-clerk")

# 1 分割: espeak が1記号で書く複合単位を、モデルの粒度に合わせて割る
_SPLIT: dict[str, tuple[str, ...]] = {
    "ɔːɹ": ("ɔː", "ɹ"), "ɑːɹ": ("ɑː", "ɹ"), "ɛɹ": ("ɛ", "ɹ"), "ɪɹ": ("ɪ", "ɹ"),
    "ʊɹ": ("ʊ", "ɹ"), "iːɹ": ("iː", "ɹ"), "aɪɚ": ("aɪ", "ɚ"), "aʊɚ": ("aʊ", "ɚ"),
    "əl": ("ə", "l"), "ən": ("ə", "n"), "əm": ("ə", "m"), "ɚɹ": ("ɚ",),
}
# 2 除去: 長音・強勢・声調の数字。等価クラス表より前に落とす（ɜː は ɜ→R に当たらない）。
#    強勢は音素に前置されるので、分割表を引く前に落とす（`ˈɔːɹ` がキー `ɔːɹ` と一致しない）
_PRE_STRIP = str.maketrans("", "", "ˈˌ")
_STRIP = str.maketrans("", "", "ː")
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
        stressless = raw.translate(_PRE_STRIP)
        for part in _SPLIT.get(stressless, (stressless,)):
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
# （str.strip は前後しか削らないので、`It's` のアポストロフィは残り、`'hello'` の囲みだけ落ちる）
_EDGE_PUNCT = '.,!?;:"\'‘’“”()[]{}'
# 曲がった引用符を直の字体に畳む。NFKC はこれを変換しないので別に持つ（実測）。
# espeak は両方の字体で同じ音素を返すので、畳んでも読みは変わらない
_QUOTE_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


class G2PError(ValueError):
    """課題文を音素化できない。未導入・言語切り替えマーカー・語区切りのいずれか"""


def has_espeak() -> bool:
    """G2P が使えるか。daemon 起動時に重い import をしないよう find_spec で見る"""
    return (importlib.util.find_spec("phonemizer") is not None
            and importlib.util.find_spec("espeakng_loader") is not None)


def split_words(text: str) -> tuple[str, ...]:
    """課題文を語に割る。全角英数などを NFKC で揃え、曲がった引用符を直の字体に畳んでから、
    空白で割って前後の記号を落とす。

    返すのは原形。照合に使うキーは word_key() で作る（設計書 §4.1-1、§7.1）
    """
    normalised = unicodedata.normalize("NFKC", text).translate(_QUOTE_FOLD)
    words = (token.strip(_EDGE_PUNCT) for token in normalised.split())
    return tuple(word for word in words if word)


def word_key(word: str) -> str:
    """`focus[].word` と課題文の語を突き合わせるためのキー。引用符の字体差と大小文字を吸収する"""
    return unicodedata.normalize("NFKC", word).translate(_QUOTE_FOLD).lower()


def _phonemizer_backend(language: Language) -> Any:
    """espeak バックエンドを作る。ホイールで入る espeak-ng を使うのでシステム依存は無い。

    キャッシュしないのは、呼ばれるのがアームのときだけ（1課題あたり語数回）で、頻度が低いから。
    スレッド間の分離にはならない（set_library() / set_data_path() はクラス属性を書き、
    espeak 自体もプロセス大域のハンドルを持つので、作り直しても隔離は得られない）
    """
    import espeakng_loader
    from phonemizer.backend import EspeakBackend
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    EspeakWrapper.set_library(espeakng_loader.get_library_path())
    EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
    # スパイクの測定は with_stress=False で行った。強勢記号は音素トークンに前置されるので、
    # True にすると `ˈɔːɹ` が `_SPLIT` のキー `ɔːɹ` と一致せず、分割表が丸ごと死ぬ
    return EspeakBackend(_ESPEAK_LANG[language], with_stress=False)


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
    from phonemizer.separator import Separator

    backend = _phonemizer_backend(language)
    # phone / word / syllable は互いに違う文字でなければならない
    raw = backend.phonemize([word], separator=Separator(phone=" ", word=_WORD_SEPARATOR, syllable=""))[0]
    if "(" in raw or ")" in raw:
        raise G2PError(f"espeak switched language while reading {word!r}: {raw!r}")
    if _WORD_SEPARATOR in raw.strip().strip(_WORD_SEPARATOR):
        raise G2PError(f"espeak split {word!r} into more than one word: {raw!r}")
    return normalise([p for p in raw.replace(_WORD_SEPARATOR, " ").split(" ") if p])


# モデルが期待するサンプリングレート。録音は 16kHz なので変換は要らない
_MODEL_SAMPLE_RATE = 16000


def _as_model_pcm(pcm: Any) -> np.ndarray:
    """モデルに渡す形に揃える。録音は int16 で来るので float32 の ±1.0 に直す。

    int16 のまま特徴抽出に渡すと、ゼロ平均・単位分散の正規化が numpy で float64 に昇格し、
    `Input type (double) and bias type (float) should be the same` で毎回落ちる（実機で発生）。
    文字起こし側（`_daemon_transcriber.py`）も同じ変換をしている
    """
    arr = np.asarray(pcm)
    if np.issubdtype(arr.dtype, np.integer):
        full_scale = float(1 << (8 * arr.dtype.itemsize - 1))
        return arr.astype(np.float32) / full_scale
    return arr.astype(np.float32, copy=False)


def has_torch() -> bool:
    """音素認識モデルが使えるか。daemon 起動時に torch を import しないよう find_spec で見る"""
    return (importlib.util.find_spec("torch") is not None
            and importlib.util.find_spec("transformers") is not None)


class PhonemeRecogniser:
    """wav2vec2 の音素認識。モデルは最初に使うときだけ読み、アイドルで解放する。

    1.2GB あるので、読み込みは呼び手がワーカースレッドから行う（API スレッドを塞がない）
    """

    def __init__(self, model: str, device: str, threads: int, label: str = "pronounce") -> None:
        self._label = label
        self._model_name = model
        self._device = device
        self._threads = threads
        self._lock = threading.Lock()
        self._processor: Any = None
        self._model: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """モデルを読む。初回は 1.2GB のダウンロードがある。二重に呼んでも1回しか読まない"""
        with self._lock:
            if self._model is not None:
                return
            import torch
            from transformers import AutoModelForCTC, AutoProcessor

            if self._threads > 0:
                torch.set_num_threads(self._threads)
            logger.info("%s: モデルを読み込みます (%s)", self._label, self._model_name)
            processor = AutoProcessor.from_pretrained(self._model_name)
            model = AutoModelForCTC.from_pretrained(self._model_name).to(self._device).eval()
            self._processor, self._model = processor, model
            logger.info("%s: モデルの読み込みが終わりました", self._label)

    def unload(self) -> None:
        """アイドルで解放する。import torch 自体のメモリは残る"""
        with self._lock:
            if self._model is None:
                return
            self._processor = self._model = None
            logger.info("%s: モデルを解放しました", self._label)

    @property
    def processor(self) -> Any:
        return self._processor

    def logits(self, pcm: Any) -> Any:
        """16kHz モノラルの PCM から、1発話分の CTC ロジット (1 × フレーム × 語彙) を取る"""
        with self._lock:
            processor, model = self._processor, self._model
        if model is None:
            raise RuntimeError(f"{self._label} model is not loaded")
        import torch

        inputs = processor(_as_model_pcm(pcm), sampling_rate=_MODEL_SAMPLE_RATE, return_tensors="pt")
        with torch.no_grad():
            return model(inputs.input_values.to(self._device)).logits.cpu()

    def actual_ipa(self, pcm: Any) -> tuple[str, ...]:
        """16kHz モノラルの float32 PCM から、正規化済みの実測IPAを取る"""
        processor = self._processor   # 推論中にアイドル解放されても復号できるよう先に握る
        logits = self.logits(pcm)     # 未ロードならここで RuntimeError（torch を import する前）
        import torch

        text = processor.batch_decode(torch.argmax(logits, dim=-1))[0]
        return normalise(text.split())
