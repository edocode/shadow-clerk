"""声紋まわりの値オブジェクトのテスト"""
from __future__ import annotations

import numpy as np
import pytest

from shadow_clerk.domain.voiceprint import (
    PersonName, VoiceEntry, VoiceSample, decode_embedding, encode_embedding,
)


def _vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=256).astype(np.float32)
    return v / np.linalg.norm(v)


def test_embedding_roundtrip_keeps_direction() -> None:
    v = _vec(1)
    back = decode_embedding(encode_embedding(v))
    assert back.dtype == np.float32
    assert float(back @ v) > 0.999


@pytest.mark.parametrize("bad", ["", "@@@", "AAA=", encode_embedding(np.zeros(256))])
def test_decode_rejects_broken(bad: str) -> None:
    with pytest.raises(ValueError):
        decode_embedding(bad)


def test_person_name_strips() -> None:
    assert PersonName("  太郎 ").value == "太郎"


def test_person_name_is_hashable_and_equal_by_value() -> None:
    assert {PersonName("太郎"): 1}[PersonName("太郎")] == 1


@pytest.mark.parametrize("bad", ["", "   ", "[太郎]", "太]郎", "自分", "相手", "相手A", "相手方",
                                 "Claude", "a\nb", "x" * 51])
def test_person_name_rejects(bad: str) -> None:
    with pytest.raises(ValueError):
        PersonName(bad)


def test_voice_sample_dict_roundtrip() -> None:
    s = VoiceSample(_vec(2), "2026-10-09 10:00:00", "transcript-202610091000.txt")
    back = VoiceSample.from_dict(s.to_dict())
    assert back.recorded_at == s.recorded_at and back.source == s.source
    assert float(back.embedding @ s.embedding) > 0.999


def test_voice_entry_line_roundtrip() -> None:
    e = VoiceEntry("2026-10-09 10:00:00", "相手A", _vec(3))
    line = e.to_json_line()
    assert line.endswith("\n")
    back = VoiceEntry.parse(line)
    assert back is not None
    assert (back.timestamp, back.label) == (e.timestamp, e.label)
    assert float(back.embedding @ e.embedding) > 0.999


@pytest.mark.parametrize("bad", ["", "{", "[]", '{"ts": "x", "label": "相手A"}',
                                 '{"ts": "x", "label": "相手A", "emb": "@@"}'])
def test_voice_entry_parse_broken_is_none(bad: str) -> None:
    assert VoiceEntry.parse(bad) is None
