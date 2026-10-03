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

# (pcm, sample_rate, should_stop)。should_stop が真になったら再生を途中でやめる
PlayFn = Callable[[np.ndarray, int, Callable[[], bool]], None]

# 句点・感嘆符・疑問符の直後と改行で切る。1文目の再生を早く始めるため
_SENTENCE_BREAK = re.compile(r"(?<=[。！？!?])|\n")
# 句点のない長い文は読点でも切る。文の切れ目が「ちょっと待って」で止められる単位になる
_MAX_CHUNK_CHARS = 60
_COMMA_BREAK = re.compile(r"(?<=[、，,])")
# 再生をこの長さずつ書き、合間に should_stop を見る
_PLAY_BLOCK_SEC = 0.1


class TtsError(Exception):
    """TTS エンジンに届かない・合成に失敗した"""


class TtsBackend(Protocol):
    LANGUAGES: tuple[Language, ...]
    DEFAULT_LANGUAGE: Language

    def check(self) -> None: ...
    def synthesize(self, text: str) -> tuple[np.ndarray, int]: ...
    def credit(self) -> str: ...
    def voices(self) -> list[dict[str, Any]]: ...


def _split_long(sentence: str) -> list[str]:
    if len(sentence) <= _MAX_CHUNK_CHARS:
        return [sentence]
    chunks = [""]
    for part in _COMMA_BREAK.split(sentence):
        if chunks[-1] and len(chunks[-1]) + len(part) > _MAX_CHUNK_CHARS:
            chunks.append("")
        chunks[-1] += part
    return [c for c in chunks if c]


def split_sentences(text: str) -> list[str]:
    return [c for raw in _SENTENCE_BREAK.split(text) if (s := raw.strip()) for c in _split_long(s)]


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


def _play_one(pcm: np.ndarray, sr: int, device: int | None, should_stop: Callable[[], bool]) -> None:
    import sounddevice as sd
    try:
        sd.check_output_settings(device=device, samplerate=sr, channels=1, dtype="float32")
    except Exception:
        target = int(sd.query_devices(device, kind="output")["default_samplerate"])
        pcm, sr = resample(pcm, sr, target), target
    block = max(1, int(sr * _PLAY_BLOCK_SEC))
    with sd.OutputStream(samplerate=sr, channels=1, dtype="float32", device=device) as stream:
        for i in range(0, len(pcm), block):
            if should_stop():
                stream.abort()  # 書き込み済みのバッファも鳴らさない
                return
            stream.write(pcm[i:i + block].reshape(-1, 1))


def play_on_devices(device_names: list[str]) -> PlayFn:
    """名前で指定した出力デバイスすべてに同時に再生する関数を返す。空ならデフォルト出力。

    再生スレッドの例外は呼び出し側に投げ直す（スレッド内で消えると、無音なのにエラーが出ない）。
    """
    from shadow_clerk._daemon_audio import PORTAUDIO_LOCK

    def play(pcm: np.ndarray, sr: int, should_stop: Callable[[], bool]) -> None:
        errors: list[Exception] = []

        def run(device: int | None) -> None:
            try:
                _play_one(pcm, sr, device, should_stop)
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


def _drain(q: queue.Queue) -> int:
    """取り出した文の数を返す（終端の None は数えない）"""
    n = 0
    while True:
        try:
            n += q.get_nowait() is not None
        except queue.Empty:
            return n


