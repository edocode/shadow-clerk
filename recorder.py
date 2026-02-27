#!/usr/bin/env python3
"""Shadow-clerk recorder: 音声キャプチャ・VAD・文字起こし"""

import argparse
import datetime
import io
import logging
import os
import queue
import re
import shutil
import signal
import struct
import subprocess
import sys
import threading
import time
import wave

import numpy as np
import sounddevice as sd
import webrtcvad
import yaml

logger = logging.getLogger("shadow-clerk")

# --- 定数 ---
SAMPLE_RATE = 16000
CHANNELS = 1
DTYPE = "int16"
FRAME_DURATION_MS = 30  # webrtcvad フレームサイズ
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION_MS / 1000)  # 480 samples

# VAD パラメータ
VAD_MODE = 3  # 0-3, 3が最も積極的に音声検出
SPEECH_FRAMES_THRESHOLD = 10  # 発話検出に必要な連続フレーム数 (~300ms)
SILENCE_FRAMES_THRESHOLD = 30  # 無音検出に必要な連続フレーム数 (~900ms)
MIN_SEGMENT_DURATION = 0.5  # 最小セグメント長(秒)
MAX_SEGMENT_DURATION = 30.0  # 最大セグメント長(秒)

# データディレクトリ
DATA_DIR = os.path.expanduser("~/.claude/skills/shadow-clerk/data")
os.makedirs(DATA_DIR, exist_ok=True)

# 設定ファイル
CONFIG_FILE = os.path.join(DATA_DIR, "config.yaml")

DEFAULT_CONFIG = {
    "translate_language": "ja",
    "auto_translate": False,
    "auto_summary": False,
    "default_language": None,
    "default_model": "small",
    "output_directory": None,
}


def load_config() -> dict:
    """config.yaml を読み込む。ファイルがなければデフォルト値を返す。"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f)
            if isinstance(user_config, dict):
                merged = dict(DEFAULT_CONFIG)
                merged.update(user_config)
                return merged
        except Exception as e:
            logger.warning("config.yaml の読み込みに失敗: %s", e)
    return dict(DEFAULT_CONFIG)


# コマンド・セッションファイル
COMMAND_FILE = os.path.join(DATA_DIR, ".clerk_command")
SESSION_FILE = os.path.join(DATA_DIR, ".clerk_session")
WORDS_FILE = os.path.join(DATA_DIR, "words.txt")

# 音声コマンド検出パターン
VOICE_CMD_PREFIX = re.compile(r"(?i)^[\s]*(?:clerk|クラ[ーァ]ク)[,、\s]*")
VOICE_COMMANDS = [
    (re.compile(r"(言語設定なし|unset\s*language)", re.IGNORECASE), "unset_language"),
    (re.compile(r"(言語.*(日本語|ja)|language.*ja)", re.IGNORECASE), "set_language ja"),
    (re.compile(r"(言語.*(英語|en)|language.*en)", re.IGNORECASE), "set_language en"),
    (re.compile(r"(会議開始|start\s*meeting)", re.IGNORECASE), "start_meeting"),
    (re.compile(r"(会議終了|end\s*meeting)", re.IGNORECASE), "end_meeting"),
]


DEFAULT_CONFIG = {
    "translate_language": "ja",
    "auto_translate": False,
    "auto_summary": False,
    "default_language": None,
    "default_model": "small",
}


def load_config() -> dict:
    """config.yaml を読み込む。ファイルがなければデフォルト値を返す。"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            return dict(DEFAULT_CONFIG)
        merged = dict(DEFAULT_CONFIG)
        merged.update({k: v for k, v in config.items() if k in DEFAULT_CONFIG})
        return merged
    except FileNotFoundError:
        return dict(DEFAULT_CONFIG)


