"""Shadow-clerk daemon: レコーダー音声キャプチャ・VAD ミックスイン"""
import datetime
import logging
import os
import queue
import re
import threading
import time
import numpy as np
import sounddevice as sd
from shadow_clerk import DATA_DIR
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import (
    SAMPLE_RATE, FRAME_SIZE, CHANNELS, DTYPE,
    COMMAND_FILE, SESSION_FILE, GLOSSARY_FILE,
    VOICE_CMD_PREFIX, VOICE_CMD_SUFFIX, VOICE_COMMANDS,
    pynput_keyboard, _HAS_PYNPUT, evdev, _ecodes, _HAS_EVDEV,
)
from shadow_clerk._daemon_config import load_config, get_translation_provider, _builtin_command_descs
from shadow_clerk._daemon_audio import detect_backend, find_monitor_device_sd
from shadow_clerk._daemon_vad import VADSegmenter
from shadow_clerk._daemon_transcriber import Transcriber, GlossaryReplacer
from shadow_clerk._daemon_dashboard import LogBuffer, FileWatcher, DashboardHandler

try:
    from shadow_clerk.llm_client import get_api_client, load_glossary, load_glossary_replacements, load_dotenv as llm_load_dotenv, _spell_check
    _HAS_LLM_CLIENT = True
except ImportError:
    _HAS_LLM_CLIENT = False

logger = logging.getLogger("shadow-clerk")


class _RecorderCaptureMixin:
    """音声キャプチャ・VAD ミックスイン"""

    def __init__(self, args):
        self.args = args
        self.stop_event = threading.Event()
        self.mic_queue: queue.Queue = queue.Queue()
        self.monitor_queue: queue.Queue = queue.Queue()
        self.vad_queue: queue.Queue = queue.Queue()
        self.transcribe_queue: queue.Queue = queue.Queue()
        self.interim_queue: queue.Queue = queue.Queue(maxsize=2)

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

        # Whisper initial_prompt: トリガーワード + ユーザー指定プロンプト
        default_prompt = "クラーク"
        user_prompt = config.get("initial_prompt")
        initial_prompt = f"{default_prompt}、{user_prompt}" if user_prompt else default_prompt

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

        # 翻訳ループ
        self._translate_stop_event = threading.Event()
        self._translate_thread: threading.Thread | None = None
        self._translating_external = False  # Claude provider 経由の翻訳中フラグ

        # リアルタイム interim 翻訳キュー (maxsize=1 で最新のみ保持)
        self._interim_translate_queue: queue.Queue = queue.Queue(maxsize=1)

    def _get_default_output(self) -> str:
        """現在日付ベースのデフォルト transcript パスを返す"""
        filename = datetime.datetime.now().strftime("transcript-%Y%m%d.txt")
        return os.path.join(self._output_dir, filename)

    def _setup_signal_handlers(self):
        import signal

        def handler(signum, frame):
            logger.info("シグナル受信 (%s)、終了処理中...", signal.Signals(signum).name)
            self.stop_event.set()

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def _mic_capture_thread(self):
        """マイク音声キャプチャスレッド"""
        mic_device = self.args.mic
        logger.info("マイクキャプチャ開始 (device=%s)", mic_device)

        def callback(indata, frames, time_info, status):
            if status:
                logger.warning("マイク status: %s", status)
            self.mic_queue.put(indata[:, 0].copy().astype(np.int16))

        try:
            with self._stream_lock:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    blocksize=FRAME_SIZE,
                    device=mic_device,
                    callback=callback,
                )
                stream.start()
            self.stop_event.wait()
            stream.stop()
            stream.close()
        except sd.PortAudioError as e:
            logger.error("マイクキャプチャエラー: %s", e)
            self.use_mic = False

    def _monitor_capture_thread(self):
        """モニター音声キャプチャスレッド"""
        # sounddevice でモニターデバイスを探す
        monitor_device = self.args.monitor
        if monitor_device is None:
            monitor_device = find_monitor_device_sd()

        if monitor_device is not None:
            dev_info = sd.query_devices(monitor_device)
            logger.info("sounddevice monitor キャプチャ開始 (device=%s: %s)", monitor_device, dev_info["name"])
            if self._monitor_capture_sounddevice(monitor_device):
                return
            # sounddevice 失敗 → バックエンドにフォールバック
            logger.info("sounddevice 失敗、%s バックエンドにフォールバック", self.backend_name)

        # バックエンド固有のモニターキャプチャ
        if self.backend:
            monitor_source = self.backend.detect_monitor_source()
            if monitor_source:
                logger.info("%s monitor キャプチャ開始: %s", self.backend_name, monitor_source)
                self.backend.start_monitor_capture(
                    monitor_source, self.monitor_queue, self.stop_event
                )
                return

        logger.warning("モニターソースが見つかりません。マイクのみで録音します。")
        self.use_monitor = False

    def _monitor_capture_sounddevice(self, device) -> bool:
        """sounddevice でモニターデバイスをキャプチャ。成功なら True、失敗なら False。"""

        def callback(indata, frames, time_info, status):
            if status:
                logger.warning("モニター status: %s", status)
            self.monitor_queue.put(indata[:, 0].copy().astype(np.int16))

        max_retries = 2
        for attempt in range(max_retries):
            try:
                sd._initialize()
                with self._stream_lock:
                    stream = sd.InputStream(
                        samplerate=SAMPLE_RATE,
                        channels=CHANNELS,
                        dtype=DTYPE,
                        blocksize=FRAME_SIZE,
                        device=device,
                        callback=callback,
                    )
                    stream.start()
                self.stop_event.wait()
                stream.stop()
                stream.close()
                return True
            except sd.PortAudioError as e:
                if attempt < max_retries - 1:
                    logger.warning("sounddevice モニターエラー (リトライ %d/%d): %s", attempt + 1, max_retries, e)
                    time.sleep(1)
                else:
                    logger.warning("sounddevice モニター失敗、バックエンドにフォールバック: %s", e)
        return False

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
