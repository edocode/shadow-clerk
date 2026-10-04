#!/usr/bin/env python3
"""Shadow-clerk daemon: メインレコーダー（後方互換シム）"""
from __future__ import annotations
import os
from shadow_clerk._daemon_recorder_capture import _RecorderCaptureMixin
from shadow_clerk._daemon_recorder_command import _RecorderCommandMixin
from shadow_clerk._daemon_recorder_transcribe import _RecorderTranscribeMixin
from shadow_clerk._daemon_recorder_translate import _RecorderTranslateMixin


class Recorder(_RecorderCaptureMixin, _RecorderCommandMixin,
               _RecorderTranscribeMixin, _RecorderTranslateMixin):
    """音声キャプチャ・VAD・文字起こし・翻訳の統合"""

    @property
    def output_path(self) -> str:
        return self._output_path

    @output_path.setter
    def output_path(self, path: str) -> None:
        """書き込み先を変える。移った時点の大きさを覚え、/api/watch が移った先をそこから流せるようにする
        （会議が終わって戻る日付ファイルは既にあり、先頭から流すとその日の発言を丸ごと流し直してしまう）"""
        try:
            self.output_switch_offset[path] = os.path.getsize(path)
        except OSError:
            self.output_switch_offset[path] = 0
        self._output_path = path
