"""shadow-clerk: 音声キャプチャデバイス（バリューオブジェクト）"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioDevice:
    """sounddevice で開くキャプチャデバイス。

    index はホストのノード構成が変わると入れ替わる（同じ PC でも起動ごとに
    19/21/22/26 と動く）ため、同一性の判定には必ず name を使う。
    index=None は PortAudio のデフォルト入力デバイスを表す。
    """

    index: int | None
    name: str

    def __str__(self) -> str:
        return f"device={self.index}: {self.name}"
