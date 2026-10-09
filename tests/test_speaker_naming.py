"""名前付けの純粋な処理のテスト"""
from __future__ import annotations

from shadow_clerk._daemon_speaker_naming import (
    LabelSummary, relabel_lines, remap_offset, summarize_labels,
)
from shadow_clerk.domain.transcript_line import TranscriptLine
from shadow_clerk.domain.voiceprint import PersonName

LINES = [
    "--- 会議開始 2026-10-09 10:00 ---\n",
    "[2026-10-09 10:00:01] [相手B] はい\n",
    "[2026-10-09 10:00:02] [相手A] 来週のリリースの件ですが\n",
    "[2026-10-09 10:00:03] [自分] どうぞ\n",
    "[2026-10-09 10:00:04] [相手A] 短い\n",
    "[2026-10-09 10:00:05] [相手?] うん\n",
    "[2026-10-09 10:00:06] [相手27] それでお願いします\n",
    "[2026-10-09 10:00:07] [相手C] 資料は共有済みです\n",
    "[2026-10-09 10:00:08] [次郎] 了解\n",
    "[2026-10-09 10:00:09] [相手] 分離なし\n",
]


def test_summarize_labels() -> None:
    assert summarize_labels(LINES) == [
        LabelSummary("相手A", 2, "来週のリリースの件ですが"),
        LabelSummary("相手B", 1, "はい"),
        LabelSummary("相手C", 1, "資料は共有済みです"),
        LabelSummary("相手27", 1, "それでお願いします"),
    ]


def test_relabel_many_to_one() -> None:
    taro = PersonName("太郎")
    new, n = relabel_lines(LINES, {"相手A": taro, "相手C": taro})
    assert n == 3 and len(new) == len(LINES)
    assert new[0] == LINES[0] and new[3] == LINES[3] and new[5] == LINES[5]
    parsed = TranscriptLine.parse(new[2])
    assert parsed is not None and parsed.speaker_label == "太郎" and parsed.text == "来週のリリースの件ですが"
    assert new[7] == "[2026-10-09 10:00:07] [太郎] 資料は共有済みです\n"


def _bytes(lines: list[str]) -> int:
    return sum(len(x.encode("utf-8")) for x in lines)


def test_remap_offset() -> None:
    new, _ = relabel_lines(LINES, {"相手A": PersonName("太郎")})
    assert remap_offset(LINES, new, 0) == 0
    assert remap_offset(LINES, new, _bytes(LINES)) == _bytes(new)
    assert remap_offset(LINES, new, _bytes(LINES[:3])) == _bytes(new[:3])
    assert remap_offset(LINES, new, _bytes(LINES[:2])) == _bytes(new[:2])
    mid = _bytes(LINES[:2]) + 5
    assert remap_offset(LINES, new, mid) == _bytes(new[:2]) + 5
