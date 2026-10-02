"""shadow-clerk domain: AI Console の役割"""
from __future__ import annotations

from enum import Enum


class ConsoleRole(str, Enum):
    """AI Console は役割ごとに1つずつ持つ。会議アシスタントと talk mode の会話役を同時に動かすため"""

    ASSISTANT = "assistant"  # 会議アシスタント（従来のコンソール）
    TALK = "talk"            # Claude と会議の会話役
