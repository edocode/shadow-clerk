"""voices サイドカーのテスト"""
from __future__ import annotations

import os

import numpy as np

from shadow_clerk._daemon_dashboard_ops import _DashboardHandlerOps
from shadow_clerk._daemon_voice_sidecar import (
    append_voice, copy_voice_range, read_voices, relabeled_voice_lines, voice_lines_without_label, voices_path,
)
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain.voiceprint import PersonName


def _vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=256).astype(np.float32)
    return v / np.linalg.norm(v)


def test_voices_filename() -> None:
    assert TranscriptName("202610091000", "週次定例").voices_filename == \
        "transcript-202610091000@週次定例.voices.jsonl"
    assert TranscriptName("20261009").voices_filename == "transcript-20261009.voices.jsonl"
    assert TranscriptName.parse("transcript-202610091000.voices.jsonl") is None


def test_voices_path(tmp_path) -> None:
    t = str(tmp_path / "transcript-202610091000.txt")
    assert voices_path(t) == str(tmp_path / "transcript-202610091000.voices.jsonl")
    assert voices_path(str(tmp_path / "summary-202610091000.md")) is None


def test_append_and_read(tmp_path) -> None:
    t = str(tmp_path / "transcript-202610091000.txt")
    assert read_voices(t) == []
    append_voice(t, "2026-10-09 10:00:01", "相手A", _vec(1))
    with open(voices_path(t), "a", encoding="utf-8") as f:
        f.write('{"ts": "broken"\n')
    append_voice(t, "2026-10-09 10:00:05", "相手B", _vec(2))
    got = read_voices(t)
    assert [(e.timestamp, e.label) for e in got] == [("2026-10-09 10:00:01", "相手A"),
                                                     ("2026-10-09 10:00:05", "相手B")]


def test_relabel_keeps_others_and_broken_lines(tmp_path) -> None:
    t = str(tmp_path / "transcript-202610091000.txt")
    assert relabeled_voice_lines(t, {"相手A": PersonName("太郎")}) is None
    append_voice(t, "2026-10-09 10:00:01", "相手A", _vec(1))
    with open(voices_path(t), "a", encoding="utf-8") as f:
        f.write("broken\n")
    append_voice(t, "2026-10-09 10:00:05", "相手B", _vec(2))
    lines = relabeled_voice_lines(t, {"相手A": PersonName("太郎")})
    assert lines is not None and len(lines) == 3
    assert '"label": "太郎"' in lines[0] and lines[1] == "broken\n" and '"label": "相手B"' in lines[2]


def test_lines_without_label(tmp_path) -> None:
    t = str(tmp_path / "transcript-202610091000.txt")
    vp = voices_path(t)
    assert voice_lines_without_label(vp, "太郎") is None
    append_voice(t, "2026-10-09 10:00:01", "太郎", _vec(1))
    assert voice_lines_without_label(vp, "次郎") is None
    with open(vp, "a", encoding="utf-8") as f:
        f.write("broken\n")
    append_voice(t, "2026-10-09 10:00:05", "相手B", _vec(2))
    append_voice(t, "2026-10-09 10:00:09", "太郎", _vec(3))
    lines = voice_lines_without_label(vp, "太郎")
    assert lines is not None and len(lines) == 2
    assert lines[0] == "broken\n" and '"label": "相手B"' in lines[1]


def test_copy_range(tmp_path) -> None:
    src = str(tmp_path / "transcript-20261009.txt")
    dst = str(tmp_path / "transcript-202610091000.txt")
    for i, ts in enumerate(["09:59:59", "10:00:00", "10:30:00", "10:30:01"]):
        append_voice(src, f"2026-10-09 {ts}", "相手A", _vec(i))
    n = copy_voice_range(src, dst, "2026-10-09 10:00:00", "2026-10-09 10:30:00")
    assert n == 2
    assert [e.timestamp for e in read_voices(dst)] == ["2026-10-09 10:00:00", "2026-10-09 10:30:00"]
    assert len(read_voices(src)) == 4


def test_copy_range_write_error(tmp_path) -> None:
    src = str(tmp_path / "transcript-20261009.txt")
    dst = str(tmp_path / "transcript-202610091000.txt")
    for i, ts in enumerate(["09:59:59", "10:00:00", "10:30:00"]):
        append_voice(src, f"2026-10-09 {ts}", "相手A", _vec(i))
    # Make destination write fail by creating a directory at the voices path
    dst_voices_dir = voices_path(dst)
    assert dst_voices_dir is not None
    os.mkdir(dst_voices_dir)
    # Should catch OSError and return 0, not raise
    n = copy_voice_range(src, dst, "2026-10-09 10:00:00", "2026-10-09 10:30:00")
    assert n == 0
    # Source should remain unchanged
    assert len(read_voices(src)) == 3


def test_related_files_include_voices(tmp_path) -> None:
    t = str(tmp_path / "transcript-202610091000.txt")
    tn = TranscriptName.parse(os.path.basename(t))
    files = {"transcript-202610091000.txt", "transcript-202610091000.voices.jsonl"}
    assert "transcript-202610091000.voices.jsonl" in _DashboardHandlerOps._related_file_names(t, tn, files)
