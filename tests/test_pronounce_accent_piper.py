"""英音の判定の入れ替え試験: 米音の声を英音の基準で、英音の声を米音の基準で判定し、米英の違いを指摘できるか

piper の声は espeak の音素から作られるので、正しい読みを誤りにしないかの試験にはならない（設計書「3. ゲート」）。
ここで見るのは、米英で違う語の違いを見つけられるか、違わない語を誤りにしないかだけ。
音素認識モデルと piper の声がローカルに無ければ SKIP する（ダウンロードしない）

実行: uv run python tests/test_pronounce_accent_piper.py
"""
from __future__ import annotations

import importlib.util
import os
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")  # モデルは手元のものだけ使う

import numpy as np

from shadow_clerk import DATA_DIR
from shadow_clerk._daemon_constants import DEFAULT_CONFIG
from shadow_clerk._daemon_pronounce import compare
from shadow_clerk._daemon_pronounce_ipa import PhonemeRecogniser, expected_ipa, has_espeak, has_torch, split_words
from shadow_clerk._daemon_tts import resample
from shadow_clerk.domain import EnglishAccent, Language, WordComparison

PIPER_DIR = os.path.join(DATA_DIR, "piper")
US_VOICE, GB_VOICE = "en_US-hfc_female-medium", "en_GB-cori-medium"
# 違いを見る語と、違わない語。単語単体は PER が振れるのでキャリア文で読ませる。
# 対象語の後ろを母音で始めない（"car again" は英音でも r をつなげて言う。linking r）
DIFF_SENTENCE, SAME_SENTENCE = "Say car now.", "Say think now."

results: list[bool] = []
_recogniser: PhonemeRecogniser | None = None


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def available() -> str:
    """使えない理由。使えるなら空"""
    if not (has_espeak() and has_torch()) or importlib.util.find_spec("piper") is None:
        return "pronounce / piper extra が無い"
    if not all(os.path.exists(os.path.join(PIPER_DIR, v + ".onnx")) for v in (US_VOICE, GB_VOICE)):
        return "piper の声がローカルに無い"
    try:
        recogniser().load()
    except Exception as e:  # pylint: disable=broad-except
        return f"音素認識モデルを読めない: {e}"
    return ""


def recogniser() -> PhonemeRecogniser:
    global _recogniser  # pylint: disable=global-statement
    if _recogniser is None:
        _recogniser = PhonemeRecogniser(str(DEFAULT_CONFIG["pronounce_model"]), "cpu", 0)
    return _recogniser


def synth(voice: str, text: str, speaker: str | None = None, steady: bool = True) -> np.ndarray:
    """piper で読んだ 16kHz の PCM。speaker は多話者モデル（VCTK）の話者名。
    steady なら合成の乱数を止める（毎回同じ音になる。試験が揺れない）"""
    from piper import PiperVoice, SynthesisConfig
    model = PiperVoice.load(os.path.join(PIPER_DIR, voice + ".onnx"))
    sid = model.config.speaker_id_map[speaker] if speaker else None
    config = SynthesisConfig(speaker_id=sid, noise_scale=0.0, noise_w_scale=0.0) if steady else SynthesisConfig(speaker_id=sid)
    pcm = np.concatenate([c.audio_float_array for c in model.synthesize(text, config)])
    return resample(pcm.astype(np.float32), int(model.config.sample_rate), 16000)


def judge(pcm: np.ndarray, text: str, accent: EnglishAccent) -> dict[str, WordComparison]:
    """accent の基準で判定した語ごとの対応（語は小文字）"""
    words = split_words(text)
    per_word = tuple(expected_ipa(w, Language.EN, accent) for w in words)
    return {c.word.lower(): c for c in compare(words, per_word, recogniser().actual_ipa(pcm), ())}


def r_flagged(c: WordComparison) -> bool:
    """r（ɹ / r 性母音 R）について、同じでない対応があるか"""
    return any(op.kind.value != "same" and {"ɹ", "R"} & {op.expected, op.actual} for op in c.ops)


def test_cross() -> None:
    us_on_gb = judge(synth(US_VOICE, DIFF_SENTENCE), DIFF_SENTENCE, EnglishAccent.BRITISH)["car"]
    check("米音の声の car は、英音の基準で r が指摘される", r_flagged(us_on_gb), repr(us_on_gb.ops))
    gb_on_us = judge(synth(GB_VOICE, DIFF_SENTENCE), DIFF_SENTENCE, EnglishAccent.AMERICAN)["car"]
    check("英音の声の car は、米音の基準で r が指摘される", r_flagged(gb_on_us), repr(gb_on_us.ops))
    for voice, accent in ((US_VOICE, EnglishAccent.BRITISH), (GB_VOICE, EnglishAccent.AMERICAN)):
        think = judge(synth(voice, SAME_SENTENCE), SAME_SENTENCE, accent)["think"]
        check(f"違わない語 think は誤りにしない（{voice} × {accent.value}）",
              all(op.kind.value == "same" for op in think.ops), repr(think.ops))


if __name__ == "__main__":
    if reason := available():
        print(f"[SKIP] {reason}")
        sys.exit(0)
    test_cross()
    sys.exit(0 if all(results) else 1)
