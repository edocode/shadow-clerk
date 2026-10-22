"""Shadow-clerk daemon: voices サイドカー

話者分離が付けたラベルと埋め込みを transcript ごとに残す。会議後の名前付けで、
ラベルに対応する埋め込みを声紋ストアへ渡すために使う。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import replace

import numpy as np

from shadow_clerk._atomic_file import atomic_write_lines
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain.voiceprint import VoiceEntry

logger = logging.getLogger("shadow-clerk")


def voices_path(transcript_path: str) -> str | None:
    """transcript に対応するサイドカーのパス。transcript 名でなければ None"""
    tn = TranscriptName.parse(os.path.basename(transcript_path))
    return os.path.join(os.path.dirname(transcript_path), tn.voices_filename) if tn else None


def append_voice(transcript_path: str, timestamp: str, label: str, embedding: np.ndarray,
                 duration: float | None = None) -> None:
    path = voices_path(transcript_path)
    if path is None:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(VoiceEntry(timestamp, label, embedding, duration).to_json_line())
    except OSError as e:
        logger.warning("voices サイドカーに書けない: %s", e)


def _read_raw(path: str | None) -> list[str] | None:
    if path is None or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()
    except OSError as e:
        logger.warning("voices サイドカーを読めない: %s", e)
        return None


def read_voices(transcript_path: str) -> list[VoiceEntry]:
    """壊れた行（書きかけ等）は飛ばして読む"""
    lines = _read_raw(voices_path(transcript_path)) or []
    return [e for line in lines if (e := VoiceEntry.parse(line)) is not None]


def _rewritten(lines: list[str], change: Callable[[VoiceEntry], VoiceEntry | None]) -> tuple[list[str], int]:
    """change が新しい項目を返した行を書き換えた全行と、書き換えた行数。壊れた行はそのまま残す"""
    out: list[str] = []
    n = 0
    for line in lines:
        e = VoiceEntry.parse(line)
        if e is not None and (new := change(e)) is not None:
            line = new.to_json_line()
            n += 1
        out.append(line)
    return out, n


def relabeled_voice_lines_where(transcript_path: str, pick: Callable[[VoiceEntry], str | None]) -> list[str] | None:
    """pick が新しいラベルを返した行を書き換えた全行。壊れた行はそのまま残す。サイドカーが無ければ None"""
    lines = _read_raw(voices_path(transcript_path))
    if lines is None:
        return None
    return _rewritten(lines, lambda e: replace(e, label=new) if (new := pick(e)) is not None and new != e.label
                      else None)[0]


def mark_no_enroll(transcript_path: str, label: str, timestamps: set[str]) -> int:
    """(ts ∈ timestamps, label) の行に「声紋に使わない」印を付けて書き戻し、印を付けた件数を返す"""
    path = voices_path(transcript_path)
    lines = _read_raw(path)
    if path is None or lines is None:
        return 0
    out, n = _rewritten(lines, lambda e: replace(e, no_enroll=True)
                        if e.timestamp in timestamps and e.label == label and not e.no_enroll else None)
    if n:
        atomic_write_lines(path, out, ".voices-")
    return n


def voice_lines_without_label(path: str, label: str) -> list[str] | None:
    """サイドカー（パス直指定）から label の行を除いた全行。壊れた行は残す。変化が無い・無ければ None"""
    lines = _read_raw(path)
    if lines is None:
        return None
    kept = [ln for ln in lines if (e := VoiceEntry.parse(ln)) is None or e.label != label]
    return kept if len(kept) != len(lines) else None


def copy_voice_range(src_transcript: str, dst_transcript: str, start_ts: str, end_ts: str) -> int:
    """src の時刻範囲 [start_ts, end_ts] の行を dst のサイドカーへ追記し、件数を返す"""
    dst = voices_path(dst_transcript)
    entries = [e for e in read_voices(src_transcript) if start_ts <= e.timestamp <= end_ts]
    if dst is None or not entries:
        return 0
    try:
        with open(dst, "a", encoding="utf-8") as f:
            f.writelines(e.to_json_line() for e in entries)
    except OSError as e:
        logger.warning("voices サイドカーへコピーできない: %s", e)
        return 0
    return len(entries)
