"""Shadow-clerk daemon: 会議内クラスタと登録済み声紋の照合（Phase B）

誤った名前を断定しないことを当たる率より優先する。HIGH は名前、LOW は「名前?」、NONE は会議内ラベルのまま。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_voiceprint_clusters import majority_shape, voiceprint_number

_TOP_K = 3


class Confidence(str, Enum):
    HIGH = "high"
    LOW = "low"
    NONE = "none"


@dataclass(frozen=True)
class MatchResult:
    confidence: Confidence
    name: str | None
    score: float
    margin: float

    def display_label(self, cluster_label: str) -> str:
        match self.confidence:
            case Confidence.HIGH:
                return str(self.name)
            case Confidence.LOW:
                return f"{self.name}?"
        return cluster_label


_NO_MATCH = MatchResult(Confidence.NONE, None, 0.0, 0.0)


def _score(emb: np.ndarray, pool: np.ndarray) -> float:
    """塊の各埋め込みについて声紋との上位 3 件平均を取り、塊内で平均する"""
    sims = emb @ pool.T  # (n_cluster, n_pool)
    k = min(_TOP_K, sims.shape[1])
    return float(np.sort(sims, axis=1)[:, -k:].mean())


def _unit_rows(emb: np.ndarray) -> np.ndarray:
    """各行を L2 正規化した float32。ゼロ・非有限の行は捨てる"""
    if emb.ndim != 2:
        return np.empty((0, 0), dtype=np.float32)
    norms = np.linalg.norm(emb, axis=1)
    ok = np.isfinite(norms) & (norms > 1e-8)
    return (emb[ok] / norms[ok, None]).astype(np.float32)


def match_cluster(cluster: list[np.ndarray], pools: dict[str, np.ndarray], attendees: set[str]) -> MatchResult:
    cfg = load_config()
    min_n = max(voiceprint_number(cfg, "voiceprint_min_utterances"), 1)
    if not pools or len(cluster) < min_n:
        return _NO_MATCH
    emb = _unit_rows(np.asarray([cluster[i] for i in majority_shape(cluster)], dtype=np.float64))
    if len(emb) < min_n:
        return _NO_MATCH
    scores = sorted(((_score(emb, p), n) for n, p in pools.items() if p.ndim == 2 and p.shape[1] == emb.shape[1]),
                    reverse=True)
    if not scores:
        return _NO_MATCH
    score, name = scores[0]
    margin = score - scores[1][0] if len(scores) > 1 else float("inf")
    # 負の値は閾値を下げて名前を出しやすくするだけなので 0 で止める
    extra = 0.0 if name in attendees else max(voiceprint_number(cfg, "voiceprint_non_attendee_penalty"), 0.0)
    if (score >= voiceprint_number(cfg, "voiceprint_high") + extra
            and margin >= max(voiceprint_number(cfg, "voiceprint_margin"), 0.0)):
        return MatchResult(Confidence.HIGH, name, score, margin)
    if score >= voiceprint_number(cfg, "voiceprint_low") + extra:
        return MatchResult(Confidence.LOW, name, score, margin)
    return MatchResult(Confidence.NONE, None, score, margin)
