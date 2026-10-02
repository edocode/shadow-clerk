"""Shadow-clerk daemon: TTS の共通インターフェースと再生パイプライン"""
from __future__ import annotations

import logging
import queue
import re
import threading
from typing import Callable, Protocol

import numpy as np

from shadow_clerk.domain import Language

logger = logging.getLogger("shadow-clerk")

PlayFn = Callable[[np.ndarray, int], None]

# 句点・感嘆符・疑問符の直後と改行で切る。1文目の再生を早く始めるため
_SENTENCE_BREAK = re.compile(r"(?<=[。！？!?])|\n")


class TtsError(Exception):
    """TTS エンジンに届かない・合成に失敗した"""


class TtsBackend(Protocol):
    LANGUAGES: tuple[Language, ...]
    DEFAULT_LANGUAGE: Language

    def check(self) -> None: ...
    def synthesize(self, text: str) -> tuple[np.ndarray, int]: ...
    def credit(self) -> str: ...


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_BREAK.split(text) if s.strip()]


def resample(pcm: np.ndarray, src: int, dst: int) -> np.ndarray:
    """線形補間でリサンプルする。音声合成の出力を読み上げるだけなので品質はこれで足りる"""
    if src == dst:
        return pcm
    n = int(len(pcm) * dst / src)
    return np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm).astype(np.float32)


def _resolve_output(name: str) -> int | None:
    import sounddevice as sd
    for i, dev in enumerate(sd.query_devices()):
        if dev["name"] == name and dev["max_output_channels"] > 0:
            return i
    logger.warning("talk: 出力デバイス %r が見つからないためデフォルト出力に出します", name)
    return None


def _play_one(pcm: np.ndarray, sr: int, device: int | None) -> None:
    import sounddevice as sd
    try:
        sd.check_output_settings(device=device, samplerate=sr, channels=1, dtype="float32")
    except Exception:
        target = int(sd.query_devices(device, kind="output")["default_samplerate"])
        pcm, sr = resample(pcm, sr, target), target
    with sd.OutputStream(samplerate=sr, channels=1, dtype="float32", device=device) as stream:
        stream.write(pcm.reshape(-1, 1))


def play_on_devices(device_names: list[str]) -> PlayFn:
    """名前で指定した出力デバイスすべてに同時に再生する関数を返す。空ならデフォルト出力"""
    def play(pcm: np.ndarray, sr: int) -> None:
        targets = [_resolve_output(n) for n in device_names] or [None]
        threads = [threading.Thread(target=_play_one, args=(pcm, sr, d), daemon=True) for d in targets]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
    return play


class TtsPlayer:
    """文を受け取り、合成スレッドと再生スレッドで回す。1文目の再生中に2文目を合成する"""

    def __init__(self, backend: TtsBackend, play: PlayFn, on_error: Callable[[str], None]) -> None:
        self._backend = backend
        self._play = play
        self._on_error = on_error
        self._texts: queue.Queue[str | None] = queue.Queue()
        self._audio: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue(maxsize=2)
        self._threads = [threading.Thread(target=self._synth_loop, name="tts-synth", daemon=True),
                         threading.Thread(target=self._play_loop, name="tts-play", daemon=True)]
        for th in self._threads:
            th.start()

    def speak(self, text: str) -> None:
        for sentence in split_sentences(text):
            self._texts.put(sentence)

    def close(self, discard_pending: bool = True) -> None:
        if discard_pending:
            while True:
                try:
                    self._texts.get_nowait()
                except queue.Empty:
                    break
        self._texts.put(None)
        for th in self._threads:
            th.join(timeout=30)

    def _synth_loop(self) -> None:
        while (text := self._texts.get()) is not None:
            try:
                self._audio.put(self._backend.synthesize(text))
            except Exception as e:
                logger.warning("talk: 合成に失敗: %s", e)
                self._on_error(str(e))
        self._audio.put(None)

    def _play_loop(self) -> None:
        while (item := self._audio.get()) is not None:
            try:
                self._play(*item)
            except Exception as e:
                logger.warning("talk: 再生に失敗: %s", e)
                self._on_error(str(e))


def make_backend(config: dict) -> TtsBackend:
    from shadow_clerk._daemon_tts_voicevox import VoicevoxBackend
    return VoicevoxBackend(str(config.get("talk_voicevox_url") or ""),
                           int(config.get("talk_speaker_id") or 0))


def make_player(backend: TtsBackend, config: dict, on_error: Callable[[str], None]) -> TtsPlayer:
    return TtsPlayer(backend, play_on_devices(list(config.get("talk_output_devices") or [])), on_error)
