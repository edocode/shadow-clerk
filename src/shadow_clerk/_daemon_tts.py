"""Shadow-clerk daemon: TTS の共通インターフェースと再生パイプライン"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Any, Callable, Protocol

import numpy as np

from shadow_clerk.domain import Language, TalkVoice

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
    def voices(self) -> list[dict[str, Any]]: ...


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
    """名前で指定した出力デバイスすべてに同時に再生する関数を返す。空ならデフォルト出力。

    再生スレッドの例外は呼び出し側に投げ直す（スレッド内で消えると、無音なのにエラーが出ない）。
    """
    from shadow_clerk._daemon_audio import PORTAUDIO_LOCK

    def play(pcm: np.ndarray, sr: int) -> None:
        errors: list[Exception] = []

        def run(device: int | None) -> None:
            try:
                _play_one(pcm, sr, device)
            except Exception as e:
                errors.append(e)

        with PORTAUDIO_LOCK:
            targets = [_resolve_output(n) for n in device_names] or [None]
            threads = [threading.Thread(target=run, args=(d,), daemon=True) for d in targets]
            for th in threads:
                th.start()
            for th in threads:
                th.join()
        if errors:
            raise errors[0]
    return play


def _drain(q: queue.Queue) -> None:
    while True:
        try:
            q.get_nowait()
        except queue.Empty:
            return


class TtsPlayer:
    """文を受け取り、合成スレッドと再生スレッドで回す。1文目の再生中に2文目を合成する"""

    def __init__(self, backend: TtsBackend, play: PlayFn, on_error: Callable[[str], None]) -> None:
        self._backend = backend
        self._play = play
        self._on_error = on_error
        self._texts: queue.Queue[str | None] = queue.Queue()
        self._audio: queue.Queue[tuple[np.ndarray, int] | None] = queue.Queue(maxsize=2)
        self._abort = threading.Event()
        self._threads = [threading.Thread(target=self._synth_loop, name="tts-synth", daemon=True),
                         threading.Thread(target=self._play_loop, name="tts-play", daemon=True)]
        for th in self._threads:
            th.start()

    def speak(self, text: str) -> None:
        for sentence in split_sentences(text):
            self._texts.put(sentence)

    def close(self, discard_pending: bool = True) -> None:
        """discard_pending なら、まだ再生していない文と合成済みの音声を捨て、再生中の1文だけ待つ"""
        if discard_pending:
            self._abort.set()
            _drain(self._texts)
            _drain(self._audio)
        self._texts.put(None)
        deadline = time.monotonic() + 30
        for th in self._threads:
            th.join(timeout=max(0.0, deadline - time.monotonic()))

    def _synth_loop(self) -> None:
        while (text := self._texts.get()) is not None:
            if self._abort.is_set():
                continue
            try:
                audio = self._backend.synthesize(text)
            except Exception as e:
                logger.warning("talk: 合成に失敗: %s", e)
                self._on_error(str(e))
                continue
            if not self._abort.is_set():
                self._audio.put(audio)
        self._audio.put(None)

    def _play_loop(self) -> None:
        while (item := self._audio.get()) is not None:
            if self._abort.is_set():
                continue
            try:
                self._play(*item)
            except Exception as e:
                logger.warning("talk: 再生に失敗: %s", e)
                self._on_error(str(e))


def make_backend(config: dict, voice: TalkVoice | None = None) -> TtsBackend:
    """voice を渡せばその声に固定する（試聴用）。省略すると文ごとに config から読み直す"""
    from shadow_clerk._daemon_config import load_config
    from shadow_clerk._daemon_tts_voicevox import VoicevoxBackend
    return VoicevoxBackend(str(config.get("talk_voicevox_url") or ""),
                           (lambda: voice) if voice is not None else (lambda: TalkVoice.from_config(load_config())))


def make_player(backend: TtsBackend, config: dict, on_error: Callable[[str], None]) -> TtsPlayer:
    return TtsPlayer(backend, play_on_devices(list(config.get("talk_output_devices") or [])), on_error)