class WordReplacer:
    """words.txt (TSV) によるテキスト置換。ファイル変更時は自動再読み込み。"""

    def __init__(self, path: str = WORDS_FILE):
        self._path = path
        self._replacements: list[tuple[str, str]] = []
        self._mtime: float | None = None
        self._load()

    def _load(self):
        try:
            mtime = os.path.getmtime(self._path)
            if mtime == self._mtime:
                return
            self._mtime = mtime
            replacements = []
            with open(self._path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t", 1)
                    if len(parts) == 2 and parts[0]:
                        replacements.append((parts[0], parts[1]))
            self._replacements = replacements
            logger.info("words.txt 読み込み: %d 件", len(replacements))
        except FileNotFoundError:
            if self._mtime is not None:
                self._replacements = []
                self._mtime = None
                logger.info("words.txt が削除されました")

    def apply(self, text: str) -> str:
        self._load()
        for wrong, correct in self._replacements:
            text = text.replace(wrong, correct)
        return text


class AudioBackend:
    """音声バックエンド基底クラス"""

    def detect_monitor_source(self) -> str | None:
        raise NotImplementedError

    def list_devices(self):
        raise NotImplementedError


class PipeWireBackend(AudioBackend):
    """PipeWire バックエンド"""

    @staticmethod
    def is_available() -> bool:
        return shutil.which("pw-record") is not None

    def detect_monitor_source(self) -> str | None:
        try:
            result = subprocess.run(
                ["pw-record", "--list-targets"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "monitor" in line.lower():
                    return line.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def list_devices(self):
        print("\n=== PipeWire デバイス ===")
        try:
            result = subprocess.run(
                ["pw-record", "--list-targets"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print("  (デバイスが見つかりません)")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print("  (pw-record が利用できません)")

    def start_monitor_capture(self, target: str, audio_queue: queue.Queue,
                              stop_event: threading.Event):
        """pw-record でモニターソースをキャプチャ"""
        cmd = [
            "pw-record", "--target", target,
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--format", "s16",
            "-",
        ]
        logger.info("PipeWire monitor capture: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while not stop_event.is_set():
                data = proc.stdout.read(FRAME_SIZE * 2)
                if not data:
                    break
                if len(data) == FRAME_SIZE * 2:
                    samples = np.frombuffer(data, dtype=np.int16)
                    audio_queue.put(samples)
        finally:
            proc.terminate()
            proc.wait()


class PulseAudioBackend(AudioBackend):
    """PulseAudio バックエンド"""

    @staticmethod
    def is_available() -> bool:
        return shutil.which("pactl") is not None

    def detect_monitor_source(self) -> str | None:
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if ".monitor" in line:
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        return parts[1]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def list_devices(self):
        print("\n=== PulseAudio ソース ===")
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print("  (ソースが見つかりません)")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print("  (pactl が利用できません)")

    def start_monitor_capture(self, source: str, audio_queue: queue.Queue,
                              stop_event: threading.Event):
        """parec でモニターソースをキャプチャ"""
        cmd = [
            "parec",
            f"--device={source}",
            f"--rate={SAMPLE_RATE}",
            "--channels=1",
            "--format=s16le",
        ]
        logger.info("PulseAudio monitor capture: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            while not stop_event.is_set():
                data = proc.stdout.read(FRAME_SIZE * 2)
                if not data:
                    break
                if len(data) == FRAME_SIZE * 2:
                    samples = np.frombuffer(data, dtype=np.int16)
                    audio_queue.put(samples)
        finally:
            proc.terminate()
            proc.wait()


def detect_backend(preferred: str = "auto") -> tuple[str, AudioBackend | None]:
    """音声バックエンドを検出"""
    if preferred == "pipewire":
        if PipeWireBackend.is_available():
            return "pipewire", PipeWireBackend()
        logger.warning("PipeWire が利用できません、sounddevice にフォールバック")
        return "sounddevice", None

    if preferred == "pulseaudio":
        if PulseAudioBackend.is_available():
            return "pulseaudio", PulseAudioBackend()
        logger.warning("PulseAudio が利用できません、sounddevice にフォールバック")
        return "sounddevice", None

    if preferred == "sounddevice":
        return "sounddevice", None

    # auto: PipeWire → PulseAudio → sounddevice
    if PipeWireBackend.is_available():
        return "pipewire", PipeWireBackend()
    if PulseAudioBackend.is_available():
        return "pulseaudio", PulseAudioBackend()
    return "sounddevice", None


def _get_default_sink_name() -> str | None:
    """wpctl/pactl でデフォルト Sink の名前を取得"""
    # wpctl (PipeWire)
    if shutil.which("wpctl"):
        try:
            result = subprocess.run(
                ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                line = line.strip().lstrip("* ")
                if line.startswith("node.name"):
                    # node.name = "alsa_output.usb-Shokz..."
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        name = parts[1].strip().strip('"')
                        logger.debug("デフォルト Sink (wpctl): %s", name)
                        return name
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # pactl (PulseAudio)
    if shutil.which("pactl"):
        try:
            result = subprocess.run(
                ["pactl", "get-default-sink"],
                capture_output=True, text=True, timeout=5,
            )
            name = result.stdout.strip()
            if name:
                logger.debug("デフォルト Sink (pactl): %s", name)
                return name
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return None


def find_monitor_device_sd() -> int | None:
    """sounddevice でモニターデバイスを検索

    `.monitor` サフィックスを持つ入力デバイスのみを対象とする。
    デフォルト Sink に対応するモニターを優先する。
    """
    devices = sd.query_devices()
    candidates = []
    for i, dev in enumerate(devices):
        name = dev["name"]
        if name.endswith(".monitor") and dev["max_input_channels"] > 0:
            candidates.append((i, name))
            logger.debug("monitor 候補: #%d %s", i, name)

    if not candidates:
        logger.debug("monitor 候補なし")
        return None

    # デフォルト Sink に対応するモニターを優先
    default_sink = _get_default_sink_name()
    if default_sink:
        expected_monitor = default_sink + ".monitor"
        for idx, name in candidates:
            if name == expected_monitor:
                logger.debug("デフォルト Sink のモニター選択: #%d %s", idx, name)
                return idx

    # 見つからなければ最初の候補
    logger.debug("デフォルト Sink 不明、最初の候補を選択: #%d %s", *candidates[0])
    return candidates[0][0]


def list_all_devices(backend_name: str, backend: AudioBackend | None):
    """全デバイス一覧表示"""
    print("=== sounddevice デバイス ===")
    print(sd.query_devices())

    if backend:
        backend.list_devices()

    monitor_sd = find_monitor_device_sd()
    if monitor_sd is not None:
        print(f"\n[自動検出] sounddevice monitor: device #{monitor_sd}")

    if backend:
        monitor = backend.detect_monitor_source()
        if monitor:
            print(f"[自動検出] {backend_name} monitor: {monitor}")


# --- VAD セグメンテーション ---
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

    def flush(self) -> np.ndarray | None:
        """残っているセグメントを強制出力"""
        if self.in_speech and self.current_segment:
            return self._finalize_segment()
        return None


# --- 文字起こし ---
class Transcriber:
    """faster-whisper による文字起こし"""

    def __init__(self, model_size: str = "small", language: str | None = None):
        self.model_size = model_size
        self.language = language
        self.model = None

    def load_model(self):
        from faster_whisper import WhisperModel
        logger.info("Whisper モデル読み込み中: %s ...", self.model_size)
        self.model = WhisperModel(
            self.model_size,
            device="cpu",
            compute_type="int8",
        )
        logger.info("モデル読み込み完了")

    def reload_model(self, model_size: str):
        self.model_size = model_size
        self.model = None
        self.load_model()

    def transcribe(self, audio: np.ndarray) -> str:
        """音声セグメントを文字起こし"""
        if self.model is None:
            self.load_model()

        # faster-whisper は float32 の numpy 配列を受け付ける
        audio_f32 = audio.astype(np.float32) / 32768.0

        segments, info = self.model.transcribe(
            audio_f32,
            language=self.language,
            beam_size=5,
            vad_filter=False,  # 自前のVADを使用
        )

        text_parts = []
        for seg in segments:
            text_parts.append(seg.text.strip())

        return " ".join(text_parts)


# --- メインレコーダー ---
class Recorder:
    """音声キャプチャ・VAD・文字起こしの統合"""

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.stop_event = threading.Event()
        self.mic_queue: queue.Queue[np.ndarray] = queue.Queue()
        self.monitor_queue: queue.Queue[np.ndarray] = queue.Queue()
        self.vad_queue: queue.Queue[np.ndarray] = queue.Queue()
        self.transcribe_queue: queue.Queue[tuple[np.ndarray, str]] = queue.Queue()

        self.backend_name, self.backend = detect_backend(args.backend)
        self.transcriber = Transcriber(
            model_size=args.model,
            language=args.language,
        )

        # output_directory: config で指定されていればそちらを使う
        config = load_config()
        output_dir_config = config.get("output_directory")
        if output_dir_config:
            self._output_dir = os.path.expanduser(output_dir_config)
            os.makedirs(self._output_dir, exist_ok=True)
        else:
            self._output_dir = DATA_DIR

        # --output が指定されていれば固定、なければ日付ベースのデフォルト
        self._explicit_output = args.output is not None
        self.output_path = args.output if self._explicit_output else self._get_default_output()
        self.use_monitor = True
        self.use_mic = True
        self.word_replacer = WordReplacer()

    def _get_default_output(self) -> str:
        """現在日付ベースのデフォルト transcript パスを返す"""
        filename = datetime.datetime.now().strftime("transcript-%Y%m%d.txt")
        return os.path.join(self._output_dir, filename)

    def _setup_signal_handlers(self):
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
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=FRAME_SIZE,
                device=mic_device,
                callback=callback,
            ):
                self.stop_event.wait()
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
            self._monitor_capture_sounddevice(monitor_device)
            return

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

    def _monitor_capture_sounddevice(self, device):
        """sounddevice でモニターデバイスをキャプチャ"""
        def callback(indata, frames, time_info, status):
            if status:
                logger.warning("モニター status: %s", status)
            self.monitor_queue.put(indata[:, 0].copy().astype(np.int16))

        try:
            with sd.InputStream(
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=FRAME_SIZE,
                device=device,
                callback=callback,
            ):
                self.stop_event.wait()
        except sd.PortAudioError as e:
            logger.error("モニターキャプチャエラー: %s", e)
            self.use_monitor = False

    def _vad_thread_for_queue(self, audio_queue: queue.Queue, segmenter: VADSegmenter,
                              label: str):
        """指定キューからフレームを読み VAD セグメンテーションを行うスレッド"""
        logger.info("VAD スレッド開始: %s", label)

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

            timestamp = time.time()
            segment = segmenter.process_frame(frame, timestamp)
            if segment is not None:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.transcribe_queue.put((segment, ts, label))

        # フラッシュ
        segment = segmenter.flush()
        if segment is not None:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.transcribe_queue.put((segment, ts, label))

    def _check_voice_command(self, text: str) -> str | None:
        """文字起こし結果から音声コマンドを検出。コマンド文字列 or None を返す"""
        if not VOICE_CMD_PREFIX.match(text):
            return None
        # プレフィックス以降の部分でコマンドマッチ
        body = VOICE_CMD_PREFIX.sub("", text)
        for pattern, command in VOICE_COMMANDS:
            if pattern.search(body):
                return command
        return None

    def _execute_command(self, cmd: str):
        """コマンド文字列をパースして実行"""
        cmd = cmd.strip()
        if not cmd:
            return

        if cmd.startswith("set_language "):
            lang = cmd.split(None, 1)[1].strip()
            self.transcriber.language = lang
            logger.info("言語を変更: %s", lang)

        elif cmd == "unset_language":
            self.transcriber.language = None
            logger.info("言語を自動検出に変更")

        elif cmd.startswith("start_meeting"):
            parts = cmd.split(None, 1)
            now = datetime.datetime.now()
            filename = now.strftime("transcript-%Y%m%d%H%M.txt")
            self.output_path = os.path.join(self._output_dir, filename)
            marker = f"--- 会議開始 {now.strftime('%Y-%m-%d %H:%M')} ---\n"
            with open(self.output_path, "a", encoding="utf-8") as f:
                f.write(marker)
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                f.write(self.output_path)
            logger.info("会議開始: %s", self.output_path)
            print(f"会議開始: {self.output_path}")

        elif cmd == "end_meeting":
            marker = "--- 会議終了 ---\n"
            with open(self.output_path, "a", encoding="utf-8") as f:
                f.write(marker)
            logger.info("会議終了: %s", self.output_path)
            print(f"会議終了: {self.output_path}")
            # 明示的 output 指定の場合はその値に戻す、そうでなければ現在日付のデフォルト
            if self._explicit_output:
                self.output_path = self.args.output
            else:
                self.output_path = self._get_default_output()
            try:
                os.remove(SESSION_FILE)
            except FileNotFoundError:
                pass

        elif cmd.startswith("set_model "):
            model_size = cmd.split(None, 1)[1].strip()
            logger.info("モデル変更中: %s ...", model_size)
            print(f"モデル変更中: {model_size} ...")
            self.transcriber.reload_model(model_size)
            logger.info("モデル変更完了: %s", model_size)
            print(f"モデル変更完了: {model_size}")

        else:
            logger.warning("不明なコマンド: %s", cmd)

    def _command_watch_thread(self):
        """コマンドファイルをポーリングして実行するスレッド"""
        logger.info("コマンド監視スレッド開始")
        while not self.stop_event.is_set():
            try:
                if os.path.exists(COMMAND_FILE):
                    with open(COMMAND_FILE, "r", encoding="utf-8") as f:
                        cmd = f.read().strip()
                    os.remove(COMMAND_FILE)
                    if cmd:
                        logger.info("コマンドファイル検出: %s", cmd)
                        self._execute_command(cmd)
            except Exception as e:
                logger.error("コマンド処理エラー: %s", e)
            self.stop_event.wait(timeout=0.5)

    def _transcribe_thread(self):
        """文字起こしスレッド"""
        logger.info("文字起こしスレッド開始")
        self.transcriber.load_model()

        speaker_labels = {"mic": "自分", "monitor": "相手"}

        while not self.stop_event.is_set():
            try:
                segment, timestamp, source = self.transcribe_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            duration = len(segment) / SAMPLE_RATE
            speaker = speaker_labels.get(source, source)
            logger.info("文字起こし中 (%s, %.1f秒)...", speaker, duration)

            text = self.transcriber.transcribe(segment)
            if text.strip():
                # mic ソースからの音声コマンド検出
                if source == "mic":
                    voice_cmd = self._check_voice_command(text)
                    if voice_cmd:
                        logger.info("音声コマンド検出: %s → %s", text.strip(), voice_cmd)
                        self._execute_command(voice_cmd)
                        continue

                # 日付変更チェック（セッション中でなく、明示的 output 指定でない場合のみ）
                if not self._explicit_output and not os.path.exists(SESSION_FILE):
                    new_path = self._get_default_output()
                    if new_path != self.output_path:
                        logger.info("日付変更検出、出力先切り替え: %s", new_path)
                        self.output_path = new_path

                text = self.word_replacer.apply(text)
                line = f"[{timestamp}] [{speaker}] {text}\n"
                with open(self.output_path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                print(f"  {line.rstrip()}")
            else:
                logger.debug("空テキスト、スキップ")

        # キュー残りを処理
        while not self.transcribe_queue.empty():
            try:
                segment, timestamp, source = self.transcribe_queue.get_nowait()
                speaker = speaker_labels.get(source, source)
                text = self.transcriber.transcribe(segment)
                if text.strip():
                    text = self.word_replacer.apply(text)
                    line = f"[{timestamp}] [{speaker}] {text}\n"
                    with open(self.output_path, "a", encoding="utf-8") as f:
                        f.write(line)
                        f.flush()
                    print(f"  {line.rstrip()}")
            except queue.Empty:
                break

    def run(self):
        """メイン実行"""
        self._setup_signal_handlers()

        logger.info("Shadow-clerk recorder 開始")
        logger.info("バックエンド: %s", self.backend_name)
        logger.info("出力先: %s", self.output_path)
        logger.info("モデル: %s", self.args.model)
        logger.info("言語: %s", self.args.language or "auto")
        print(f"録音中... (Ctrl+C で停止)")
        print(f"出力先: {self.output_path}")

        self.mic_segmenter = VADSegmenter()
        self.monitor_segmenter = VADSegmenter()

        threads = [
            threading.Thread(target=self._mic_capture_thread, name="mic-capture", daemon=True),
            threading.Thread(target=self._monitor_capture_thread, name="monitor-capture", daemon=True),
            threading.Thread(
                target=self._vad_thread_for_queue,
                args=(self.mic_queue, self.mic_segmenter, "mic"),
                name="vad-mic", daemon=True,
            ),
            threading.Thread(
                target=self._vad_thread_for_queue,
                args=(self.monitor_queue, self.monitor_segmenter, "monitor"),
                name="vad-monitor", daemon=True,
            ),
            threading.Thread(target=self._transcribe_thread, name="transcribe", daemon=True),
            threading.Thread(target=self._command_watch_thread, name="cmd-watch", daemon=True),
        ]

        for t in threads:
            t.start()

        # メインスレッドで待機
        try:
            while not self.stop_event.is_set():
                self.stop_event.wait(timeout=0.5)
        except KeyboardInterrupt:
            self.stop_event.set()

        logger.info("スレッド終了待機中...")
        for t in threads:
            t.join(timeout=5.0)

        logger.info("Shadow-clerk recorder 終了")


def main():
    parser = argparse.ArgumentParser(
        description="Shadow-clerk: Web会議の音声を録音・文字起こし",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help=f"文字起こし出力ファイル (default: {DATA_DIR}/transcript-YYYYMMDD.txt)",
    )
    parser.add_argument(
        "--model", "-m",
        default="small",
        help="Whisper モデルサイズ (default: small)",
    )
    parser.add_argument(
        "--language", "-l",
        default=None,
        help="言語コード (例: ja, en)。未指定で自動検出",
    )
    parser.add_argument(
        "--mic",
        default=None,
        type=int,
        help="マイクデバイス番号",
    )
    parser.add_argument(
        "--monitor",
        default=None,
        type=int,
        help="モニターデバイス番号 (sounddevice)",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "pipewire", "pulseaudio", "sounddevice"],
        default="auto",
        help="音声バックエンド (default: auto)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="デバイス一覧を表示して終了",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="詳細ログ出力",
    )

    args = parser.parse_args()

    # config.yaml の値を CLI 未指定の場合のみ適用
    config = load_config()
    if args.model == "small" and config.get("default_model"):
        args.model = config["default_model"]
    if args.language is None and config.get("default_language"):
        args.language = config["default_language"]

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_devices:
        backend_name, backend = detect_backend(args.backend)
        print(f"バックエンド: {backend_name}")
        list_all_devices(backend_name, backend)
        return

    recorder = Recorder(args)
    recorder.run()


if __name__ == "__main__":
    main()
