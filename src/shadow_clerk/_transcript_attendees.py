"""Shadow-clerk: transcript ごとの参加予定者（attendees.json）の読み出し

ダッシュボード（名前の候補）と録音側（声紋照合の参加者）の両方から使う。
"""
from __future__ import annotations

import json
import os

from shadow_clerk._transcript_name import TranscriptName


def read_attendees(transcript_path: str) -> list[str]:
    """transcript と同じディレクトリの attendees.json から参加予定者を返す。無ければ空"""
    tn = TranscriptName.parse(os.path.basename(transcript_path))
    if tn is None:
        return []
    try:
        with open(os.path.join(os.path.dirname(transcript_path), tn.attendees_filename),
                  "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    return [a for a in (data.get("attendees") or []) if isinstance(a, str) and a.strip()]
