"""声紋ストアのテスト"""
from __future__ import annotations

import os
import stat

import numpy as np
import pytest

import shadow_clerk._daemon_voiceprint_clusters as cluster_mod
import shadow_clerk._daemon_voiceprint_store as store_mod
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore, VoiceprintStoreError
from shadow_clerk.domain.voiceprint import PersonName, SampleStatus, VoiceSample


def _sample(seed: int, ts: str = "2026-10-09 10:00:00") -> VoiceSample:
    v = np.random.default_rng(seed).normal(size=256).astype(np.float32)
    return VoiceSample(v / np.linalg.norm(v), ts, "transcript-202610091000.txt")


@pytest.fixture
def store(tmp_path, monkeypatch) -> VoiceprintStore:
    monkeypatch.setattr(store_mod, "load_config", lambda: {})
    monkeypatch.setattr(cluster_mod, "load_config", lambda: {})
    return VoiceprintStore(str(tmp_path / "voiceprints.json"))


def test_empty(store) -> None:
    assert store.people() == {}
    assert store.samples(PersonName("太郎")) == []


def test_add_and_read(store) -> None:
    s = _sample(1)
    store.add({PersonName("太郎"): [s], PersonName("次郎"): [_sample(2), _sample(3, "2026-10-09 10:00:01")]})
    assert store.people() == {"太郎": 1, "次郎": 2}
    got = store.samples(PersonName("太郎"))
    assert len(got) == 1 and float(got[0].embedding @ s.embedding) > 0.999


def test_add_appends(store) -> None:
    store.add({PersonName("太郎"): [_sample(1)]})
    store.add({PersonName("太郎"): [_sample(2, "2026-10-09 10:00:01")]})
    assert store.people() == {"太郎": 2}


def test_add_is_idempotent_per_source_and_time(store) -> None:
    store.add({PersonName("太郎"): [_sample(1)]})
    store.add({PersonName("太郎"): [_sample(1), _sample(2, "2026-10-09 10:00:01")]})
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


def test_update_moves_samples_between_people(store) -> None:
    a, b = _sample(1), _sample(2, "2026-10-09 10:00:01")
    store.add({PersonName("太郎"): [a, b]})
    store.update({PersonName("次郎"): [a]}, {"太郎": {(a.source, a.recorded_at)}})
    assert store.people() == {"太郎": 1, "次郎": 1}
    assert store.samples(PersonName("太郎"))[0].recorded_at == b.recorded_at


def test_update_drops_emptied_person_with_a_single_save(store, monkeypatch) -> None:
    a = _sample(1)
    store.add({PersonName("太郎"): [a]})
    saves: list[dict] = []
    orig = store._save
    monkeypatch.setattr(store, "_save", lambda people: (saves.append(people), orig(people))[1])
    store.update({PersonName("次郎"): [a]}, {"太郎": {(a.source, a.recorded_at)}})
    assert store.people() == {"次郎": 1} and len(saves) == 1


def test_update_remove_only_and_unknown_person(store) -> None:
    a = _sample(1)
    store.add({PersonName("太郎"): [a]})
    store.update({}, {"太郎": {(a.source, a.recorded_at)}, "三郎": {("x", "y")}})
    assert store.people() == {}


def test_update_returns_keys_actually_changed(store, monkeypatch) -> None:
    monkeypatch.setattr(store_mod, "load_config", lambda: {"voiceprint_max_samples": 2})
    a, b, c = _sample(1), _sample(2, "2026-10-09 10:00:01"), _sample(3, "2026-10-09 10:00:02")
    store.add({PersonName("太郎"): [a]})
    change = store.update({PersonName("太郎"): [a, b, c]}, {"次郎": {a.key}, "三郎": {("x", "y")}})
    assert change.removed == {}
    assert change.added == {"太郎": {b.key, c.key}}  # a は既にあり、上限 2 で a が押し出される
    change = store.update({PersonName("次郎"): [_sample(4, "2026-10-09 10:00:03")]}, {"太郎": {b.key, a.key}})
    assert change.removed == {"太郎": {b.key}} and set(change.added) == {"次郎"}


def test_update_refuses_broken_file(store) -> None:
    with open(store.path, "w", encoding="utf-8") as f:
        f.write("{broken")
    with pytest.raises(VoiceprintStoreError):
        store.update({PersonName("次郎"): [_sample(1)]}, {"太郎": {("a", "b")}})
    with open(store.path, encoding="utf-8") as f:
        assert f.read() == "{broken"


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


def test_relocate_source_all_and_range(store) -> None:
    old, new = "transcript-202610091000.txt", "transcript-202610091000@acme.txt"
    mk = lambda seed, ts, src: VoiceSample(_sample(seed).embedding, ts, src)  # noqa: E731
    store.add({PersonName("太郎"): [mk(1, "2026-10-09 10:00:01", old), mk(2, "2026-10-09 10:00:09", old),
                                    mk(3, "2026-10-09 10:00:01", "other.txt")]})
    assert store.relocate_source(old, new, ("2026-10-09 10:00:05", "2026-10-09 10:00:10")) == 1
    keys = {s.key for s in store.samples(PersonName("太郎"))}
    assert keys == {(old, "2026-10-09 10:00:01"), (new, "2026-10-09 10:00:09"), ("other.txt", "2026-10-09 10:00:01")}
    assert store.relocate_source(old, new) == 1
    assert {s.source for s in store.samples(PersonName("太郎"))} == {new, "other.txt"}
    assert store.relocate_source(old, new) == 0


def _cluster_samples(n_main: int = 40) -> list[VoiceSample]:
    rng = np.random.default_rng(0)
    base = rng.normal(size=256)
    base /= np.linalg.norm(base)
    far = rng.normal(size=256)
    far /= np.linalg.norm(far)
    out = []
    for i, b in enumerate([base] * n_main + [far]):
        v = b + rng.normal(scale=0.06, size=256)
        out.append(VoiceSample((v / np.linalg.norm(v)).astype(np.float32), f"2026-10-09 10:00:{i:02d}", "t.txt"))
    return out


def test_update_marks_outliers_and_keeps_kept(store) -> None:
    samples = _cluster_samples()
    far = samples[-1]
    change = store.update({PersonName("太郎"): samples}, {})
    assert change.added["太郎"] == {s.key for s in samples}
    got = {s.key: s.status for s in store.samples(PersonName("太郎"))}
    assert got[far.key] is SampleStatus.OUTLIER
    assert {st for k, st in got.items() if k != far.key} == {SampleStatus.NORMAL}
    assert store.set_status("太郎", {far.key}, SampleStatus.KEPT) == 1
    store.update({PersonName("太郎"): [_sample(99, "2026-10-09 11:00:00")]}, {})
    assert {s.key: s.status for s in store.samples(PersonName("太郎"))}[far.key] is SampleStatus.KEPT


def test_set_status_unknown_person_or_keys(store) -> None:
    assert store.set_status("nobody", {("a", "b")}, SampleStatus.KEPT) == 0
