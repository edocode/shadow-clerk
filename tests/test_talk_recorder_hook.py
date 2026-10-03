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
    def __init__(self, active: bool, route: bool = False) -> None:
        self.active, self.route = active, route
        self.self_lines: list[TranscriptLine] = []
        self.echo_calls: list[tuple] = []

    def is_suppressed(self, source: str) -> bool:
        return self.active and source == "monitor" and not self.route

    def is_echo(self, source: str, s: float, e: float, text: str) -> bool:
        self.echo_calls.append((source, s, e, text))
        return self.active and self.route and source == "monitor" and "Claude の声" in text

    def on_self_line(self, line: TranscriptLine) -> None:
        self.self_lines.append(line)


class _Rec(_RecorderTranscribeMixin):
    def __init__(self, talk: _Talk, said: str = "これはテストです") -> None:
        self.mute_mic = self.mute_monitor = False
        self._explicit_output = True
        self.output_path = os.path.join(tempfile.mkdtemp(), "transcript-20261002.txt")
        self.transcript_lock = threading.Lock()
        self.transcriber = type("_T", (), {"language": "ja",
                                           "transcribe": staticmethod(lambda seg: said)})()
        self.word_replacer = type("_W", (), {"apply": staticmethod(lambda text, lang: text)})()
        self.talk = talk

    def _extract_command_body(self, text: str) -> str | None:
        return None


def _lines(rec: _Rec) -> list[str]:
    if not os.path.exists(rec.output_path):
        return []
    with open(rec.output_path, encoding="utf-8") as f:
        return f.read().splitlines()


def _run(rec: _Rec, source: str, last: Speaker | None = None) -> None:
    rec._process_transcribe_item(np.zeros(16000, dtype=np.float32), "2026-10-02 10:00:00", 1000.25,
                                 source, False, {"mic": "自分", "monitor": "相手"}, last)


def test_suppress_monitor() -> None:
    talk = _Talk(active=True)
    rec = _Rec(talk)
    _run(rec, "monitor")
    check("talk mode 中の monitor は書かない", _lines(rec) == [], repr(_lines(rec)))
    _run(rec, "mic")
    check("mic は書く", _lines(rec) == ["[2026-10-02 10:00:00] [自分] これはテストです"], repr(_lines(rec)))
    check("[自分] 行を通知する", [tl.speaker for tl in talk.self_lines] == [Speaker.SELF])


def test_echo_dropped_other_side_kept() -> None:
    talk = _Talk(active=True)
    talk.route = True
    rec = _Rec(talk, said="これは Claude の声です")
    events: list[tuple[str, str]] = []
    rec._file_watcher = type("_FW", (), {"_broadcast": staticmethod(lambda ev, data: events.append((ev, data)))})()
    _run(rec, "monitor")
    check("届け先ありの talk mode で Claude の声は書かない", _lines(rec) == [], repr(_lines(rec)))
    check("捨てたときも中間テキストを消す", [e for e, _ in events] == ["interim_clear"], repr(events))
    rec = _Rec(talk, said="相手の発言です")
    _run(rec, "monitor")
    check("相手の発言は [相手] で書く", _lines(rec) == ["[2026-10-02 10:00:00] [相手] 相手の発言です"], repr(_lines(rec)))
    check("区間は録音側が測った開始時刻と音声の長さから渡す", talk.echo_calls[-1][1:3] == (1000.25, 1001.25), repr(talk.echo_calls[-1]))


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


def test_short_reply_kept_in_talk_mode() -> None:
    # Claude の行は transcribe ループの外で書かれるので、直前の話者は自分のまま残る。
    # それでも Claude の質問への「はい」は捨ててはいけない
    talk = _Talk(active=True)
    rec = _Rec(talk, said="はい")
    _run(rec, "mic", last=Speaker.SELF)
    check("talk mode 中の「はい」は書いて送る",
          _lines(rec) == ["[2026-10-02 10:00:00] [自分] はい"] and len(talk.self_lines) == 1, repr(_lines(rec)))
    rec = _Rec(_Talk(active=False), said="はい")
    _run(rec, "mic", last=Speaker.SELF)
    check("talk mode でなければ従来どおり捨てる", _lines(rec) == [])


if __name__ == "__main__":
    test_short_reply_kept_in_talk_mode()
    test_suppress_monitor()
    test_inactive()
    test_echo_dropped_other_side_kept()
    test_append_line()
    sys.exit(0 if all(results) else 1)
