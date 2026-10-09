"""Shadow-clerk daemon: 話者の名前付け（会議内ラベル → 人名）の純粋な処理"""
from __future__ import annotations

from dataclasses import dataclass

from shadow_clerk._daemon_speaker_diarization import label_index
from shadow_clerk.domain.speaker import Speaker
from shadow_clerk.domain.transcript_line import TranscriptLine
from shadow_clerk.domain.voiceprint import PersonName


@dataclass(frozen=True)
class LabelSummary:
    label: str
    count: int
    example: str  # 誰だったか思い出せるよう、最長の発話を見せる


def summarize_labels(lines: list[str]) -> list[LabelSummary]:
    """名前付けの対象になる会議内ラベル（相手A 等）を番号順に返す"""
    counts: dict[str, int] = {}
    longest: dict[str, str] = {}
    for line in lines:
        tl = TranscriptLine.parse(line)
        if (tl is None or tl.speaker != Speaker.OTHER or not tl.speaker_label
                or label_index(tl.speaker_label) is None):
            continue
        label = tl.speaker_label
        counts[label] = counts.get(label, 0) + 1
        if len(tl.text) > len(longest.get(label, "")):
            longest[label] = tl.text
    return [LabelSummary(lb, counts[lb], longest[lb]) for lb in sorted(counts, key=label_index)]


def relabel_lines(lines: list[str], mapping: dict[str, PersonName]) -> tuple[list[str], int]:
    """mapping のラベルを名前に書き換えた行と、書き換えた行数を返す。行数は変えない"""
    out: list[str] = []
    renamed = 0
    for line in lines:
        tl = TranscriptLine.parse(line)
        if tl is not None and tl.speaker_label in mapping:
            line = TranscriptLine(tl.timestamp, tl.speaker, tl.text,
                                  mapping[tl.speaker_label].value).format()
            renamed += 1
        out.append(line)
    return out, renamed


def remap_offset(old_lines: list[str], new_lines: list[str], old_offset: int) -> int:
    """書き換え前の translate_offset（バイト）を、書き換え後の同じ位置へ移す。

    名前とラベルはバイト長が違うので、現サイズへのリセットでは未翻訳の末尾を
    翻訳済みとみなし、0 への巻き戻しでは全文を翻訳し直してしまう
    """
    old_pos = new_pos = 0
    for old, new in zip(old_lines, new_lines):
        ob, nb = len(old.encode("utf-8")), len(new.encode("utf-8"))
        if old_pos + ob > old_offset:
            return new_pos + min(old_offset - old_pos, nb)
        old_pos += ob
        new_pos += nb
    return new_pos + max(0, old_offset - old_pos)
