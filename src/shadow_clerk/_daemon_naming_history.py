"""Shadow-clerk daemon: 名前付け履歴サイドカー

名前付け 1 回ごとの記録（NamingRecord）を transcript の隣の .naming.jsonl に残す。
取り消し（undo）が、その名前付けで書き換えた行と足した声紋サンプルを特定するのに使う。
読めない履歴は空とみなして上書きしない（NamingHistoryError で書き込みを止める）。
"""
from __future__ import annotations

import os
from dataclasses import replace

from shadow_clerk._atomic_file import atomic_write_lines
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain.naming_history import NamingRecord


class NamingHistoryError(Exception):
    """履歴ファイルに読めない行がある。空とみなして書き戻すと履歴が消えるので止める"""


def naming_path(transcript_path: str) -> str | None:
    """transcript に対応する履歴ファイルのパス。transcript 名でなければ None"""
    tn = TranscriptName.parse(os.path.basename(transcript_path))
    return os.path.join(os.path.dirname(transcript_path), tn.naming_filename) if tn else None


def read_history(transcript_path: str) -> list[NamingRecord]:
    path = naming_path(transcript_path)
    if path is None:
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = [ln for ln in f.read().splitlines() if ln.strip()]
    except FileNotFoundError:
        return []
    except (OSError, UnicodeDecodeError) as e:
        raise NamingHistoryError(f"{path}: {e}") from e
    records = [NamingRecord.parse(ln) for ln in raw]
    if any(r is None for r in records):
        raise NamingHistoryError(f"{path}: 読めない行がある")
    return [r for r in records if r is not None]


def _write(path: str, records: list[NamingRecord]) -> None:
    atomic_write_lines(path, [r.to_json_line() for r in records], ".naming-")


def append_history(transcript_path: str, records: list[NamingRecord]) -> None:
    path = naming_path(transcript_path)
    if path is None or not records:
        return
    _write(path, read_history(transcript_path) + records)


def mark_undone(transcript_path: str, record_id: str) -> NamingRecord | None:
    """record_id のレコードを undone にして書き戻す。未取り消しで見つかったときだけそれを返す"""
    path = naming_path(transcript_path)
    records = read_history(transcript_path)
    for i, r in enumerate(records):
        if r.id == record_id and not r.undone and path is not None:
            records[i] = replace(r, undone=True)
            _write(path, records)
            return records[i]
    return None


def split_history(src_transcript: str, dst_transcript: str, start_ts: str, end_ts: str) -> int:
    """時刻範囲 [start_ts, end_ts] の部分を dst の履歴へ移し、移したレコード数を返す。
    各レコードの lines/added/removed/auto_cleared を範囲内と範囲外に分け、範囲内が空でなければ同じ id で dst へ追記する"""
    src_path, dst_path = naming_path(src_transcript), naming_path(dst_transcript)
    records = read_history(src_transcript)
    if src_path is None or dst_path is None or not records:
        return 0

    def part(ts: tuple[str, ...], inside: bool) -> tuple[str, ...]:
        return tuple(x for x in ts if (start_ts <= x <= end_ts) == inside)

    fields = ("lines", "added", "removed", "auto_cleared")

    def half(r: NamingRecord, inside: bool) -> NamingRecord:
        return replace(r, **{f: part(getattr(r, f), inside) for f in fields})

    def filled(r: NamingRecord) -> bool:
        return any(getattr(r, f) for f in fields)
    moved: list[NamingRecord] = []
    kept: list[NamingRecord] = []
    for r in records:
        if filled(inner := half(r, True)):
            moved.append(inner)
        if filled(outer := half(r, False)) or not filled(inner):
            kept.append(outer)
    if not moved:
        return 0
    _write(dst_path, read_history(dst_transcript) + moved)
    _write(src_path, kept)
    return len(moved)
