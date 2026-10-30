"""Shadow-clerk daemon: VAD セグメンテーション"""
from __future__ import annotations
import logging
from collections import deque
import numpy as np
import webrtcvad
from shadow_clerk._daemon_constants import (
    VAD_MODE, SAMPLE_RATE, SPEECH_FRAMES_THRESHOLD, SILENCE_FRAMES_THRESHOLD,
    MIN_SEGMENT_DURATION, MAX_SEGMENT_DURATION, INTERIM_MAX_DURATION,
    FRAME_DURATION_MS, VAD_PRE_ROLL_FRAMES,
)

logger = logging.getLogger("shadow-clerk")


class VADSegmenter:
    """webrtcvad を使った音声セグメンテーション"""

    def __init__(self) -> None:
        self.vad = webrtcvad.Vad(VAD_MODE)
        self.last_pre_roll_sec = 0.0
        self.reset()

    def reset(self) -> None:
        self.in_speech = False
        self.last_is_speech = False  # 直前のフレームに声があったか（区切りの余韻を含まない）
        self.speech_frame_count = 0
        self.silence_frame_count = 0
        self.current_segment: list[np.ndarray] = []
        self.segment_start_time: float | None = None
        self.pre_roll: deque[np.ndarray] = deque(maxlen=VAD_PRE_ROLL_FRAMES)
        self.pre_roll_frames = 0  # current_segment の頭のうちプリロールのフレーム数

    def process_frame(self, frame: np.ndarray, timestamp: float) -> np.ndarray | None:
        """
        フレームを処理し、セグメントが確定したらその音声データを返す。
        確定していなければ None を返す。
        """
        raw = frame.tobytes()
        is_speech = self.last_is_speech = self.vad.is_speech(raw, SAMPLE_RATE)

        if not self.in_speech:
            if is_speech:
                self.speech_frame_count += 1
                if self.segment_start_time is None:
                    self.segment_start_time = timestamp
                    self.current_segment = list(self.pre_roll)
                    self.pre_roll_frames = len(self.pre_roll)
                    self.pre_roll.clear()
                self.current_segment.append(frame)
                if self.speech_frame_count >= SPEECH_FRAMES_THRESHOLD:
                    self.in_speech = True
                    self.silence_frame_count = 0
                    logger.debug("発話検出 @ %.1f", timestamp)
            else:
                # 検出に届かなかった音声も捨てずにプリロールへ戻す（弱い子音の途切れで頭を失わない）
                self.pre_roll.extend(self.current_segment)
                self.pre_roll.append(frame)
                self.speech_frame_count = 0
                self.current_segment = []
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
        """セグメントを確定して返す。直前のプリロールの秒数は last_pre_roll_sec に残す"""
        if not self.current_segment:
            self.reset()
            return None

        segment = np.concatenate(self.current_segment)
        duration = len(segment) / SAMPLE_RATE
        self.last_pre_roll_sec = self.pre_roll_frames * FRAME_DURATION_MS / 1000.0

        self.reset()

        if duration < MIN_SEGMENT_DURATION:
            logger.debug("セグメント破棄 (%.2f秒 < %.1f秒)", duration, MIN_SEGMENT_DURATION)
            return None

        return segment

    def voice_onset(self, segment: np.ndarray, end: float) -> float:
        """確定したセグメントの、プリロールを除いた声の開始時刻。
        読み上げとの重なり判定に使う。プリロールの分で重なって捨てられないように"""
        return end - len(segment) / SAMPLE_RATE + self.last_pre_roll_sec

    def get_interim_segment(self) -> np.ndarray | None:
        """発話中の蓄積音声のコピーを返す（読み取り専用、segmentation に影響しない）

        長い発話で毎回全体を再転写しないよう、直近 INTERIM_MAX_DURATION 秒に制限する。
        """
        if self.in_speech and self.current_segment:
            duration = len(self.current_segment) * FRAME_DURATION_MS / 1000.0
            if duration >= MIN_SEGMENT_DURATION:
                max_frames = int(INTERIM_MAX_DURATION * 1000 / FRAME_DURATION_MS)
                return np.concatenate(self.current_segment[-max_frames:])
        return None

    def flush(self) -> np.ndarray | None:
        """残っているセグメントを強制出力"""
        if self.in_speech and self.current_segment:
            return self._finalize_segment()
        return None
