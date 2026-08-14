"""AudioLevel / CaptureLevel の検証

実行: uv run python tests/test_audio_level.py
音声デバイスを必要としない（合成波形のみ）。
"""
from __future__ import annotations
import math
import time

import numpy as np

from shadow_clerk._daemon_audio_level import CaptureLevel
from shadow_clerk.domain import AudioLevel

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def measure(samples: np.ndarray) -> AudioLevel:
    lv = CaptureLevel()
    lv.add(samples)
    return lv.snapshot()


n = 16000
t = np.arange(n) / 16000.0

# 無音: rms も peak も 0、crest は 0 除算を避けて 0
silence = measure(np.zeros(n, dtype=np.int16))
check("1. 無音の rms=0", silence.rms == 0.0, f"{silence.rms}")
check("2. 無音の crest=0 (0除算しない)", silence.crest == 0.0, f"{silence.crest}")

# 正弦波: crest = peak/rms = √2 ≒ 1.41
sine = measure((10000 * np.sin(2 * math.pi * 440 * t)).astype(np.int16))
check("3. 正弦波の crest ≒ 1.41", 1.30 < sine.crest < 1.55, f"{sine.crest:.2f}")

# 定常ノイズ: crest は 1〜2 の低い値に収まる（今回の障害の内蔵マイク相当）
rng = np.random.default_rng(12345)
noise = measure(rng.normal(0, 2000, n).astype(np.int16))
check("4. 定常ノイズの crest < 5", noise.crest < 5.0, f"{noise.crest:.2f}")

# バースト（音声相当）: 大半が無音で一部だけ大きい → crest が高い
burst = np.zeros(n, dtype=np.int16)
burst[:800] = 15000
check("5. バースト（正方向）の crest > 3", measure(burst).crest > 3.0,
      f"{measure(burst).crest:.2f}")

# 負方向のバースト。peak は np.abs() を通さないと data.max() が 0 のまま
# crest=0 になってしまう（符号の取り扱いを固定するための対称チェック）
burst_neg = np.zeros(n, dtype=np.int16)
burst_neg[:800] = -15000
check("6. バースト（負方向）の crest > 3", measure(burst_neg).crest > 3.0,
      f"{measure(burst_neg).crest:.2f}")

# snapshot は窓をリセットする
lv = CaptureLevel()
lv.add(np.full(1000, 5000, dtype=np.int16))
first = lv.snapshot()
second = lv.snapshot()
check("7. snapshot で窓がリセットされる", first.rms > 0 and second.rms == 0.0,
      f"1回目={first.rms:.0f} 2回目={second.rms:.0f}")

# idle_sec は add からの経過を返す
lv2 = CaptureLevel()
lv2.add(np.zeros(10, dtype=np.int16))
time.sleep(0.2)
check("8. idle_sec が経過を返す", 0.15 < lv2.idle_sec() < 1.0, f"{lv2.idle_sec():.2f}")

# AudioLevel は不変
try:
    AudioLevel(rms=1.0, peak=2.0, crest=2.0).rms = 9.0  # type: ignore[misc]
    check("9. AudioLevel は不変", False, "代入できてしまった")
except Exception:
    check("9. AudioLevel は不変", True)

# 元の check「levels に mic と monitor がある」は、_RecorderCaptureMixin.__init__
# を呼ばず levels を自分で代入する偽ホストを使っていたため、実際の __init__ が
# それを作ることは何も検証していなかった（Finding C: tautological）。
# 実 __init__ は argparse.Namespace・Transcriber・backend 検出・config 読み込みなど
# 重い依存を要求し、この軽量テストで構築するのは割に合わない。ソースを読んで
# 「__init__ はこう書かれているはず」と断定するのも実行時の検証にならないため、
# 何も保証しないチェックを残すより削除する方を選んだ。

# --- _CaptureStream のコールバックが level を更新する ---
import queue as _queue

from shadow_clerk import _daemon_recorder_capture as cap

dev = __import__("shadow_clerk.domain", fromlist=["AudioDevice"]).AudioDevice(index=0, name="x")
lv = CaptureLevel()
st = cap._CaptureStream("mic", dev, _queue.Queue(), level=lv)
st._callback(np.full((480, 1), 3000, dtype=np.int16), 480, None, None)
snap = lv.snapshot()
check("10. コールバックが level を更新する", snap.rms > 0, f"rms={snap.rms:.0f}")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
