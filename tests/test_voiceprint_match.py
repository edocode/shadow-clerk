"""会議内クラスタと声紋の照合のテスト"""
from __future__ import annotations

import numpy as np
import pytest

import shadow_clerk._daemon_voiceprint_match as match_mod
from shadow_clerk._daemon_voiceprint_match import Confidence, MatchResult, match_cluster

D = 256


def _basis(i: int) -> np.ndarray:
    v = np.zeros(D, dtype=np.float32)
    v[i] = 1.0
    return v


def _at(i: int, cos: float, k: int = 100) -> np.ndarray:
    """基底 i とのコサインが cos の単位ベクトル（直交成分は k 番目の基底）"""
    return (cos * _basis(i) + np.sqrt(1 - cos**2) * _basis(k)).astype(np.float32)


def _pools(*idx: int) -> dict[str, np.ndarray]:
    names = ["alice", "bob", "carol"]
    return {names[j]: np.stack([_basis(i)] * 4) for j, i in enumerate(idx)}


@pytest.fixture(autouse=True)
def _cfg(monkeypatch) -> None:
    monkeypatch.setattr(match_mod, "load_config", lambda: {})


def test_high_for_clear_match() -> None:
    r = match_cluster([_at(0, 0.8), _at(0, 0.8)], _pools(0, 1), {"alice", "bob"})
    assert r.confidence is Confidence.HIGH and r.name == "alice" and r.score == pytest.approx(0.8, abs=1e-4)
    assert r.margin == pytest.approx(0.8, abs=1e-4)


def test_low_between_thresholds() -> None:
    r = match_cluster([_at(0, 0.55)] * 2, _pools(0, 1), {"alice"})
    assert r.confidence is Confidence.LOW and r.name == "alice"


def test_none_below_low() -> None:
    r = match_cluster([_at(0, 0.4)] * 2, _pools(0, 1), {"alice"})
    assert r.confidence is Confidence.NONE and r.name is None


def test_margin_too_small_is_not_high() -> None:
    near = _at(0, 0.97, 1)
    pools = {"alice": np.stack([_basis(0)] * 3), "bob": np.stack([near] * 3)}
    r = match_cluster([_basis(0)] * 2, pools, {"alice", "bob"})
    assert r.score == pytest.approx(1.0) and r.margin == pytest.approx(0.03, abs=1e-4)
    assert r.confidence is Confidence.LOW and r.name == "alice"


def test_non_attendee_penalty_raises_bar() -> None:
    cluster = [_at(0, 0.62)] * 2
    assert match_cluster(cluster, _pools(0), {"alice"}).confidence is Confidence.HIGH
    assert match_cluster(cluster, _pools(0), {"bob"}).confidence is Confidence.LOW
    assert match_cluster(cluster, _pools(0), set()).confidence is Confidence.LOW


def test_non_attendee_still_identified_when_strong() -> None:
    assert match_cluster([_at(0, 0.8)] * 2, _pools(0), set()).confidence is Confidence.HIGH


def test_non_attendee_low_threshold_also_raised() -> None:
    assert match_cluster([_at(0, 0.52)] * 2, _pools(0), {"alice"}).confidence is Confidence.LOW
    assert match_cluster([_at(0, 0.52)] * 2, _pools(0), set()).confidence is Confidence.NONE


def test_min_utterances() -> None:
    assert match_cluster([_at(0, 0.8)], _pools(0), {"alice"}).confidence is Confidence.NONE
    assert match_cluster([_at(0, 0.8)] * 2, _pools(0), {"alice"}).confidence is Confidence.HIGH


def test_no_pools_none() -> None:
    assert match_cluster([_at(0, 0.8)] * 2, {}, set()).confidence is Confidence.NONE


def test_top3_mean_per_embedding() -> None:
    pools = {"alice": np.stack([_basis(0), _basis(0), _basis(0), _basis(5), _basis(6)])}
    r = match_cluster([_basis(0)] * 2, pools, {"alice"})
    assert r.score == pytest.approx(1.0)
    pools = {"alice": np.stack([_basis(0), _basis(5), _basis(6), _basis(7)])}
    assert match_cluster([_basis(0)] * 2, pools, {"alice"}).score == pytest.approx(1 / 3)


def test_mismatched_dimension_ignored() -> None:
    pools = {"alice": np.stack([_basis(0)] * 3), "bob": np.ones((3, 8), dtype=np.float32) / np.sqrt(8)}
    r = match_cluster([_basis(0), _basis(0), np.ones(8, dtype=np.float32)], pools, {"alice"})
    assert r.name == "alice" and r.confidence is Confidence.HIGH


def test_display_label() -> None:
    assert MatchResult(Confidence.HIGH, "alice", 0.9, 0.5).display_label("相手A") == "alice"
    assert MatchResult(Confidence.LOW, "alice", 0.55, 0.5).display_label("相手A") == "alice?"
    assert MatchResult(Confidence.NONE, None, 0.1, 0.0).display_label("相手A") == "相手A"
