"""Shadow-clerk daemon: 声紋サンプルの塊分け

人ごとの声紋サンプルを平均連結の凝集型クラスタリングで塊に分け、いつもの声（MAIN）・
別の声（DIFFERENT）・少数で遠い外れ値（OUTLIER）に分類する。
"""
from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from enum import Enum

import numpy as np

from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_constants import DEFAULT_CONFIG

logger = logging.getLogger("shadow-clerk")


class ClusterKind(str, Enum):
    MAIN = "main"
    DIFFERENT = "different"
    OUTLIER = "outlier"


@dataclass(frozen=True)
class SampleCluster:
    kind: ClusterKind
    members: tuple[int, ...]  # 入力リストの添字
    similarity: float  # 主の塊の重心とのコサイン類似度（MAIN は 1.0）


def _average_linkage(emb: np.ndarray, max_distance: float) -> list[list[int]]:
    """コサイン距離の平均連結。最小の塊間距離が max_distance 以下の間、その 2 つを併合する"""
    n = len(emb)
    dist = 1.0 - emb @ emb.T
    np.fill_diagonal(dist, np.inf)
    groups: dict[int, list[int]] = {i: [i] for i in range(n)}
    while len(groups) > 1:
        i, j = np.unravel_index(np.argmin(dist), dist.shape)
        if dist[i, j] > max_distance:
            break
        ni, nj = len(groups[i]), len(groups[j])
        merged = (ni * dist[i] + nj * dist[j]) / (ni + nj)  # Lance–Williams
        dist[i, :], dist[:, i] = merged, merged
        dist[i, i] = np.inf
        dist[j, :], dist[:, j] = np.inf, np.inf
        groups[i] = sorted(groups[i] + groups.pop(j))
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))


def _centroid(emb: np.ndarray, members: list[int]) -> np.ndarray:
    c = emb[members].mean(axis=0)
    return c / max(float(np.linalg.norm(c)), 1e-12)


def majority_shape(embeddings: list[np.ndarray]) -> list[int]:
    """多数派の次元の埋め込みの添字。次元違い（モデル変更・壊れた行）は塊分けに混ぜられない"""
    if not embeddings:
        return []
    shape = Counter(e.shape for e in embeddings).most_common(1)[0][0]
    return [i for i, e in enumerate(embeddings) if e.shape == shape]


def cluster_samples(embeddings: list[np.ndarray]) -> list[SampleCluster]:
    """MAIN を先頭に、残りは件数の多い順。しきい値は config（なければ既定値）から読む"""
    cfg = {**DEFAULT_CONFIG, **load_config()}
    n = len(embeddings)
    if n < int(cfg["voiceprint_cluster_min_samples"]):
        return [SampleCluster(ClusterKind.MAIN, tuple(range(n)), 1.0)] if n else []
    emb = np.asarray(embeddings, dtype=np.float32)
    groups = _average_linkage(emb, float(cfg["voiceprint_cluster_distance"]))
    main, main_c = list(groups[0]), _centroid(emb, groups[0])
    out: list[SampleCluster] = []
    for g in groups[1:]:
        sim = float(_centroid(emb, g) @ main_c)
        if sim >= float(cfg["voiceprint_main_similarity"]):
            main += g
        elif len(g) <= int(cfg["voiceprint_outlier_max"]) and len(g) / n <= float(cfg["voiceprint_outlier_ratio"]):
            out.append(SampleCluster(ClusterKind.OUTLIER, tuple(g), sim))
        else:
            out.append(SampleCluster(ClusterKind.DIFFERENT, tuple(g), sim))
    return [SampleCluster(ClusterKind.MAIN, tuple(sorted(main)), 1.0), *out]
