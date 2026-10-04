"""shadow-clerk domain: talk mode で monitor に戻ってきた Claude 自身の声を見分ける

手元で鳴らした Claude の読み上げは monitor にも入る。いつ鳴らしたかは分かっているので、
monitor の1行が読み上げの時間帯（各文の終了後 tail_sec を含む）に重なれば、本文に関わらず Claude の声とみなす。
読み上げ中に相手がかぶせて話した発言も失われるが、これは承知の上で採る（短い発言や相槌は文の類似では
見分けられず、Claude の声が [相手] として漏れたため）。

判定に使うのは VAD が測った monitor 区間の開始時刻。VAD は無音で区間を分けるので、Claude の反響の区間は
読み上げ中に始まって捨てられ、monitor が静かになった後に始まる区間は新しい発言として残る。tail_sec は出力と録音の遅れ
（バッファ 0.2〜0.3 秒）を吸収できればよい（1 秒だと Claude が話し終えた直後の返事まで捨てていた）。
既知の限界: Claude の直後に無音を挟まず相手が話し始めると、VAD が両方を1区間にまとめ、その区間は捨てられる。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class SpokenSpan:
    """実際に鳴った1文。start / end は epoch 秒"""

    start: float
    end: float
    text: str


class EchoFilter:
    """読み上げ履歴を持ち、monitor の区間が Claude の読み上げ中（終了後 tail_sec まで）かを判定する"""

    def __init__(self, tail_sec: float = 0.3, keep_sec: float = 60.0) -> None:
        self._tail = tail_sec
        self._keep = keep_sec
        self._spans: list[SpokenSpan] = []
        self._lock = threading.Lock()

    def record(self, span: SpokenSpan) -> None:
        with self._lock:
            self._spans.append(span)
            horizon = span.end - self._keep
            self._spans = [s for s in self._spans if s.end >= horizon]

    def overlaps(self, seg_start: float, seg_end: float) -> bool:
        """区間が読み上げ（終了後 tail_sec を含む）と重なるか。重なれば本文に関わらず Claude の声として扱う"""
        with self._lock:
            return any(s.start <= seg_end and seg_start <= s.end + self._tail for s in self._spans)
