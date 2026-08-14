"""shadow-clerk daemon: 入力レベルの集計"""
from __future__ import annotations

import time

import numpy as np

from shadow_clerk.domain import AudioLevel

# rms がこの値未満なら実質無音とみなし、crest を 0 にする（0 除算回避）
_SILENCE_RMS = 1.0


class CaptureLevel:
    """1 秒窓の入力レベルを集計する。

    音声コールバック（毎秒約33回）から `add()` され、配信スレッドから
    `snapshot()` される。GIL 下の単純な数値更新のみで、ロックは持たない
    ——取りこぼしても次の窓で回復するため、厳密さより軽さを優先する。
    """

    def __init__(self) -> None:
        self._sum_sq = 0.0
        self._count = 0
        self._peak = 0.0
        self._last_add = time.monotonic()

    def add(self, samples: np.ndarray) -> None:
        """フレームを取り込む。音声コールバック内から呼ばれる。"""
        data = samples.astype(np.float32)
        self._sum_sq += float(np.dot(data, data))
        self._count += len(data)
        self._peak = max(self._peak, float(np.abs(data).max(initial=0.0)))
        self._last_add = time.monotonic()

    def idle_sec(self) -> float:
        """最後に add されてからの経過秒数。

        CLOCK_MONOTONIC はサスペンド中進まないため、レジューム直後に
        サスペンド時間で誤検知することはない。
        """
        return time.monotonic() - self._last_add

    def snapshot(self) -> AudioLevel:
        """直近の窓を返して窓をリセットする。"""
        count, sum_sq, peak = self._count, self._sum_sq, self._peak
        self._count, self._sum_sq, self._peak = 0, 0.0, 0.0
        if not count:
            return AudioLevel(rms=0.0, peak=0.0, crest=0.0)
        rms = (sum_sq / count) ** 0.5
        crest = peak / rms if rms >= _SILENCE_RMS else 0.0
        return AudioLevel(rms=rms, peak=peak, crest=crest)
