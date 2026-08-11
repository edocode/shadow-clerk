"""shadow-clerk: 音声レベル（バリューオブジェクト）"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioLevel:
    """直近 1 秒の入力レベル。

    crest（クレストファクタ = peak / rms）は「デバイスは開けているがノイズしか
    来ていない」状態の判別に使う。音声なら 3〜10 以上、定常ノイズなら 1〜2。
    rms が微小なときは 0 とする（無音で発散させないため）。
    """

    rms: float
    peak: float
    crest: float
