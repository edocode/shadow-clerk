"""Shadow-clerk daemon: 議事録の再生成

元と同じ作り方で作り直す。AI アシスタントが見ていた会議（advice か analysis がある）は
アシスタント（clerk-meeting-helper）に、それ以外は shadow-clerk の LLM に頼む。
メタデータは持たない——生成物の有無が作り方を物語る。
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any

from shadow_clerk._daemon_constants import SESSION_FILE
from shadow_clerk._daemon_console import get_console, start_console_for
from shadow_clerk._transcript_name import TranscriptName

logger = logging.getLogger("shadow-clerk")


def summary_method(transcript_path: str) -> str:
    tn = TranscriptName.parse(os.path.basename(transcript_path))
    if tn is None:
        return "llm"
    d = os.path.dirname(transcript_path)
    assistant_files = (tn.advice_filename, tn.analysis_filename)
    return "console" if any(os.path.isfile(os.path.join(d, n)) for n in assistant_files) else "llm"


def regen_prompt(transcript_path: str) -> str:
    tn = TranscriptName.parse(os.path.basename(transcript_path))
    summary = os.path.join(os.path.dirname(transcript_path), tn.summary_filename) if tn else ""
    return (f"{transcript_path} の話者の名前と所属が確定しました。"
            f"GET /api/speaker-roster?file={os.path.basename(transcript_path)} で話者一覧を読み、"
            f"transcript を頭から読み直して議事録を作り直し、{summary} に上書きしてください。")


def _other_meeting_active(transcript_path: str) -> bool:
    """別の会議が進行中か（AI コンソールは1本の共有 PTY なので、会議中のアシスタントを横取りしない）"""
    try:
        with open(SESSION_FILE, "r", encoding="utf-8") as f:
            active = f.read().strip()
    except OSError:
        return False
    return bool(active) and os.path.basename(active) != os.path.basename(transcript_path)


def regenerate_summary(recorder: Any, transcript_path: str) -> str:
    """作り直しを始め、使った作り方 ("console" / "llm") を返す。アシスタントを使えなければ LLM に落とす"""
    use_console = summary_method(transcript_path) == "console"
    if use_console and _other_meeting_active(transcript_path):
        use_console = False
        logger.info("会議中のため、別の会議の議事録は LLM で再生成します")
    if use_console:
        try:
            if start_console_for(transcript_path, send_prompt=False):
                get_console().send_after_ready(regen_prompt(transcript_path) + "\r")
                logger.info("AI コンソールに議事録の再生成を依頼します: %s", os.path.basename(transcript_path))
                return "console"
        except Exception as e:  # pylint: disable=broad-except
            logger.warning("AI コンソールへの再生成依頼に失敗: %s", e, exc_info=e)
        logger.info("AI コンソールを使えないので LLM で議事録を作り直します")
    threading.Thread(target=recorder._auto_summarize, args=(transcript_path,),
                     name="regen-summary", daemon=True).start()
    return "llm"
