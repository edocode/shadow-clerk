"""VADSegmenter のプリロールの検証

実行: uv run python tests/test_vad_pre_roll.py
webrtcvad の判定は差し替える（フレームの値が 1000 以上なら音声）。音声デバイスは不要。
"""
from __future__ import annotations

import numpy as np

from shadow_clerk._daemon_constants import (
    FRAME_DURATION_MS, FRAME_SIZE, SAMPLE_RATE, SILENCE_FRAMES_THRESHOLD, SPEECH_FRAMES_THRESHOLD,
    VAD_PRE_ROLL_FRAMES,
)
from shadow_clerk._daemon_vad import VADSegmenter

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class FakeVad:
    def is_speech(self, raw: bytes, rate: int) -> bool:
        return int(np.frombuffer(raw[:2], dtype=np.int16)[0]) >= 1000


def segmenter() -> VADSegmenter:
    seg = VADSegmenter()
    seg.vad = FakeVad()
    return seg


def frame(value: int) -> np.ndarray:
    return np.full(FRAME_SIZE, value, dtype=np.int16)


def run(seg: VADSegmenter, values: list[int]) -> np.ndarray | None:
    out = None
    for i, v in enumerate(values):
        if (got := seg.process_frame(frame(v), i * FRAME_DURATION_MS / 1000.0)) is not None:
            out = got
    return out


def heads(segment: np.ndarray) -> list[int]:
    return [int(segment[i]) for i in range(0, len(segment), FRAME_SIZE)]


speech = [1000 + i for i in range(SPEECH_FRAMES_THRESHOLD + 5)]
silence = [0] * SILENCE_FRAMES_THRESHOLD

# 1. 発話の直前の非音声フレーム（弱い子音）が頭に付く
before = list(range(1, VAD_PRE_ROLL_FRAMES + 6))
seg = segmenter()
got = run(seg, before + speech + silence)
expected_head = before[-VAD_PRE_ROLL_FRAMES:]
check("1. 直前の非音声がプリロールとして頭に付く",
      got is not None and heads(got)[:VAD_PRE_ROLL_FRAMES] == expected_head,
      f"{heads(got)[:VAD_PRE_ROLL_FRAMES] if got is not None else None}")
check("2. プリロールより古いフレームは付かない",
      got is not None and heads(got)[VAD_PRE_ROLL_FRAMES] == speech[0])
check("3. last_pre_roll_sec がプリロールの長さ",
      abs(seg.last_pre_roll_sec - VAD_PRE_ROLL_FRAMES * FRAME_DURATION_MS / 1000.0) < 1e-9,
      f"{seg.last_pre_roll_sec}")

# 4. 検出前に途切れた音声（音声→非音声→音声）も捨てずに頭に残る
broken = [1500, 1501, 7, 1502]
got = run(segmenter(), broken + speech + silence)
check("4. 検出に届かず途切れた音声もプリロールに残る",
      got is not None and heads(got)[:len(broken)] == broken,
      f"{heads(got)[:len(broken)] if got is not None else None}")

# 5. 前のセグメントの末尾がプリロールとして重複しない
seg = segmenter()
run(seg, speech + silence)
got = run(seg, speech + silence)
check("5. 確定直後の発話にはプリロールが付かない",
      got is not None and heads(got)[0] == speech[0] and seg.last_pre_roll_sec == 0.0)

# 6. voice_onset はプリロールを除いた声の開始
seg = segmenter()
got = run(seg, before + speech + silence)
assert got is not None
end = 100.0
onset = seg.voice_onset(got, end)
check("6. voice_onset はプリロールの分だけ後ろ",
      abs(onset - (end - len(got) / SAMPLE_RATE + seg.last_pre_roll_sec)) < 1e-9
      and onset > end - len(got) / SAMPLE_RATE, f"{onset}")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
