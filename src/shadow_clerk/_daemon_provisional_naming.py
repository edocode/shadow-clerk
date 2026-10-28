"""Shadow-clerk daemon: 会議中の話者の仮登録

会議中は transcript・声紋を触らず、名前付けを transcript の隣の .provisional.json に預ける。
会議が終わったら（end_meeting の経路は問わない）議事録より先に、ダッシュボードの付け替えと同じ処理で本登録する。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from shadow_clerk.i18n import t
from shadow_clerk._atomic_file import atomic_write_lines
from shadow_clerk._daemon_speaker_naming import summarize_labels
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain.provisional_naming import ProvisionalNaming
from shadow_clerk.domain.speaker import Speaker
from shadow_clerk.domain.transcript_line import TranscriptLine

logger = logging.getLogger("shadow-clerk")

TRANSLATION_WAIT_SEC = 120  # 本登録は翻訳中のファイルを書き換えられない。終了直後のチャンクが終わるのを待つ上限


class ProvisionalNamingError(Exception):
    """仮登録ファイルが読めない。空とみなして上書きすると仮登録が消えるので止める"""


def provisional_path(transcript_path: str) -> str | None:
    tn = TranscriptName.parse(os.path.basename(transcript_path))
    return os.path.join(os.path.dirname(transcript_path), tn.provisional_filename) if tn else None


def read_provisional(transcript_path: str) -> ProvisionalNaming:
    path = provisional_path(transcript_path)
    if path is None:
        return ProvisionalNaming()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return ProvisionalNaming.parse(f.read())
    except FileNotFoundError:
        return ProvisionalNaming()
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ProvisionalNamingError(f"{path}: {e}") from e


def write_provisional(transcript_path: str, p: ProvisionalNaming) -> None:
    """空になったらファイルを消す"""
    path = provisional_path(transcript_path)
    if path is None:
        return
    if p.empty:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return
    atomic_write_lines(path, [p.to_json()], ".provisional-")


def apply_provisional(recorder: Any, transcript_path: str) -> str | None:
    """終了した会議の仮登録を本登録する。本登録できなかった分はファイルに残す。
    何か本登録したときは表示用のメッセージを返す"""
    try:
        p = read_provisional(transcript_path)
    except ProvisionalNamingError as e:
        logger.error("仮登録を読めないので本登録しません: %s", e)
        return None
    if p.empty:
        return None
    deadline = time.monotonic() + TRANSLATION_WAIT_SEC
    while recorder.is_translating(transcript_path) and time.monotonic() < deadline:
        time.sleep(1)
    from shadow_clerk._daemon_dashboard_handler import DashboardHandler  # pylint: disable=import-outside-toplevel

    class _Headless(DashboardHandler):
        """HTTP を通さずに付け替えの本体を呼ぶ"""
        def __init__(self) -> None:  # pylint: disable=super-init-not-called
            self.recorder, self.file_watcher = recorder, getattr(recorder, "_file_watcher", None)
            self.sent: dict = {}

        def _send_json(self, data: Any) -> None:
            self.sent = data

    h, file, messages = _Headless(), os.path.basename(transcript_path), []

    def run(call: Any, body: dict) -> bool:
        call(h, {"file": file, **body})
        if h.sent.get("status") == "ok":
            messages.append(h.sent.get("message", ""))
            return True
        logger.error("仮登録を本登録できない (%s): %s", file, h.sent.get("message"))
        return False

    def read_lines() -> list[str]:
        with open(transcript_path, "r", encoding="utf-8") as f:
            return f.readlines()

    remaining = ProvisionalNaming(p.labels)
    remote = {(tl.timestamp, tl.speaker_label or Speaker.OTHER.value)
              for ln in read_lines() if (tl := TranscriptLine.parse(ln)) and tl.speaker == Speaker.OTHER}
    for assign, targets in p.line_groups():  # 行が先。ラベル単位の名前付けは、付け替えられずに残った行にだけ当たる
        if (present := targets & remote) and not run(DashboardHandler._assign_lines_with, {
                "lines": [{"ts": ts, "label": label} for ts, label in sorted(present)], **assign}):
            remaining = remaining.with_lines(present, assign)
    labels = {s.label for s in summarize_labels(read_lines())}
    mapping = {k: v for k, v in p.labels.items() if k in labels}  # 行単位で全部付け替わったラベルは消えている
    if not mapping or run(DashboardHandler._assign_speakers_with, {"mapping": mapping}) \
            or h.sent.get("message") == t("dash.speakers_nothing"):
        remaining = ProvisionalNaming(lines=remaining.lines)
    try:
        write_provisional(transcript_path, remaining)
    except OSError as e:
        logger.error("仮登録ファイルを更新できない: %s", e)
    logger.info("仮登録を本登録: %s %s", file, " ".join(messages))
    return " ".join(m for m in messages if m) or None
