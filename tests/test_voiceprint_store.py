"""声紋ストアのテスト"""
from __future__ import annotations

import os
import stat

import numpy as np
import pytest

import shadow_clerk._daemon_voiceprint_store as store_mod
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore, VoiceprintStoreError
from shadow_clerk.domain.voiceprint import PersonName, VoiceSample


def _sample(seed: int, ts: str = "2026-10-09 10:00:00") -> VoiceSample:
    v = np.random.default_rng(seed).normal(size=256).astype(np.float32)
    return VoiceSample(v / np.linalg.norm(v), ts, "transcript-202610091000.txt")


@pytest.fixture
def store(tmp_path, monkeypatch) -> VoiceprintStore:
    monkeypatch.setattr(store_mod, "load_config", lambda: {})
    return VoiceprintStore(str(tmp_path / "voiceprints.json"))


def test_empty(store) -> None:
    assert store.people() == {}
    assert store.samples(PersonName("太郎")) == []


def test_add_and_read(store) -> None:
    s = _sample(1)
    store.add({PersonName("太郎"): [s], PersonName("次郎"): [_sample(2), _sample(3)]})
    assert store.people() == {"太郎": 1, "次郎": 2}
    got = store.samples(PersonName("太郎"))
    assert len(got) == 1 and float(got[0].embedding @ s.embedding) > 0.999


def test_add_appends(store) -> None:
    store.add({PersonName("太郎"): [_sample(1)]})
    store.add({PersonName("太郎"): [_sample(2)]})
    assert store.people() == {"太郎": 2}


def test_cap_keeps_newest(store, monkeypatch) -> None:
    monkeypatch.setattr(store_mod, "load_config", lambda: {"voiceprint_max_samples": 3})
    store.add({PersonName("太郎"): [_sample(i, f"2026-10-09 10:00:0{i}") for i in range(5)]})
    assert [s.recorded_at for s in store.samples(PersonName("太郎"))] == \
        ["2026-10-09 10:00:02", "2026-10-09 10:00:03", "2026-10-09 10:00:04"]


def test_delete(store) -> None:
    store.add({PersonName("太郎"): [_sample(1)]})
    assert store.delete("太郎") is True
    assert store.delete("太郎") is False
    assert store.people() == {}


def test_file_is_private(store) -> None:
    store.add({PersonName("太郎"): [_sample(1)]})
    assert stat.S_IMODE(os.stat(store.path).st_mode) == 0o600


@pytest.mark.parametrize("content", ["{broken", "[]", '{"version": 1}',
                                       '{"version": 1, "people": {"太郎": "x"}}',
                                       '{"version": 1, "people": {"太郎": {"samples": "abc"}}}'])
def test_broken_file_is_never_overwritten(store, content) -> None:
    with open(store.path, "w", encoding="utf-8") as f:
        f.write(content)
    with pytest.raises(VoiceprintStoreError):
        store.add({PersonName("太郎"): [_sample(1)]})
    with pytest.raises(VoiceprintStoreError):
        store.delete("太郎")
    with pytest.raises(VoiceprintStoreError):
        store.people()
    with open(store.path, encoding="utf-8") as f:
        assert f.read() == content


def test_broken_file_invalid_utf8_is_never_overwritten(store) -> None:
    """Test that invalid UTF-8 bytes are handled safely"""
    content_bytes = b'\xff\xfe{"people": {}}'
    with open(store.path, "wb") as f:
        f.write(content_bytes)
    with pytest.raises(VoiceprintStoreError):
        store.add({PersonName("太郎"): [_sample(1)]})
    with pytest.raises(VoiceprintStoreError):
        store.delete("太郎")
    with pytest.raises(VoiceprintStoreError):
        store.people()
    with open(store.path, "rb") as f:
        assert f.read() == content_bytes
