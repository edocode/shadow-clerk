#!/usr/bin/env python3
"""Shadow-clerk daemon: メインレコーダー（後方互換シム）"""
from shadow_clerk._daemon_recorder_capture import _RecorderCaptureMixin
from shadow_clerk._daemon_recorder_command import _RecorderCommandMixin
from shadow_clerk._daemon_recorder_transcribe import _RecorderTranscribeMixin


class Recorder(_RecorderCaptureMixin, _RecorderCommandMixin, _RecorderTranscribeMixin):
    """音声キャプチャ・VAD・文字起こしの統合"""
