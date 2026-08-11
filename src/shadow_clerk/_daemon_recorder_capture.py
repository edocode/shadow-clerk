"""Shadow-clerk daemon: レコーダー音声キャプチャ・VAD ミックスイン"""
# pylint: disable=duplicate-code  # 各モジュールで必要な optional import ブロックは共通形だが抽象化不可
from __future__ import annotations
import argparse
import datetime
import logging
import os
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Any
import numpy as np
from shadow_clerk import DATA_DIR
from shadow_clerk._daemon_constants import (
    SAMPLE_RATE, FRAME_SIZE, CHANNELS, DTYPE,
    SESSION_FILE,
    STREAM_STALL_SEC, STREAM_CHECK_INTERVAL, STREAM_RESOLVE_INTERVAL, STREAM_RETRY_SEC,
    STREAM_DEGRADED_RETRY_SEC, STREAM_DEGRADED_RETRY_MAX_SEC,
    build_wake_word_patterns,
)
from shadow_clerk._daemon_audio_level import CaptureLevel
from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_audio import (
    detect_backend, device_exists, find_device_by_name, get_default_sink_name,
    refresh_device_list, resolve_mic_device, resolve_monitor_device, snapshot_devices,
)
from shadow_clerk._daemon_recorder_monitor import _RecorderMonitorBackendMixin
from shadow_clerk._daemon_vad import VADSegmenter
from shadow_clerk._daemon_transcriber import Transcriber, GlossaryReplacer
from shadow_clerk.domain import AudioDevice, MeetingSession

logger = logging.getLogger("shadow-clerk")


@dataclass(frozen=True)
class _Reconnect:
    """張り替え要求。

    labels=None は全ストリームが対象。refresh=True はデバイス一覧の再列挙が
    必要な場合で、再列挙は開いている全ストリームを破棄する。
    """

    reason: str
    labels: frozenset[str] | None = None
    refresh: bool = True


class _CaptureStream:
    """監視付きの PortAudio 入力ストリーム。

    コールバックで最終フレーム時刻を更新し、ウォッチドッグが途絶を検知する。
    follow_sink=True なら開いた時点のデフォルト Sink 名を覚え、出力先の切り替えを
    検知する（サスペンド復帰やヘッドセットの抜き差しで実際に起きる）。
    """

    def __init__(self, label: str, device: AudioDevice, audio_queue: queue.Queue,
                 follow_sink: bool = False, requested: str | None = None,
                 level: CaptureLevel | None = None) -> None:
        self.label = label
        self.device = device
        self.requested = requested   # 開いた時点で config が要求していたデバイス名
        self.follow_sink = follow_sink
        self.sink = get_default_sink_name() if follow_sink else None
        self._queue = audio_queue
        self.level = level
        self._stream: Any = None
        self.last_frame = time.monotonic()

    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            logger.warning("%s status: %s", self.label, status)
        self.last_frame = time.monotonic()
        mono = indata[:, 0].copy().astype(np.int16)
        if self.level is not None:
            self.level.add(mono)
        self._queue.put(mono)

    def open(self) -> bool:
        """ストリームを開いて開始する。成功なら True。"""
        import sounddevice as sd
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=FRAME_SIZE,
                device=self.device.index,
                callback=self._callback,
            )
            self._stream.start()
        except sd.PortAudioError as e:
            logger.warning("%s キャプチャを開けません (%s): %s", self.label, self.device, e)
            self.close()
            return False
        self.last_frame = time.monotonic()
        logger.info("%s キャプチャ開始 (%s)", self.label, self.device)
        return True

    def idle_sec(self) -> float:
        """最終フレームからの経過秒数。

        CLOCK_MONOTONIC はサスペンド中進まないため、レジューム直後に
        サスペンド時間で誤検知することはない。
        """
        return time.monotonic() - self.last_frame

    def changed_sink(self) -> str | None:
        """デフォルト Sink が開いた時点から変わっていれば新しい名前を返す"""
        if not self.follow_sink:
            return None
        current = get_default_sink_name()
        if not current:
            return None
        if self.sink is None:
            # オープン時に Sink 名を取れなかった（レジューム直後で wireplumber が
            # 再起動中など）。取れた時点を基準にしないと追従が永久に無効化される
            self.sink = current
            return None
        return current if current != self.sink else None

    def close(self) -> None:
        import sounddevice as sd
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except sd.PortAudioError:
            pass
        self._stream = None