class TtsPlayer:
    """文を受け取り、合成スレッドと再生スレッドで回す。1文目の再生中に2文目を合成する。

    文には世代番号を付ける。interrupt() で世代を進めると、古い世代の文は合成も再生もされず、
    再生中の文も should_stop で途中で止まる。
    """

    def __init__(self, backend: TtsBackend, play: PlayFn, on_error: Callable[[str], None]) -> None:
        self._backend = backend
        self._play = play
        self._on_error = on_error
        self._on_played: Callable[[str, float, float], None] | None = None
        self._texts: queue.Queue[tuple[int, str] | None] = queue.Queue()
        self._audio: queue.Queue[tuple[int, str, np.ndarray, int] | None] = queue.Queue(maxsize=2)
        self._abort = threading.Event()
        self._gen = 0
        self._speaking = ""
        self._pending = 0  # 合成待ち・再生待ち・再生中の文の数
        self._pending_lock = threading.Lock()
        self._threads = [threading.Thread(target=self._synth_loop, name="tts-synth", daemon=True),
                         threading.Thread(target=self._play_loop, name="tts-play", daemon=True)]
        for th in self._threads:
            th.start()

    def set_on_played(self, fn: Callable[[str, float, float], None] | None) -> None:
        """鳴らし終えた1文ごとに fn(text, start, end) を呼ぶ（talk mode で Claude 自身の声を見分けるため）"""
        self._on_played = fn

    def speak(self, text: str) -> None:
        gen = self._gen
        for sentence in split_sentences(text):
            self._add_pending(1)
            self._texts.put((gen, sentence))

    def is_busy(self) -> bool:
        """話している文か、合成・再生を待っている文があるか"""
        with self._pending_lock:
            return self._pending > 0

    def _add_pending(self, n: int) -> None:
        with self._pending_lock:
            self._pending = max(0, self._pending + n)

    def interrupt(self) -> str:
        """まだ話していない文を捨て、話している文も止める。止めた時点で話していた文を返す（無ければ ""）"""
        self._gen += 1
        self._add_pending(-(_drain(self._texts) + _drain(self._audio)))
        speaking, self._speaking = self._speaking, ""
        return speaking

    def close(self, discard_pending: bool = True) -> None:
        """discard_pending なら、まだ話していない文を捨て、話している文も止める"""
        if discard_pending:
            self._abort.set()
            _drain(self._texts)
            _drain(self._audio)
        self._texts.put(None)
        deadline = time.monotonic() + 30
        for th in self._threads:
            th.join(timeout=max(0.0, deadline - time.monotonic()))

    def _stale(self, gen: int) -> bool:
        return self._abort.is_set() or gen != self._gen

    def _synth_loop(self) -> None:
        while (item := self._texts.get()) is not None:
            gen, text = item
            if self._stale(gen):
                self._add_pending(-1)
                continue
            try:
                pcm, sr = self._backend.synthesize(text)
            except Exception as e:
                logger.warning("talk: 合成に失敗: %s", e)
                self._on_error(str(e))
                self._add_pending(-1)
                continue
            if self._stale(gen):
                self._add_pending(-1)
            else:
                self._audio.put((gen, text, pcm, sr))
        self._audio.put(None)

    def _play_loop(self) -> None:
        while (item := self._audio.get()) is not None:
            gen, text, pcm, sr = item
            if self._stale(gen):
                self._add_pending(-1)
                continue
            self._speaking = text
            try:
                start = time.time()
                self._play(pcm, sr, lambda: self._stale(gen))
                end = time.time()
                if self._on_played is not None:
                    try:
                        self._on_played(text, start, end)
                    except Exception as e:  # 通知の失敗で再生を止めない
                        logger.warning("talk: 再生の通知に失敗: %s", e)
            except Exception as e:
                logger.warning("talk: 再生に失敗: %s", e)
                self._on_error(str(e))
            finally:
                if self._speaking == text:
                    self._speaking = ""
                self._add_pending(-1)


def make_backend(config: dict, voice: TalkVoice | None = None) -> TtsBackend:
    """voice を渡せばその声に固定する（試聴用）。省略すると文ごとに config から読み直す"""
    from shadow_clerk._daemon_config import load_config
    from shadow_clerk._daemon_tts_voicevox import VoicevoxBackend
    return VoicevoxBackend(str(config.get("talk_voicevox_url") or ""),
                           (lambda: voice) if voice is not None else (lambda: TalkVoice.from_config(load_config())))


def make_player(backend: TtsBackend, config: dict, on_error: Callable[[str], None]) -> TtsPlayer:
    return TtsPlayer(backend, play_on_devices(list(config.get("talk_output_devices") or [])), on_error)
