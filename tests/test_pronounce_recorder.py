"""お手本の gate と、文字起こしスレッドからワーカーへの受け渡しの検証

実行: uv run python tests/test_pronounce_recorder.py
モデルも音声デバイスも不要。
"""
from __future__ import annotations
import os
import sys
import tempfile
import threading

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-pronounce-rec-")

from shadow_clerk._daemon_talk import _PlaybackSpan  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_span_open_while_speaking() -> None:
    span = _PlaybackSpan(tail_sec=0.3)
    check("何も鳴っていなければ素通し", not span.covers(100.0))
    span.open(100.0)
    check("読み上げ中に始まったセグメントは捨てる", span.covers(100.5))
    # 長い課題文の途中で VAD が閉じると、セグメントは読み上げの終了前に届く。
    # 「終わってから記録」にするとここが素通りする（設計書 §8.1 の本題）
    check("読み上げ中なら、いつ始まったものでも捨てる", span.covers(103.0))
    check("読み上げの前に始まったものは残す", not span.covers(99.9))
    span.close(101.8)
    check("実終了 + tail までは捨てる", span.covers(102.0))
    # 見積もりは 8 文字/秒なので "Turn right at the light." なら 3.0 秒。
    # 実際は 1.8 秒で終わる。ユーザーが 2.3 秒で言い始めた試行を捨ててはいけない
    check("実終了のあとに始まったセグメントは残す", not span.covers(102.3),
          "見積もりベースだと 103.0 まで捨ててしまう")


def test_span_reopens() -> None:
    span = _PlaybackSpan(tail_sec=0.3)
    span.open(100.0)
    span.close(101.0)
    span.open(105.0)
    check("次の文で開き直す", span.covers(105.5))
    check("前の区間は残らない", not span.covers(102.0))


def test_span_keeps_earlier_sentences() -> None:
    # お手本は文ごとに open/close される（TtsPlayer が文単位でキューに積むため）。
    # 文1の最中に VAD が閉じたセグメントは、文字起こしを終えて届く頃には文2が始まっている。
    # 1区間だけ保持して上書きすると、ここで素通りしてお手本を学習者の発話として解析してしまう
    span = _PlaybackSpan(tail_sec=0.3)
    span.open(100.0)
    span.close(101.0)          # 文1
    span.open(101.5)           # 文2が鳴り始めた
    check("文1の最中に始まったセグメントは、文2が始まった後でも捨てる", span.covers(100.5))
    check("文2の最中も捨てる", span.covers(101.8))
    span.close(102.4)
    check("すべて鳴り終わった後に始まったセグメントは残す", not span.covers(102.9))
    check("文1より前に始まったセグメントは残す", not span.covers(99.5))


def test_span_prunes_old_entries() -> None:
    # 履歴が無限に伸びないこと
    span = _PlaybackSpan(tail_sec=0.3, keep_sec=1.0)
    for i in range(50):
        span.open(1000.0 + i)
        span.close(1000.3 + i)
    span.open(2000.0)
    check("古い区間は捨てる", not span.covers(1000.1), "1000.1 は 1000 秒前の区間")
    check("直近は残る", span.covers(2000.5))


def test_player_opens_and_closes_span() -> None:
    from shadow_clerk._daemon_tts import TtsPlayer

    spans: list[tuple[float, float | None]] = []
    played: list[int] = []

    class _Backend:
        LANGUAGES = ()
        DEFAULT_LANGUAGE = None

        def check(self) -> None: ...
        def synthesize(self, text: str):
            return np.zeros(1600, dtype=np.float32), 16000
        def credit(self) -> str:
            return ""
        def voices(self) -> list:
            return []

    done = threading.Event()

    def _play(pcm, sr, should_stop) -> None:
        played.append(len(pcm))
        done.set()

    player = TtsPlayer(_Backend(), _play, lambda msg: None)
    player.set_on_span(lambda start, end: spans.append((start, end)))
    player.speak("hello")
    done.wait(5.0)
    player.close(discard_pending=False)
    check("開いて閉じる、の2回呼ばれる", len(spans) == 2, repr(spans))
    check("1回目は未終了", spans and spans[0][1] is None, repr(spans))
    check("2回目は実終了", len(spans) == 2 and spans[1][1] is not None, repr(spans))
    check("開始時刻は同じ", len(spans) == 2 and spans[0][0] == spans[1][0], repr(spans))
    check("実終了は開始より後", len(spans) == 2 and spans[1][1] >= spans[1][0], repr(spans))


if __name__ == "__main__":
    test_span_open_while_speaking()
    test_span_reopens()
    test_span_keeps_earlier_sentences()
    test_span_prunes_old_entries()
    test_player_opens_and_closes_span()
    sys.exit(0 if all(results) else 1)