class _RecorderCaptureMixin(_RecorderMonitorBackendMixin):
    """音声キャプチャ・VAD ミックスイン

    モニターのフォールバック経路 (pw-record/parec) は
    _RecorderMonitorBackendMixin が持つ。
    """

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.stop_event = threading.Event()
        self.mic_queue: queue.Queue = queue.Queue()
        self.monitor_queue: queue.Queue = queue.Queue()
        self.vad_queue: queue.Queue = queue.Queue()
        self.transcribe_queue: queue.Queue = queue.Queue()
        self.interim_queue: queue.Queue = queue.Queue(maxsize=2)
        self.transcript_lock = threading.Lock()  # トランスクリプトファイル読み書きの排他制御

        self.backend_name, self.backend = detect_backend(args.backend)

        # config 読み込み
        config = load_config()

        # カスタム音声コマンドをコンパイル
        self._custom_commands = []
        for entry in config.get("custom_commands") or []:
            try:
                pat = re.compile(entry["pattern"], re.IGNORECASE)
                self._custom_commands.append((pat, entry["action"]))
            except (KeyError, re.error) as e:
                logger.warning("カスタムコマンド定義エラー: %s — %s", entry, e)

        # ウェイクワードパターン初期化（_RecorderCommandMixin）
        wake_word = (config.get("wake_word") or "").strip() or "シェルク"
        self._wake_prefix, self._wake_suffix = build_wake_word_patterns(wake_word)

        # Whisper initial_prompt: ウェイクワード + ユーザー指定プロンプト
        user_prompt = config.get("initial_prompt")
        initial_prompt = f"{wake_word}、{user_prompt}" if user_prompt else wake_word

        self.transcriber = Transcriber(
            model_size=args.model,
            language=args.language,
            initial_prompt=initial_prompt,
            beam_size=args.whisper_beam_size,
            compute_type=args.whisper_compute_type,
            device=args.whisper_device,
        )

        # (api_endpoint の判定は load_config() で毎回取得する)

        # output_directory: config で指定されていればそちらを使う
        output_dir_config = config.get("output_directory")
        if output_dir_config:
            self._output_dir = os.path.expanduser(output_dir_config)
            os.makedirs(self._output_dir, exist_ok=True)
        else:
            self._output_dir = DATA_DIR

        # --output が指定されていれば固定、なければ日付ベースのデフォルト
        self._explicit_output = args.output is not None
        if self._explicit_output:
            self.output_path = args.output
        elif os.path.exists(SESSION_FILE):
            # 会議セッション中に再起動された場合、セッションファイルを復元
            try:
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    session_path = f.read().strip()
                if session_path and os.path.exists(session_path):
                    self.output_path = session_path
                    logger.info("会議セッション復元: %s", session_path)
                else:
                    self.output_path = self._get_default_output()
            except Exception:
                self.output_path = self._get_default_output()
        else:
            self.output_path = self._get_default_output()
        self.use_monitor = True
        self.use_mic = True
        self.word_replacer = GlossaryReplacer()

        # Push-to-Talk コマンドモード
        self._command_mode = False
        self._command_mode_release_time: float = 0.0  # キーリリース時刻
        self._voice_command_key = config.get("voice_command_key")

        # Mic/Speaker ミュートフラグ
        self.mute_mic = False
        self.mute_monitor = False

        # 番号指定 (--mic/--monitor) で最後に開いたデバイス名。再列挙で番号が
        # ずれても同じデバイスを掴み直すために使う
        self._pinned_names: dict[str, str] = {}
        # ダッシュボードからの手動デバイス再検出リクエスト。_watch_streams の次の
        # 2 秒ティックで消費され、通常の refresh=True 張り替え経路に乗る
        self._manual_device_refresh = False
        # 「指定デバイスが復帰した」判定で張り替えたのに開けるようにならなかった
        # 場合の指数バックオフ。{ラベル: (デバイス名, 次に試せる時刻, 次の待ち時間)}
        self._return_backoff: dict[str, tuple[str, float, float]] = {}
        # 遅延起動するため threads リストに載らない。shutdown で join する
        self._monitor_backend: threading.Thread | None = None
        # バックエンドのモニターキャプチャに再起動を要求するイベント。監視スレッド
        # だけが set し、バックエンドスレッドだけが clear する（所有権を分けて
        # 両者が同じモニターを奪い合わないようにする）
        self._monitor_restart = threading.Event()
        # バックエンド起動時に監視スレッドが見た monitor_device の値。
        # 監視スレッド専用の状態で、バックエンドスレッドからは触らない
        self._monitor_backend_requested: str | None = None
        # /api/audio-devices が返すデバイス一覧。Task 4 で監視スレッドが
        # ストリームを開くたびに更新する。起動直後のごく短い間だけ空になる
        self._device_snapshot: dict[str, Any] = {
            "mic": [], "monitor": [], "updated_at": None}

        # 入力レベル。sounddevice 経路とバックエンド経路の両方が更新する
        self.levels: dict[str, CaptureLevel] = {
            "mic": CaptureLevel(), "monitor": CaptureLevel()}

        # 会議セッション（進行中は MeetingSession、それ以外は None）
        self.current_session: MeetingSession | None = None

        # 翻訳ループ
        self._translate_stop_event = threading.Event()
        self._translate_thread: threading.Thread | None = None
        self.translate_target_path: str | None = None  # 現在翻訳中のトランスクリプトパス

        # リアルタイム interim 翻訳キュー (maxsize=1 で最新のみ保持)
        self._interim_translate_queue: queue.Queue = queue.Queue(maxsize=1)

    def _get_default_output(self) -> str:
        """現在日付ベースのデフォルト transcript パスを返す"""
        filename = datetime.datetime.now().strftime("transcript-%Y%m%d.txt")
        return os.path.join(self._output_dir, filename)

    def _setup_signal_handlers(self) -> None:
        import signal
        import types

        def handler(signum: int, frame: types.FrameType | None) -> None:
            logger.info("シグナル受信 (%s)、終了処理中...", signal.Signals(signum).name)
            self.stop_event.set()

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def _audio_capture_thread(self) -> None:
        """マイク/モニターをキャプチャし、途絶・出力先変更・設定変更で再接続する。

        マイクとモニターを 1 スレッドでまとめて管理するのは、デバイス一覧の再列挙
        (refresh_device_list) が開いている PortAudio ストリームを全て破棄するため。
        逆に再列挙が要らない張り替え（設定で選び直した先がキャッシュ上にある）では
        該当する系統だけを開き直し、もう一方の音声を途切れさせない。
        """
        streams: dict[str, _CaptureStream] = {}
        backend_started = False
        need_refresh = False
        degraded_wait = STREAM_DEGRADED_RETRY_SEC
        try:
            while not self.stop_event.is_set():
                try:
                    if need_refresh:
                        # サスペンド復帰・抜き差し後はキャッシュが陳腐化している。
                        # 全ストリームが閉じている状態でのみ呼べる
                        try:
                            refresh_device_list()
                        except Exception as e:
                            logger.warning("デバイス一覧の再列挙に失敗: %s", e)
                        need_refresh = False

                    if "mic" not in streams:
                        if (s := self._open_requested(
                                "mic", self.args.mic, self.mic_queue)) is not None:
                            streams["mic"] = s
                    self.use_mic = "mic" in streams

                    if "monitor" not in streams and not backend_started:
                        s = self._open_requested(
                            "monitor", self.args.monitor, self.monitor_queue,
                            follow_sink=self._should_follow_sink())
                        if s is not None:
                            streams["monitor"] = s
                        else:
                            logger.info("sounddevice でモニターを開けません、"
                                        "%s バックエンドにフォールバック", self.backend_name)
                            # バックエンド稼働中の設定変更検知の基準値（_config_changed）
                            self._monitor_backend_requested = self._requested_device("monitor")
                            self._monitor_backend = threading.Thread(
                                target=self._monitor_backend_thread,
                                name="monitor-backend", daemon=True)
                            self._monitor_backend.start()
                            backend_started = True
                        self.use_monitor = "monitor" in streams

                    self._device_snapshot = snapshot_devices()

                    degraded = "mic" not in streams or (
                        "monitor" not in streams and not backend_started)
                    req = self._watch_streams(list(streams.values()),
                                              degraded_wait if degraded else None)
                    if req is None:
                        return
                    logger.warning("音声ストリーム再接続: %s", req.reason)
                    degraded_wait = (min(degraded_wait * 2, STREAM_DEGRADED_RETRY_MAX_SEC)
                                     if degraded else STREAM_DEGRADED_RETRY_SEC)
                    had_live = bool(streams)
                    if req.refresh:
                        # 再列挙は全ストリームを破棄するので、全部閉じてから
                        for stream in streams.values():
                            stream.close()
                        streams.clear()
                        need_refresh = True
                    else:
                        for label in (req.labels or frozenset(streams)):
                            if (stream := streams.pop(label, None)) is not None:
                                stream.close()
                    # 待機は「開き直しても失敗する」状態でのビジーループ防止。
                    # 直前に生きたストリームがあったなら待たずに張り替える
                    if not had_live and self.stop_event.wait(STREAM_RETRY_SEC):
                        return
                except Exception:
                    # 1 スレッドで両系統を持つため、ここで落とすと録音が全て止まる
                    logger.exception("音声キャプチャで予期しないエラー、再試行します")
                    for stream in streams.values():
                        stream.close()
                    streams.clear()
                    need_refresh = True
                    if self.stop_event.wait(STREAM_RETRY_SEC):
                        return
        finally:
            for stream in streams.values():
                stream.close()

    def request_device_refresh(self) -> None:
        """ダッシュボードの「一覧を更新」からの手動再列挙リクエスト。

        refresh_device_list() 自体はここで呼ばない。全ストリームが閉じている
        状態でしか安全に呼べないため、キャプチャスレッド側の通常の
        refresh=True 張り替え経路（_audio_capture_thread）に乗せる必要がある。
        ここではフラグを立てるだけで、_watch_streams が次の監視ティックで消費する。
        """
        self._manual_device_refresh = True

    def _requested_device(self, label: str) -> str | None:
        """config で指定されたデバイス名。CLI で番号指定されている場合は None。

        CLI と config が同時に効くと張り替えが競合するため、CLI を優先して
        config を無効化する。
        """
        if getattr(self.args, label) is not None:
            return None
        value = load_config().get(f"{label}_device")
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _should_follow_sink(self) -> bool:
        """デフォルト Sink の変更でモニターを張り替えてよいか。

        CLI でも config でもモニターを固定していない場合だけ追従する。固定して
        いるのに追従すると、出力先を変えるたび同じデバイスを開き直すだけになる。
        """
        return self.args.monitor is None and self._requested_device("monitor") is None

    def _resolve(self, label: str, index: int | None) -> AudioDevice | None:
        """デバイスを解決する。優先順位は CLI 番号 > config のデバイス名 > 自動。

        config の名前が見つからない場合は自動にフォールバックする。設定値は
        書き換えない（デバイスが戻ったら復帰させるため）。
        """
        if index is not None:
            return self._resolve_index(label, index)
        if requested := self._requested_device(label):
            if (found := find_device_by_name(requested, capture=True)) is not None:
                return found
            logger.info("%s: 指定デバイス %s が見つかりません。自動で代替します",
                        label, requested)
        resolve = resolve_mic_device if label == "mic" else resolve_monitor_device
        return resolve(None)

    def _resolve_index(self, label: str, index: int) -> AudioDevice | None:
        """番号指定を解決する。前回開いた名前と一致するものを優先する。

        refresh_device_list() の後は同じ番号が別のデバイスを指しうるため、番号だけを
        頼りにすると無言で別のマイクを掴む。
        """
        resolve = resolve_mic_device if label == "mic" else resolve_monitor_device
        device = resolve(index)
        pinned = self._pinned_names.get(label)
        if pinned and device is not None and device.name != pinned:
            if (found := find_device_by_name(pinned, capture=label == "mic")) is not None:
                logger.info("%s: 番号 %d は %s に変わったため名前で再解決: %s",
                            label, index, device.name, found)
                return found
            logger.warning("%s: 指定デバイス %s が見つかりません。番号 %d の %s を使います",
                           label, pinned, index, device.name)
        if device is not None:
            self._pinned_names[label] = device.name
        return device

    def _open_capture(self, label: str, device: AudioDevice | None, audio_queue: queue.Queue,
                      follow_sink: bool = False,
                      requested: str | None = None) -> _CaptureStream | None:
        """キャプチャストリームを開く。一時的な失敗に備えて 1 度だけリトライする。"""
        if device is None:
            return None
        for attempt in range(2):
            stream = _CaptureStream(label, device, audio_queue, follow_sink, requested,
                                    level=self.levels[label])
            if stream.open():
                return stream
            if attempt == 0 and self.stop_event.wait(1.0):
                break
        return None

    def _open_requested(self, label: str, index: int | None,
                        audio_queue: queue.Queue,
                        follow_sink: bool = False) -> _CaptureStream | None:
        """指定デバイスで開き、失敗したら自動デバイスで開き直す。

        列挙はできても他アプリが排他的に掴んでいて開けないことがある。設定値は
        書き換えず、戻ってきたら復帰判定で拾い直す。
        """
        requested = self._requested_device(label)
        stream = self._open_capture(label, self._resolve(label, index), audio_queue,
                                    follow_sink, requested)
        if stream is not None or not requested:
            return stream
        logger.info("%s: 指定デバイス %s を開けません。自動で代替します", label, requested)
        resolve = resolve_mic_device if label == "mic" else resolve_monitor_device
        return self._open_capture(label, resolve(None), audio_queue, follow_sink, requested)

    def _watch_streams(self, streams: list[_CaptureStream],
                       degraded_wait: float | None = None) -> _Reconnect | None:
        """ストリームを監視し、張り替え要求を返す。停止要求なら None。

        degraded_wait は一部のデバイスを開けていない場合の再試行間隔。
        """
        if not streams:
            # 1 本も開けていない。即座に返すと再列挙のビジーループになるので待つ
            if self.stop_event.wait(degraded_wait or STREAM_DEGRADED_RETRY_SEC):
                return None
            # この経路が返す張り替えは refresh=True で再列挙するので、手動リクエスト
            # はここで満たされる。消さずに残すと、ストリームが復帰した後の最初の
            # 監視ティックでもう一度余計な全系統再列挙が起きる
            self._manual_device_refresh = False
            return _Reconnect("キャプチャデバイスを取得できません")
        retry_at = time.monotonic() + degraded_wait if degraded_wait else None
        next_resolve = time.monotonic() + STREAM_RESOLVE_INTERVAL
        while not self.stop_event.wait(STREAM_CHECK_INTERVAL):
            if retry_at is not None and time.monotonic() >= retry_at:
                return _Reconnect("開けていないデバイスの再試行")
            for stream in streams:
                if (idle := stream.idle_sec()) > STREAM_STALL_SEC:
                    return _Reconnect(
                        f"{stream.label} のフレームが {idle:.0f} 秒途絶 "
                        f"({stream.device.name})")
            if (req := self._config_changed(streams)) is not None:
                return req
            if self._manual_device_refresh:
                # 消費したら必ずクリアする。1 回のリクエストで再列挙は 1 回だけ起きる
                self._manual_device_refresh = False
                return _Reconnect("ダッシュボードから手動デバイス再検出をリクエスト")
            if time.monotonic() < next_resolve:
                continue
            next_resolve = time.monotonic() + STREAM_RESOLVE_INTERVAL
            # ここから先は wpctl を叩く同期呼び出しが並ぶ。停止要求が来ていたら
            # 入る前に抜けて、shutdown の join (5 秒) を subprocess 待ちで
            # 食い潰さないようにする
            if self.stop_event.is_set():
                return None
            for stream in streams:
                if (new_sink := stream.changed_sink()) is not None:
                    return _Reconnect(f"デフォルト出力先が変更 {stream.sink} → {new_sink}")
            if (req := self._requested_returned(streams)) is not None:
                return req
        return None

    def _config_changed(self, streams: list[_CaptureStream]) -> _Reconnect | None:
        """設定値が開いた時点から変わっていれば張り替えを要求する（2 秒ごと）"""
        for stream in streams:
            requested = self._requested_device(stream.label)
            if requested == stream.requested:
                continue
            # 目的のデバイスがキャッシュ上にあるなら再列挙は要らず、
            # この系統だけ開き直せばもう一方の音声は途切れない
            cached = (requested is None
                      or find_device_by_name(requested, capture=True) is not None)
            return _Reconnect(
                f"{stream.label} の指定デバイスが変更 {stream.requested} → {requested}",
                labels=frozenset({stream.label}), refresh=not cached)
        self._sync_backend_monitor_config()
        return None

    def _sync_backend_monitor_config(self) -> None:
        """バックエンド (pw-record/parec) 稼働中の monitor_device 変更を反映させる。

        フォールバック中のモニターは PortAudio ストリームではないので streams に
        載らず、上のループでは設定変更を拾えない。放置すると次に子プロセスが
        死ぬまで（何時間も）新しい選択が反映されない。

        ここでは再起動を「要求」するだけで、監視スレッド側はモニターに触らない。
        実際に開き直すのはバックエンドスレッド自身なので、どちらがモニターを
        持っているかが曖昧にならない。
        """
        if self._monitor_backend is None or not self._monitor_backend.is_alive():
            return
        requested = self._requested_device("monitor")
        if requested == self._monitor_backend_requested:
            return
        logger.info("monitor の指定デバイスが変更 %s → %s、"
                    "バックエンドキャプチャを再起動します",
                    self._monitor_backend_requested, requested)
        self._monitor_backend_requested = requested
        self._monitor_restart.set()

    def _requested_returned(self, streams: list[_CaptureStream]) -> _Reconnect | None:
        """フォールバック中の指定デバイスが抜き差し等で戻っていれば張り替えを要求する
        （最短 10 秒ごと、空振りが続けば指数バックオフ）。

        再列挙が要るのは、そのデバイスがまだ PortAudio のキャッシュに無い場合だけ。
        キャッシュ上には既にあるのにフォールバック中なら、開こうとして失敗した
        （他アプリに排他的に掴まれている等）ということであり、再列挙しても開ける
        ようにはならない。ここで検知すると 10 秒ごとに無意味な張り替えが起き、
        もう一方の健全なストリームまで巻き込んで破棄してしまう

        条件が揃っていても、再列挙で開けるようにならないことがある:
        refresh_device_list() 自体が失敗する / sd.query_devices() が失敗する /
        設定が Sink 名を指している（device_exists は wpctl の Sinks も見るので
        「OS 上には常に在る」が capture デバイスとしては永久に見つからない）。
        いずれも同じ条件が 10 秒後にもそのまま成立するため、バックオフが無いと
        会議中ずっと 10 秒ごとに全系統の再列挙と音の欠落が続く。そこで縮退時の
        再試行と同じ指数バックオフを、デバイス名ごとに掛ける。
        """
        now = time.monotonic()
        for stream in streams:
            if not stream.requested or stream.device.name == stream.requested:
                # 目的のデバイスで開けている。次に外れたときは即座に試せるよう戻す
                self._return_backoff.pop(stream.label, None)
                continue
            backoff = self._return_backoff.get(stream.label)
            if backoff is not None and backoff[0] == stream.requested and now < backoff[1]:
                continue
            if self.stop_event.is_set():
                return None
            if find_device_by_name(stream.requested, capture=True) is not None:
                continue
            if device_exists(stream.requested) is not True:
                continue
            wait = (min(backoff[2] * 2, STREAM_DEGRADED_RETRY_MAX_SEC)
                    if backoff is not None and backoff[0] == stream.requested
                    else STREAM_DEGRADED_RETRY_SEC)
            self._return_backoff[stream.label] = (stream.requested, now + wait, wait)
            return _Reconnect(
                f"{stream.label} の指定デバイスが復帰 {stream.requested}"
                f" (次の再試行まで {wait:.0f} 秒)",
                labels=frozenset({stream.label}), refresh=True)
        return None

    def _vad_thread_for_queue(self, audio_queue: queue.Queue, segmenter: VADSegmenter,
                              label: str):
        """指定キューからフレームを読み VAD セグメンテーションを行うスレッド"""
        logger.info("VAD スレッド開始: %s", label)
        command_mode_latch = False  # セグメント中に一度でも command_mode なら True を維持
        PTT_GRACE_SEC = 1.5  # キーリリース後の猶予時間
        interim_seq = 0
        last_interim_time = 0.0
        interim_enabled = load_config().get("interim_transcription", False)

        while not self.stop_event.is_set():
            try:
                frame = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # フレームサイズ調整
            if len(frame) != FRAME_SIZE:
                if len(frame) > FRAME_SIZE:
                    frame = frame[:FRAME_SIZE]
                else:
                    frame = np.pad(frame, (0, FRAME_SIZE - len(frame)))

            # コマンドモード判定: キー押下中 or リリース後の猶予期間内
            # PTT はユーザーのマイクにのみ適用する。monitor スレッドがラッチや
            # 共有の猶予タイマーを操作すると、リモート参加者のセグメント確定の
            # たびに mic 側の猶予が殺され、コマンドが本文として記録されてしまう
            if label == "mic":
                if self._command_mode or (
                    self._command_mode_release_time > 0
                    and time.time() - self._command_mode_release_time < PTT_GRACE_SEC
                ):
                    command_mode_latch = True
                elif command_mode_latch and not self._command_mode:
                    # 猶予期間が過ぎてもセグメントが生成されなかった場合、ラッチをリセット
                    command_mode_latch = False

            timestamp = time.time()
            segment = segmenter.process_frame(frame, timestamp)
            if segment is not None:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.transcribe_queue.put((segment, ts, label, command_mode_latch))
                command_mode_latch = False  # 次のセグメント用にリセット
                if label == "mic":
                    self._command_mode_release_time = 0.0  # 猶予タイマーもクリア
                interim_seq += 1
                last_interim_time = 0.0
                # final segment 確定時に config を再読み込み（ランタイム切替対応）
                interim_enabled = load_config().get("interim_transcription", False)
            elif interim_enabled and label == "monitor" and segmenter.in_speech:
                now = time.time()
                if now - last_interim_time >= 1.5:
                    interim_audio = segmenter.get_interim_segment()
                    if interim_audio is not None:
                        try:
                            self.interim_queue.put_nowait(
                                (interim_audio, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 label, interim_seq))
                        except queue.Full:
                            pass  # best effort
                        last_interim_time = now

        # フラッシュ
        segment = segmenter.flush()
        if segment is not None:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.transcribe_queue.put((segment, ts, label, command_mode_latch))
