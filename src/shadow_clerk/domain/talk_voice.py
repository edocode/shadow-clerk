"""shadow-clerk domain: Claude talk mode の声（話者と読み上げパラメータ）"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("shadow-clerk")

# VOICEVOX エディタのスライダーと同じ範囲
_RANGES: dict[str, tuple[float, float]] = {
    "speed": (0.5, 2.0), "pitch": (-0.15, 0.15), "intonation": (0.0, 2.0), "volume": (0.0, 2.0)}


@dataclass(frozen=True)
class TalkVoice:
    speaker_id: int = 3
    speed: float = 1.0
    pitch: float = 0.0
    intonation: float = 1.0
    volume: float = 1.0

    @classmethod
    def parse(cls, raw: dict) -> TalkVoice:
        """API から来た値を検証して作る。省略した項目は既定値、型や範囲が不正なら ValueError"""
        sid = raw.get("speaker_id", cls.speaker_id)
        if isinstance(sid, bool) or not isinstance(sid, int) or sid < 0:
            raise ValueError("speaker_id must be a non-negative integer")
        values: dict[str, float] = {}
        for name, (lo, hi) in _RANGES.items():
            v = raw.get(name, getattr(cls, name))
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
                raise ValueError(f"{name} must be a number in [{lo}, {hi}]")
            values[name] = float(v)
        return cls(speaker_id=sid, **values)

    @classmethod
    def from_config(cls, config: dict) -> TalkVoice:
        """config の talk_* から作る。不正な値なら既定値に戻す（手で書き換えた config でも止めない）"""
        raw = {"speaker_id": config.get("talk_speaker_id"),
               **{name: config.get(f"talk_{name}") for name in _RANGES}}
        try:
            return cls.parse({k: v for k, v in raw.items() if v is not None})
        except ValueError as e:
            logger.warning("talk: 声の設定が不正なため既定値を使います: %s", e)
            return cls()

    def query_overrides(self) -> dict[str, float]:
        """VOICEVOX の audio_query に上書きする値"""
        return {"speedScale": self.speed, "pitchScale": self.pitch,
                "intonationScale": self.intonation, "volumeScale": self.volume}
