"""shadow-clerk domain: talk mode で monitor に戻ってきた Claude 自身の声を見分ける

手元で鳴らした Claude の読み上げは monitor にも入る。いつ・何を鳴らしたかは分かっているので、
monitor の1行が読み上げの時間帯に重なり、かつ読み上げた文と似ていれば、Claude の声の文字起こしとみなす。
"""
from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

_DROP = re.compile(r"[\s\W_]+", re.UNICODE)


def normalize_for_echo(text: str) -> str:
    """比べる前に、空白・句読点・記号を除き、全角半角をそろえ、英字を小文字にする"""
    return _DROP.sub("", unicodedata.normalize("NFKC", text)).lower()


@dataclass(frozen=True)
class SpokenSpan:
    """実際に鳴った1文。start / end は epoch 秒"""

    start: float
    end: float
    text: str


class EchoFilter:
    def __init__(self, tail_sec: float = 3.0, similarity: float = 0.5, keep_sec: float = 60.0) -> None:
        self._tail = tail_sec
        self._similarity = similarity
        self._keep = keep_sec
        self._spans: list[SpokenSpan] = []
        self._lock = threading.Lock()

    def record(self, span: SpokenSpan) -> None:
        with self._lock:
            self._spans.append(span)
            horizon = span.end - self._keep
            self._spans = [s for s in self._spans if s.end >= horizon]

    def is_echo(self, seg_start: float, seg_end: float, text: str) -> bool:
        """区間が読み上げ（終了後 tail_sec を含む）と重なり、文がその読み上げに含まれていれば真"""
        heard = normalize_for_echo(text)
        if not heard:
            return False
        with self._lock:
            spoken = "".join(normalize_for_echo(s.text) for s in self._spans
                             if s.start <= seg_end and seg_start <= s.end + self._tail)
        if not spoken:
            return False
        matched = sum(b.size for b in SequenceMatcher(None, heard, spoken, autojunk=False).get_matching_blocks())
        return matched / len(heard) >= self._similarity
