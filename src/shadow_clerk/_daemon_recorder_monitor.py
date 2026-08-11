"""Shadow-clerk daemon: モニターキャプチャのフォールバック経路 (pw-record / parec)

PortAudio でモニター (ループバック) を開けない環境では、外部コマンドを子プロセス
として動かして PCM を受け取る。PortAudio ストリームを持つ監視スレッド
(_audio_capture_thread) とは別スレッドで、遅延起動する。
"""
from __future__ import annotations
import logging
import queue
import threading
import time
from collections.abc import Iterator
from shadow_clerk._daemon_audio_level import CaptureLevel
from shadow_clerk._daemon_constants import STREAM_RETRY_SEC, STREAM_STALL_SEC
from shadow_clerk._daemon_audio import (
    AudioBackend, PipeWireBackend, PulseAudioBackend, sink_serial,
)

logger = logging.getLogger("shadow-clerk")


class _AnyStop:
    """複数の停止イベントのいずれかが立っていれば停止とみなす読み取り専用ビュー。

    バックエンドのモニターキャプチャは、デーモン全体の停止だけでなく
    monitor_device の設定変更による再起動要求でも止める必要がある
    (_daemon_audio.StopSignal を構造的に満たす)。
    """

    def __init__(self, *events: threading.Event) -> None:
        self._events = events

    def is_set(self) -> bool:
        return any(e.is_set() for e in self._events)


class _RecorderMonitorBackendMixin:
    """pw-record / parec によるモニターキャプチャ。

    以下の属性と _requested_device() は _RecorderCaptureMixin が用意する。
    ここでは型注釈だけ置いて、このモジュール単体で型が追えるようにする。
    """

    stop_event: threading.Event
    monitor_queue: queue.Queue
    backend: AudioBackend | None
    backend_name: str
    use_monitor: bool
    _monitor_restart: threading.Event
    levels: dict[str, CaptureLevel]

    def _requested_device(self, label: str) -> str | None:
        raise NotImplementedError

    def _monitor_backend_thread(self) -> None:
        """モニターをキャプチャし、プロセスが落ちたら再検出して再開する。

        monitor_device の設定変更でも監視スレッドから再起動を要求される
        (_sync_backend_monitor_config)。要求を消費するのはこのスレッドだけで、
        監視スレッドは要求を出すだけ。こうしてモニターの所有権を 1 つに保つ。
        """
        warned = False
        while not self.stop_event.is_set():
            self._monitor_restart.clear()
            if self._capture_monitor_backend_once():
                warned = False
            elif not warned:
                logger.warning("モニターソースが見つかりません。マイクのみで録音します。")
                warned = True
            self.use_monitor = False
            if self._monitor_restart.is_set():
                # 設定変更による意図的な停止。失敗時の待機を挟まず新しい値で開き直す
                continue
            if self.stop_event.wait(STREAM_RETRY_SEC):
                return

    def _capture_monitor_backend_once(self) -> bool:
        """バックエンドを優先順に試して 1 回キャプチャする。キャプチャできたら True。

        コマンドは起動できても即座に終了することがある（指定先が古い等）。
        その場合は例外が飛ばないため、次のバックエンド（PulseAudio）に進めるよう
        「予期せず終了」を失敗として扱う。
        """
        requested = self._requested_device("monitor")
        stop = _AnyStop(self.stop_event, self._monitor_restart)
        for backend, name in self._monitor_backends():
            source = self._monitor_target(backend, requested)
            if not source:
                continue
            logger.info("%s monitor キャプチャ開始: %s", name, source)
            self.use_monitor = True
            started = time.monotonic()
            try:
                backend.start_monitor_capture(source, self.monitor_queue, stop,
                                              self.levels["monitor"])
            except FileNotFoundError as e:
                logger.error("monitor キャプチャコマンドが見つかりません: %s", e)
                continue
            except Exception as e:
                logger.error("%s monitor キャプチャ失敗: %s", name, e)
                continue
            if self.stop_event.is_set() or self._monitor_restart.is_set():
                return True
            logger.warning("%s monitor キャプチャが予期せず終了しました: %s", name, source)
            if time.monotonic() - started < STREAM_STALL_SEC:
                # すぐ死んだ = このバックエンドでは掴めない。次を試す
                continue
            return True
        return False

    def _monitor_target(self, backend: AudioBackend, requested: str | None) -> str | None:
        """バックエンドに渡すモニターキャプチャ先を決める。

        PipeWire: `pw-record --target` は名前で指定した場合 Source ノードとしか
        照合しない。ダッシュボードが保存する monitor_device は PortAudio 名
        ＝「<Sink 名>.monitor」で、これも Sink 名そのものも --target には一致せず、
        pw-record は警告も非ゼロ終了も出さないまま既定の Source ＝ ユーザーの
        マイクを録ってしまう（pw-link で実測確認済み）。Sink を確実に指すには
        数値の object.serial を渡すしかないので、".monitor" を外した Sink 名を
        serial に解決する。解決できなければ、判っていて間違った値を渡すより
        自動検出（既定 Sink の serial）に落とす方が安全なのでそうする。

        PulseAudio: `parec --device=` はモニターソース名をそのまま受け付ける。

        WASAPI (Windows): mic_device/monitor_device は Linux 向けの設定という
        設計上の非目標なので、requested は渡さず無視する。渡すと loopback
        デバイスの prefer_name として部分一致に使われてしまう。
        """
        if requested:
            if isinstance(backend, PulseAudioBackend):
                return requested
            if isinstance(backend, PipeWireBackend):
                sink = requested.removesuffix(".monitor")
                if (serial := sink_serial(sink)) is not None:
                    logger.info("monitor: Sink %s → object.serial %s", sink, serial)
                    return serial
                logger.warning("monitor: 指定 Sink %s の object.serial を解決できません。"
                               "自動検出にフォールバックします", sink)
        return backend.detect_monitor_source()

    def _monitor_backends(self) -> Iterator[tuple[AudioBackend, str]]:
        """モニターキャプチャに使うバックエンドを優先順に返す"""
        if self.backend:
            yield self.backend, self.backend_name
        # PipeWire (pw-record) が使えない場合に PulseAudio (parec) で再試行する
        if self.backend_name == "pipewire" and PulseAudioBackend.is_available():
            yield PulseAudioBackend(), "pulseaudio"
