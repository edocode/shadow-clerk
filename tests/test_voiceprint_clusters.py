"""声紋サンプルの塊分けのテスト"""
from __future__ import annotations

import numpy as np

import shadow_clerk._daemon_voiceprint_clusters as cl
from shadow_clerk._daemon_voiceprint_clusters import ClusterKind, cluster_samples

DIM = 256


def unit(v: np.ndarray) -> np.ndarray:
    return v / np.linalg.norm(v)


def bases(n: int, seed: int = 0) -> list[np.ndarray]:
    return [unit(v) for v in np.random.default_rng(seed).normal(size=(n, DIM))]


def around(base: np.ndarray, n: int, seed: int, sigma: float = 0.06) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    return [unit(base + rng.normal(scale=sigma, size=DIM)) for _ in range(n)]


def by_kind(clusters: list, kind: ClusterKind) -> list:
    return [c for c in clusters if c.kind is kind]


def test_single_cluster_below_min_samples(monkeypatch) -> None:
    monkeypatch.setattr(cl, "load_config", lambda: {})
    b = bases(2)
    out = cluster_samples(around(b[0], 8, 1) + [b[1]])
    assert len(out) == 1 and out[0].kind is ClusterKind.MAIN
    assert out[0].members == tuple(range(9)) and out[0].similarity == 1.0


def test_main_and_outlier(monkeypatch) -> None:
    monkeypatch.setattr(cl, "load_config", lambda: {})
    b = bases(2)
    out = cluster_samples(around(b[0], 60, 1) + [b[1]])
    assert [c.kind for c in out] == [ClusterKind.MAIN, ClusterKind.OUTLIER]
    assert len(out[0].members) == 60 and out[1].members == (60,)


def test_main_and_different(monkeypatch) -> None:
    monkeypatch.setattr(cl, "load_config", lambda: {})
    b = bases(2)
    out = cluster_samples(around(b[0], 50, 1) + around(b[1], 10, 2))
    assert [c.kind for c in out] == [ClusterKind.MAIN, ClusterKind.DIFFERENT]
    assert len(out[0].members) == 50 and len(out[1].members) == 10
    assert out[1].similarity < 0.5


def test_close_cluster_merged_into_main(monkeypatch) -> None:
    monkeypatch.setattr(cl, "load_config", lambda: {})
    b = bases(2)
    near = unit(0.7 * b[0] + 0.714 * unit(b[1] - (b[1] @ b[0]) * b[0]))
    out = cluster_samples(around(b[0], 50, 1) + around(near, 3, 2))
    assert len(out) == 1 and out[0].kind is ClusterKind.MAIN and len(out[0].members) == 53


def test_ratio_and_count_both_required(monkeypatch) -> None:
    monkeypatch.setattr(cl, "load_config", lambda: {})
    b = bases(2)
    out = cluster_samples(around(b[0], 38, 1) + around(b[1], 2, 2))
    assert [c.kind for c in out] == [ClusterKind.MAIN, ClusterKind.DIFFERENT]


def test_remaining_clusters_sorted_by_size(monkeypatch) -> None:
    monkeypatch.setattr(cl, "load_config", lambda: {})
    b = bases(3)
    out = cluster_samples(around(b[0], 40, 1) + around(b[1], 4, 2) + around(b[2], 8, 3))
    assert [len(c.members) for c in out] == [40, 8, 4]


def test_count_limit_fails_while_ratio_holds(monkeypatch) -> None:
    monkeypatch.setattr(cl, "load_config", lambda: {})
    b = bases(2)
    out = cluster_samples(around(b[0], 117, 1) + around(b[1], 3, 2))  # 3/120 = 2.5% but 3 > outlier_max
    assert [c.kind for c in out] == [ClusterKind.MAIN, ClusterKind.DIFFERENT]
