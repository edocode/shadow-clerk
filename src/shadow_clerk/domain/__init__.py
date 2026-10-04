"""shadow-clerk: ドメインモデル（バリューオブジェクト）"""
from __future__ import annotations

from shadow_clerk.domain.speaker import Speaker
from shadow_clerk.domain.language import Language
from shadow_clerk.domain.audio_device import AudioDevice
from shadow_clerk.domain.audio_level import AudioLevel
from shadow_clerk.domain.transcript_line import TranscriptLine
from shadow_clerk.domain.meeting_session import MEETING_END_MARKER, MeetingSession, meeting_start_marker
from shadow_clerk.domain.summary import Summary
from shadow_clerk.domain.translation import Translation
from shadow_clerk.domain.talk_persona import TalkPersona
from shadow_clerk.domain.talk_voice import TalkVoice
from shadow_clerk.domain.console_role import ConsoleRole
from shadow_clerk.domain.talk_route import RouteTarget
from shadow_clerk.domain.talk_echo import EchoFilter, SpokenSpan
from shadow_clerk.domain.talk_speech import SpeechTab, estimate_speech_sec

__all__ = [
    "Speaker",
    "Language",
    "AudioDevice",
    "AudioLevel",
    "TranscriptLine",
    "MEETING_END_MARKER",
    "MeetingSession",
    "meeting_start_marker",
    "Summary",
    "Translation",
    "TalkPersona",
    "TalkVoice",
    "ConsoleRole",
    "RouteTarget",
    "EchoFilter",
    "SpokenSpan",
    "SpeechTab",
    "estimate_speech_sec",
]
