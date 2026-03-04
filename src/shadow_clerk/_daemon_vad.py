"""Shadow-clerk daemon: VAD セグメンテーション"""
import logging
import numpy as np
import webrtcvad
from shadow_clerk._daemon_constants import (
    VAD_MODE, SAMPLE_RATE, SPEECH_FRAMES_THRESHOLD, SILENCE_FRAMES_THRESHOLD,
    MIN_SEGMENT_DURATION, MAX_SEGMENT_DURATION, FRAME_DURATION_MS,
)

logger = logging.getLogger("shadow-clerk")


class VADSegmenter:
    """webrtcvad を使った音声セグメンテーション"""

    def __init__(self):
        self.vad = webrtcvad.Vad(VAD_MODE)
        self.reset()

    def reset(self):
        self.in_speech = False
        self.speech_frame_count = 0
        self.silence_frame_count = 0
        self.current_segment: list[np.ndarray] = []
        self.segment_start_time: float | None = None

    def process_frame(self, frame: np.ndarray, timestamp: float) -> np.ndarray | None:
        """
        フレームを処理し、セグメントが確定したらその音声データを返す。
        確定していなければ None を返す。
        """
        raw = frame.tobytes()
        is_speech = self.vad.is_speech(raw, SAMPLE_RATE)

        if not self.in_speech:
            if is_speech:
                self.speech_frame_count += 1
                self.current_segment.append(frame)
                if self.segment_start_time is None:
                    self.segment_start_time = timestamp
                if self.speech_frame_count >= SPEECH_FRAMES_THRESHOLD:
                    self.in_speech = True
                    self.silence_frame_count = 0
                    logger.debug("発話検出 @ %.1f", timestamp)
            else:
                self.speech_frame_count = 0
                self.current_segment.clear()
                self.segment_start_time = None
        else:
            self.current_segment.append(frame)
            if is_speech:
                self.silence_frame_count = 0
            else:
                self.silence_frame_count += 1

            # セグメント長チェック
            segment_duration = len(self.current_segment) * FRAME_DURATION_MS / 1000.0

            if self.silence_frame_count >= SILENCE_FRAMES_THRESHOLD:
                logger.debug("無音検出、セグメント確定 (%.1f秒)", segment_duration)
                return self._finalize_segment()

            if segment_duration >= MAX_SEGMENT_DURATION:
                logger.debug("最大長到達、セグメント強制分割 (%.1f秒)", segment_duration)
                return self._finalize_segment()

        return None

    def _finalize_segment(self) -> np.ndarray | None:
        """セグメントを確定して返す"""
        if not self.current_segment:
            self.reset()
            return None

        segment = np.concatenate(self.current_segment)
        duration = len(segment) / SAMPLE_RATE

        self.reset()

        if duration < MIN_SEGMENT_DURATION:
            logger.debug("セグメント破棄 (%.2f秒 < %.1f秒)", duration, MIN_SEGMENT_DURATION)
            return None

        return segment

    def get_interim_segment(self) -> np.ndarray | None:
        """発話中の蓄積音声のコピーを返す（読み取り専用、segmentation に影響しない）"""
        if self.in_speech and self.current_segment:
            duration = len(self.current_segment) * FRAME_DURATION_MS / 1000.0
            if duration >= MIN_SEGMENT_DURATION:
                return np.concatenate(self.current_segment)
        return None

    def flush(self) -> np.ndarray | None:
        """残っているセグメントを強制出力"""
        if self.in_speech and self.current_segment:
            return self._finalize_segment()
        return None
