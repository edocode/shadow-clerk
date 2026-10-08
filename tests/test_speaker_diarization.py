"""tests/test_speaker_diarization.py — 話者分離ユニットテスト

onnxruntime / モデル不要でも動くテスト（特徴量生成・マッチング・ラベル生成等）。
"""
from __future__ import annotations

import sys
sys.path.insert(0, "/home/ktat/git/gitlab.edocode.co.jp/common/shadow-clerk-diarization-v2/src")

import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from shadow_clerk._daemon_speaker_diarization import (
    SpeakerDiarizer,
    _cosine_similarity,
    _generate_label,
)
from shadow_clerk.domain.transcript_line import TranscriptLine, Speaker


def _silence(sec: float = 2.0) -> np.ndarray:
    return np.zeros(int(16000 * sec), dtype=np.int16)


# --- _generate_label ---

def test_generate_label_first():
    assert _generate_label(1) == "相手A"

def test_generate_label_last_alpha():
    assert _generate_label(26) == "相手Z"

def test_generate_label_beyond_alpha():
    assert _generate_label(27) == "相手27"

def test_generate_label_no_collision():
    labels = [_generate_label(i) for i in range(1, 30)]
    assert len(labels) == len(set(labels))


# --- 短セグメントは None を返す ---

def test_identify_speaker_short_returns_none():
    d = SpeakerDiarizer()
    audio = _silence(0.5)   # < 1.0s
    assert d.identify_speaker(audio) is None


# --- onnxruntime 未インストール時は None (かつ例外なし) ---

def test_identify_speaker_no_ort_returns_none(monkeypatch):
    import shadow_clerk._daemon_speaker_diarization as mod
    monkeypatch.setattr(mod, "_HAS_ORT", False)
    d = SpeakerDiarizer()
    audio = _silence(2.0)
    result = d.identify_speaker(audio)
    assert result is None


# --- 失敗フラグ: ダウンロード失敗後に _load_model を再呼びしても 1回だけ試みる ---

def test_load_model_failure_latch(monkeypatch):
    import shadow_clerk._daemon_speaker_diarization as mod
    import sys
    monkeypatch.setattr(mod, "_HAS_ORT", True)
    call_count = {"n": 0}

    def fake_download(*args, **kwargs):
        call_count["n"] += 1
        raise RuntimeError("network error")

    fake_hf = MagicMock()
    fake_hf.hf_hub_download = fake_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)

    d = SpeakerDiarizer()
    d._load_model()
    d._load_model()  # 2回目は latch で skip
    assert call_count["n"] == 1


# --- コサイン類似度の threshold 境界 (>= で既存話者を使う) ---

def test_best_match_uses_ge_not_gt():
    d = SpeakerDiarizer()
    emb = np.array([1.0, 0.0], dtype=np.float32)
    d._session_speakers["相手A"] = [emb.copy()]
    d._next_idx = 1

    with patch.object(d, "_threshold", return_value=1.0):
        name, score = d._best_match(emb, d._session_speakers)
    assert name == "相手A"
    assert abs(score - 1.0) < 1e-6


# --- 話者分離有効 + identify_speaker()=None → speaker_label="相手?" ---

def test_diarization_unknown_label_when_none(monkeypatch):
    import shadow_clerk._daemon_speaker_diarization as mod
    monkeypatch.setattr(mod, "_HAS_ORT", False)  # identify_speaker が None を返す状態

    from shadow_clerk._daemon_speaker_diarization import SpeakerDiarizer as SD
    diarizer = SD()
    # 話者分離有効時、None は "相手?" になる
    audio = _silence(2.0)
    raw = diarizer.identify_speaker(audio)  # None
    assert raw is None
    # transcribe 側のマッピング: None → "相手?"
    label = raw if raw is not None else "相手?"
    assert label == "相手?"


# --- "相手?" の TranscriptLine round-trip ---

def test_transcript_line_unknown_label_roundtrip():
    tl = TranscriptLine(
        timestamp="10:00:00",
        speaker=Speaker.OTHER,
        text="えっと",
        speaker_label="相手?",
    )
    line = tl.format()
    assert "[相手?]" in line
    parsed = TranscriptLine.parse(line)
    assert parsed is not None
    assert parsed.speaker == Speaker.OTHER
    assert parsed.speaker_label == "相手?"


# --- TranscriptLine.parse() round-trip ---

def test_transcript_line_parse_roundtrip_with_diarization_label():
    tl = TranscriptLine(
        timestamp="10:00:00",
        speaker=Speaker.OTHER,
        text="こんにちは",
        speaker_label="相手A",
    )
    line = tl.format()
    parsed = TranscriptLine.parse(line)
    assert parsed is not None
    assert parsed.speaker == Speaker.OTHER
    assert parsed.speaker_label == "相手A"
    assert parsed.text == "こんにちは"
