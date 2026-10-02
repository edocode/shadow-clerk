"""Recorder の talk mode フックの検証

実行: uv run python tests/test_talk_recorder_hook.py
"""
from __future__ import annotations
import os
import sys
import tempfile
import threading

import numpy as np

from shadow_clerk._daemon_recorder_transcribe import _RecorderTranscribeMixin
from shadow_clerk.domain import Speaker, TranscriptLine

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Talk:
    def __init__(self, active: bool) -> None:
        self.active = active
        self.self_lines: list[TranscriptLine] = []

    def is_suppressed(self, source: str) -> bool:
        return self.active and source == "monitor"

    def on_self_line(self, line: TranscriptLine) -> None:
        self.self_lines.append(line)


class _Rec(_RecorderTranscribeMixin):
    def __init__(self, talk: _Talk) -> None:
        self.mute_mic = self.mute_monitor = False
        self._explicit_output = True
        self.output_path = os.path.join(tempfile.mkdtemp(), "transcript-20261002.txt")
        self.transcript_lock = threading.Lock()
        self.transcriber = type("_T", (), {"language": "ja",
                                           "transcribe": staticmethod(lambda seg: "これはテストです")})()
        self.word_replacer = type("_W", (), {"apply": staticmethod(lambda text, lang: text)})()
        self.talk = talk

    def _extract_command_body(self, text: str) -> str | None:
        return None


def _lines(rec: _Rec) -> list[str]:
    if not os.path.exists(rec.output_path):
        return []
    with open(rec.output_path, encoding="utf-8") as f:
        return f.read().splitlines()


def _run(rec: _Rec, source: str) -> None:
    rec._process_transcribe_item(np.zeros(16000, dtype=np.float32), "2026-10-02 10:00:00",
                                 source, False, {"mic": "自分", "monitor": "相手"}, None)


def test_suppress_monitor() -> None:
    talk = _Talk(active=True)
    rec = _Rec(talk)
    _run(rec, "monitor")
    check("talk mode 中の monitor は書かない", _lines(rec) == [], repr(_lines(rec)))
    _run(rec, "mic")
    check("mic は書く", _lines(rec) == ["[2026-10-02 10:00:00] [自分] これはテストです"], repr(_lines(rec)))
    check("[自分] 行を通知する", [tl.speaker for tl in talk.self_lines] == [Speaker.SELF])


def test_inactive() -> None:
    talk = _Talk(active=False)
    rec = _Rec(talk)
    _run(rec, "monitor")
    check("talk mode でなければ monitor も書く", _lines(rec) == ["[2026-10-02 10:00:00] [相手] これはテストです"])
    check("[相手] 行は通知しない", talk.self_lines == [])


def test_append_line() -> None:
    rec = _Rec(_Talk(active=False))
    rec._append_transcript_line(TranscriptLine("2026-10-02 10:00:01", Speaker.CLAUDE, "やあ"))
    check("[Claude] 行を追記できる", _lines(rec) == ["[2026-10-02 10:00:01] [Claude] やあ"])


if __name__ == "__main__":
    test_suppress_monitor()
    test_inactive()
    test_append_line()
    sys.exit(0 if all(results) else 1)
