#!/usr/bin/env python3
"""Shadow-clerk daemon: 音声キャプチャ・VAD・文字起こし"""

import argparse
import collections
import datetime
import io
import json
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
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import numpy as np
import sounddevice as sd
import webrtcvad
import yaml

from shadow_clerk import DATA_DIR, CONFIG_FILE
from shadow_clerk.i18n import t, t_all

try:
    from shadow_clerk.llm_client import get_api_client, load_glossary, load_dotenv as llm_load_dotenv
    _HAS_LLM_CLIENT = True
except ImportError:
    _HAS_LLM_CLIENT = False

try:
    from pynput import keyboard as pynput_keyboard
    _HAS_PYNPUT = True
except ImportError:
    _HAS_PYNPUT = False

try:
    import evdev
    from evdev import ecodes as _ecodes
    _HAS_EVDEV = True
except ImportError:
    _HAS_EVDEV = False

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

# データディレクトリ（shadow_clerk パッケージから取得）
# DATA_DIR, CONFIG_FILE は from shadow_clerk import で取得済み

DEFAULT_CONFIG = {
    "translate_language": "ja",
    "auto_translate": False,
    "auto_summary": False,
    "default_language": None,
    "default_model": "small",
    "output_directory": None,
    "llm_provider": "claude",
    "api_endpoint": None,
    "api_model": None,
    "api_key_env": "SHADOW_CLERK_API_KEY",
    "custom_commands": [],
    "initial_prompt": None,
    "voice_command_key": "f23",
    "whisper_beam_size": 5,        # beam_size (1=高速, 5=高精度)
    "whisper_compute_type": "int8", # int8/float16/float32
    "whisper_device": "cpu",       # cpu/cuda
    "interim_transcription": False,
    "interim_model": "tiny",
    "ui_language": "ja",
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
GLOSSARY_FILE = os.path.join(DATA_DIR, "glossary.txt")

# 音声コマンド検出パターン
# Whisper の誤認識揺れを許容:
#   クラーク → ブラーク/プラーク/グラーク/クラーゴ/ブラック/フランク/プラグ 等
VOICE_CMD_PREFIX = re.compile(
    r"(?i)^[\s]*(?:clerk|[ブプグクフ][ラー]{1,3}[ーッ]?[クゴグ]|フランク)[,、\s]*"
)
VOICE_CMD_SUFFIX = re.compile(
    r"(?i)[,、\s]*(?:clerk|[ブプグクフ][ラー]{1,3}[ーッ]?[クゴグ]|フランク)[\s]*$"
)
VOICE_COMMANDS = [
    (re.compile(r"(言語設定なし|unset\s*language)", re.IGNORECASE), "unset_language"),
    (re.compile(r"(言語.*(日本語|ja)|language.*ja)", re.IGNORECASE), "set_language ja"),
    (re.compile(r"(言語.*(英語|en)|language.*en)", re.IGNORECASE), "set_language en"),
    (re.compile(r"(会議.*開始|start\s*meeting)", re.IGNORECASE), "start_meeting"),
    (re.compile(r"(会議.*終了|end\s*meeting)", re.IGNORECASE), "end_meeting"),
    (re.compile(r"(翻訳.*(?:開始|始め)|(?:本|ほん)やく.*(?:開始|始め)|start\s*translat)", re.IGNORECASE), "translate_start"),
    (re.compile(r"(翻訳.*(?:停止|止め)|(?:本|ほん)やく.*(?:停止|止め)|stop\s*translat)", re.IGNORECASE), "translate_stop"),
]

def _builtin_command_descs():
    return [
        {"command": "start_meeting", "description": t("vcmd.start_meeting")},
        {"command": "end_meeting", "description": t("vcmd.end_meeting")},
        {"command": "translate_start", "description": t("vcmd.translate_start")},
        {"command": "translate_stop", "description": t("vcmd.translate_stop")},
        {"command": "set_language ja", "description": t("vcmd.set_language_ja")},
        {"command": "set_language en", "description": t("vcmd.set_language_en")},
        {"command": "unset_language", "description": t("vcmd.unset_language")},
    ]


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
        print(t("rec.pipewire_devices"))
        try:
            result = subprocess.run(
                ["pw-record", "--list-targets"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print(t("rec.no_devices"))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print(t("rec.pw_unavailable"))

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
        print(t("rec.pulseaudio_sources"))
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print(t("rec.no_sources"))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print(t("rec.pa_unavailable"))

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
    print(t("rec.sounddevice_devices"))
    print(sd.query_devices())

    if backend:
        backend.list_devices()

    monitor_sd = find_monitor_device_sd()
    if monitor_sd is not None:
        print(t("rec.auto_detect_sd", device=monitor_sd))

    if backend:
        monitor = backend.detect_monitor_source()
        if monitor:
            print(t("rec.auto_detect_backend", backend=backend_name, source=monitor))


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

    def get_interim_segment(self) -> np.ndarray | None:
        """発話中の蓄積音声のコピーを返す（読み取り専用、segmentation に影響しない）"""
        if self.in_speech and self.current_segment:
            duration = len(self.current_segment) * FRAME_DURATION_MS / 1000.0
            if duration >= MIN_SEGMENT_DURATION:
                return np.concatenate(self.current_segment)
        return None

    def flush(self) -> np.ndarray | None:
        """残っているセグメントを強制出力"""
        if self.in_speech and self.current_segment:
            return self._finalize_segment()
        return None


# --- 文字起こし ---
class Transcriber:
    """faster-whisper による文字起こし"""

    def __init__(self, model_size: str = "small", language: str | None = None,
                 initial_prompt: str | None = None,
                 beam_size: int = 5, compute_type: str = "int8",
                 device: str = "cpu"):
        self.model_size = model_size
        self.language = language
        self.initial_prompt = initial_prompt
        self.beam_size = beam_size
        self.compute_type = compute_type
        self.device = device
        self.model = None

    def load_model(self):
        from faster_whisper import WhisperModel
        logger.info("Whisper モデル読み込み中: %s (device=%s, compute_type=%s) ...",
                     self.model_size, self.device, self.compute_type)
        self.model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        logger.info("モデル読み込み完了")

    def reload_model(self, model_size: str):
        self.model_size = model_size
        self.model = None
        self.load_model()

    # Whisper がよく出力するハルシネーション（無音時の誤認識）パターン
    HALLUCINATION_RE = re.compile(
        r"(字幕|ご視聴|ご覧いただき|ありがとうございました|チャンネル登録"
        r"|お疲れ様でした|よろしくお願いします"
        r"|Thank you for watching|Thanks for watching"
        r"|Please subscribe|See you next time"
        r"|Subtitles by|Amara\.org)",
        re.IGNORECASE,
    )

    def transcribe(self, audio: np.ndarray) -> str:
        """音声セグメントを文字起こし"""
        if self.model is None:
            self.load_model()

        # faster-whisper は float32 の numpy 配列を受け付ける
        audio_f32 = audio.astype(np.float32) / 32768.0

        segments, info = self.model.transcribe(
            audio_f32,
            language=self.language,
            beam_size=self.beam_size,
            vad_filter=False,  # 自前のVADを使用
            initial_prompt=self.initial_prompt,
        )

        text_parts = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            # no_speech_prob が高いセグメントはスキップ
            if seg.no_speech_prob > 0.6:
                logger.debug("ハルシネーション除去 (no_speech=%.2f): %s", seg.no_speech_prob, text)
                continue
            # 既知のハルシネーションパターンをフィルタ
            if self.HALLUCINATION_RE.search(text):
                logger.debug("ハルシネーション除去 (パターン): %s", text)
                continue
            text_parts.append(text)

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
        self.interim_queue: queue.Queue = queue.Queue(maxsize=2)

        self.backend_name, self.backend = detect_backend(args.backend)

        # config 読み込み
        config = load_config()

        # カスタム音声コマンドをコンパイル
        self._custom_commands = []
        custom_keywords = []
        for entry in config.get("custom_commands") or []:
            try:
                pat = re.compile(entry["pattern"], re.IGNORECASE)
                self._custom_commands.append((pat, entry["action"]))
                # pattern から語彙ヒント用キーワードを抽出（| 区切りを分割）
                for kw in entry["pattern"].split("|"):
                    kw = kw.strip()
                    if kw:
                        custom_keywords.append(kw)
            except (KeyError, re.error) as e:
                logger.warning("カスタムコマンド定義エラー: %s — %s", entry, e)

        # Whisper initial_prompt: 音声コマンドのキーワードをヒントとして与える
        default_prompt = "クラーク、会議開始、会議終了、翻訳開始、翻訳停止、言語設定"
        if custom_keywords:
            default_prompt += "、" + "、".join(custom_keywords)
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

        # api_endpoint の有無を記憶（LLM フォールバック判定用）
        self._api_configured = bool(config.get("api_endpoint"))

        # output_directory: config で指定されていればそちらを使う
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

        # リアルタイム interim 翻訳キュー (maxsize=1 で最新のみ保持)
        self._interim_translate_queue: queue.Queue = queue.Queue(maxsize=1)

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

    def _check_voice_command(self, text: str) -> str | None:
        """文字起こし結果から音声コマンドを検出。コマンド文字列 or None を返す

        「クラーク、翻訳開始」(前置き) と「翻訳開始、クラーク」(後置き) の両方に対応。
        """
        # プレフィックスまたはサフィックスでキーワードを検出
        if VOICE_CMD_PREFIX.match(text):
            body = VOICE_CMD_PREFIX.sub("", text).strip()
        elif VOICE_CMD_SUFFIX.search(text):
            body = VOICE_CMD_SUFFIX.sub("", text).strip()
        else:
            return None
        # 1. 組み込みコマンド（優先）
        for pattern, command in VOICE_COMMANDS:
            if pattern.search(body):
                return command
        # 2. カスタムコマンド
        for pattern, action in self._custom_commands:
            if pattern.search(body):
                return f"custom_exec {action}"
        # 3. LLM フォールバック（API 設定済みの場合）
        if self._api_configured and body:
            return f"llm_query {body}"
        return None

    def _match_command_body(self, text: str) -> str | None:
        """プレフィックス/サフィックスなしでコマンドマッチ（Push-to-Talk 用）"""
        body = text.strip()
        if not body:
            return None
        # 1. 組み込みコマンド（優先）
        for pattern, command in VOICE_COMMANDS:
            if pattern.search(body):
                return command
        # 2. カスタムコマンド
        for pattern, action in self._custom_commands:
            if pattern.search(body):
                return f"custom_exec {action}"
        # 3. LLM フォールバック（API 設定済みの場合）
        if self._api_configured and body:
            return f"llm_query {body}"
        return None

    def _get_command_list(self) -> list[dict]:
        """_builtin_command_descs() + カスタムコマンドからコマンドリストを生成"""
        commands = list(_builtin_command_descs())
        for pattern, action in self._custom_commands:
            commands.append({
                "command": f"custom_exec {action}",
                "description": pattern.pattern,
            })
        return commands

    def _llm_match_and_execute(self, text: str):
        """LLM にコマンドマッチングを依頼し、confidence が高ければ実行する"""
        commands = self._get_command_list()
        payload = json.dumps({"text": text, "commands": commands}, ensure_ascii=False)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "shadow_clerk.llm_client", "match-command"],
                input=payload, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning("match-command 失敗: %s", result.stderr.strip())
                return
            response = json.loads(result.stdout.strip())
        except subprocess.TimeoutExpired:
            logger.warning("match-command タイムアウト")
            return
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("match-command レスポンスエラー: %s", e)
            return

        command = response.get("command", "")
        confidence = response.get("confidence", 0)

        if confidence >= 80 and command:
            logger.info("LLM コマンドマッチ: '%s' → %s (confidence=%d)", text, command, confidence)
            print(t("rec.voice_cmd_llm", text=text.strip(), command=command, confidence=confidence))
            self._execute_command(command)
        else:
            logger.info("LLM コマンドマッチ低信頼度: '%s' → %s (confidence=%d)", text, command, confidence)
            print(t("rec.voice_cmd_fail", text=text.strip(), confidence=confidence))
            if hasattr(self, "_file_watcher"):
                self._file_watcher._broadcast("alert", json.dumps(
                    {"message": t("dash.alert_cmd_fail", text=text.strip())},
                    ensure_ascii=False))

    def _auto_summarize(self, transcript_path: str):
        """会議終了時に自動で議事録を生成する"""
        basename = os.path.basename(transcript_path)
        summary_name = basename.replace("transcript-", "summary-").replace(".txt", ".md")
        summary_path = os.path.join(self._output_dir, summary_name)

        # 既存 summary があれば --existing で渡す
        cmd = [
            sys.executable, "-m", "shadow_clerk.llm_client",
            "summarize", "--mode", "full",
            "--file", transcript_path,
            "--output", summary_path,
        ]

        logger.info("自動要約開始: %s → %s", basename, summary_name)
        print(t("rec.auto_summary_start", src=basename, dst=summary_name))

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=180,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            if result.returncode == 0:
                logger.info("自動要約完了: %s", summary_path)
                print(t("rec.auto_summary_done", name=summary_name))
                if hasattr(self, "_file_watcher"):
                    self._file_watcher._broadcast("alert", json.dumps(
                        {"message": t("dash.alert_summary_done", name=summary_name)},
                        ensure_ascii=False))
            else:
                logger.warning("自動要約失敗: %s", result.stderr.strip())
                print(t("rec.auto_summary_fail", error=result.stderr.strip()[:100]))
        except subprocess.TimeoutExpired:
            logger.warning("自動要約タイムアウト")
            print(t("rec.auto_summary_timeout"))
        except Exception as e:
            logger.warning("自動要約エラー: %s", e)

    def _resolve_pynput_key(self, key_name: str):
        """config の voice_command_key 文字列を pynput のキーオブジェクトに変換"""
        if not _HAS_PYNPUT:
            return None
        key_map = {
            "menu": pynput_keyboard.Key.menu,
            "ctrl_r": pynput_keyboard.Key.ctrl_r,
            "ctrl_l": pynput_keyboard.Key.ctrl_l,
            "alt_r": pynput_keyboard.Key.alt_r,
            "alt_l": pynput_keyboard.Key.alt_l,
            "shift_r": pynput_keyboard.Key.shift_r,
            "shift_l": pynput_keyboard.Key.shift_l,
        }
        return key_map.get(key_name)

    def _key_listener_thread(self):
        """pynput でグローバルキー監視を行うスレッド"""
        target_key = self._resolve_pynput_key(self._voice_command_key)
        if target_key is None:
            logger.warning("voice_command_key '%s' を解決できません", self._voice_command_key)
            return

        logger.info("キーリスナー開始: %s", self._voice_command_key)

        def on_press(key):
            if key == target_key:
                self._command_mode = True
                logger.info("コマンドモード ON (%s pressed)", self._voice_command_key)
                print(t("rec.ptt_on", vkey=self._voice_command_key))

        def on_release(key):
            if key == target_key:
                self._command_mode = False
                self._command_mode_release_time = time.time()
                logger.info("コマンドモード OFF (%s released)", self._voice_command_key)
                print(t("rec.ptt_off", vkey=self._voice_command_key))

        with pynput_keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            self.stop_event.wait()
            listener.stop()

    def _resolve_evdev_key(self, key_name: str) -> int | None:
        """config の voice_command_key 文字列を evdev キーコードに変換"""
        if not _HAS_EVDEV:
            return None
        key_map = {
            "menu": _ecodes.KEY_COMPOSE,
            "f23": _ecodes.KEY_F23,
            "ctrl_r": _ecodes.KEY_RIGHTCTRL,
            "ctrl_l": _ecodes.KEY_LEFTCTRL,
            "alt_r": _ecodes.KEY_RIGHTALT,
            "alt_l": _ecodes.KEY_LEFTALT,
            "shift_r": _ecodes.KEY_RIGHTSHIFT,
            "shift_l": _ecodes.KEY_LEFTSHIFT,
        }
        return key_map.get(key_name)

    def _find_keyboard_devices(self) -> list:
        """evdev でキーボードデバイスを検出"""
        devices = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                if _ecodes.EV_KEY in caps and _ecodes.KEY_A in caps[_ecodes.EV_KEY]:
                    devices.append(dev)
                else:
                    dev.close()
            except (PermissionError, OSError):
                pass
        return devices

    def _key_listener_thread_evdev(self):
        """evdev でグローバルキー監視を行うスレッド (Wayland 対応)"""
        import select

        target_code = self._resolve_evdev_key(self._voice_command_key)
        if target_code is None:
            logger.warning("voice_command_key '%s' を evdev キーコードに解決できません",
                           self._voice_command_key)
            return

        keyboards = self._find_keyboard_devices()
        if not keyboards:
            logger.warning("evdev: キーボードデバイスが見つかりません。"
                           " 'sudo usermod -aG input $USER' を実行してください。")
            return

        logger.info("evdev キーリスナー開始: %s (デバイス: %s)",
                     self._voice_command_key,
                     ", ".join(d.name for d in keyboards))

        # 起動時に既に押下されているキーを検出し、初期イベントを無視するためのフラグ
        initially_held = False
        for dev in keyboards:
            try:
                if target_code in dev.active_keys():
                    initially_held = True
                    break
            except OSError:
                pass
        if initially_held:
            logger.info("evdev: %s は起動時に押下状態 — 初期イベントを無視",
                        self._voice_command_key)

        try:
            while not self.stop_event.is_set():
                r, _, _ = select.select(keyboards, [], [], 0.1)
                for dev in r:
                    try:
                        for event in dev.read():
                            if event.type == _ecodes.EV_KEY and event.code == target_code:
                                if event.value == 1:  # key down
                                    if initially_held:
                                        # 起動前から押されていたキーの down イベント → 無視
                                        continue
                                    self._command_mode = True
                                    logger.info("コマンドモード ON (%s pressed) [evdev]",
                                                self._voice_command_key)
                                    print(t("rec.ptt_on", vkey=self._voice_command_key))
                                elif event.value == 0:  # key up
                                    initially_held = False  # リリースされたのでフラグ解除
                                    self._command_mode = False
                                    self._command_mode_release_time = time.time()
                                    logger.info("コマンドモード OFF (%s released) [evdev]",
                                                self._voice_command_key)
                                    print(t("rec.ptt_off", vkey=self._voice_command_key))
                                # value == 2 (キーリピート) は無視
                    except OSError:
                        pass  # デバイス切断等
        finally:
            for dev in keyboards:
                try:
                    dev.close()
                except Exception:
                    pass

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
            print(t("rec.meeting_start", path=self.output_path))

        elif cmd == "end_meeting":
            marker = "--- 会議終了 ---\n"
            session_transcript = self.output_path
            with open(session_transcript, "a", encoding="utf-8") as f:
                f.write(marker)
            logger.info("会議終了: %s", session_transcript)
            print(t("rec.meeting_end", path=session_transcript))
            # 明示的 output 指定の場合はその値に戻す、そうでなければ現在日付のデフォルト
            if self._explicit_output:
                self.output_path = self.args.output
            else:
                self.output_path = self._get_default_output()
            try:
                os.remove(SESSION_FILE)
            except FileNotFoundError:
                pass
            # auto_summary: 会議終了時に自動で議事録を生成
            config = load_config()
            if config.get("auto_summary") and self._api_configured:
                threading.Thread(
                    target=self._auto_summarize,
                    args=(session_transcript,),
                    name="auto-summary", daemon=True,
                ).start()

        elif cmd.startswith("set_model "):
            model_size = cmd.split(None, 1)[1].strip()
            logger.info("モデル変更中: %s ...", model_size)
            print(t("rec.model_changing", model=model_size))
            self.transcriber.reload_model(model_size)
            logger.info("モデル変更完了: %s", model_size)
            print(t("rec.model_changed", model=model_size))

        elif cmd == "translate_start":
            config = load_config()
            if config.get("llm_provider") == "api":
                if self._translate_thread and self._translate_thread.is_alive():
                    logger.info("翻訳ループは既に動作中")
                else:
                    self._translate_stop_event.clear()
                    self._translate_thread = threading.Thread(
                        target=self._translate_loop, name="translate-loop", daemon=True)
                    self._translate_thread.start()
            else:
                with open(COMMAND_FILE, "w", encoding="utf-8") as f:
                    f.write("translate_start")
                logger.info("翻訳開始コマンドを .clerk_command に書き込み (claude provider)")
            print(t("rec.translate_start"))

        elif cmd == "translate_stop":
            if self._translate_thread and self._translate_thread.is_alive():
                self._translate_stop_event.set()
                self._translate_thread.join(timeout=10)
                self._translate_thread = None
                logger.info("翻訳ループ停止")
            else:
                with open(COMMAND_FILE, "w", encoding="utf-8") as f:
                    f.write("translate_stop")
                logger.info("翻訳停止コマンドを .clerk_command に書き込み")
            print(t("rec.translate_stop"))

        elif cmd.startswith("custom_exec "):
            action = cmd.split(None, 1)[1]
            logger.info("カスタムコマンド実行: %s", action)
            print(t("rec.custom_exec", action=action))
            subprocess.Popen(action, shell=True)

        elif cmd.startswith("llm_query "):
            query_text = cmd.split(None, 1)[1]
            logger.info("LLM クエリ: %s", query_text)
            threading.Thread(
                target=self._llm_query, args=(query_text,),
                name="llm-query", daemon=True,
            ).start()

        elif cmd == "mute_mic":
            self.mute_mic = True
            logger.info("マイクミュート ON")

        elif cmd == "unmute_mic":
            self.mute_mic = False
            logger.info("マイクミュート OFF")

        elif cmd == "mute_monitor":
            self.mute_monitor = True
            logger.info("スピーカーミュート ON")

        elif cmd == "unmute_monitor":
            self.mute_monitor = False
            logger.info("スピーカーミュート OFF")

        elif cmd == "ptt_on":
            self._command_mode = True
            logger.info("PTT 強制 ON (Dashboard)")

        elif cmd == "ptt_off":
            self._command_mode = False
            self._command_mode_release_time = time.time()
            logger.info("PTT 強制 OFF (Dashboard)")

        else:
            logger.warning("不明なコマンド: %s", cmd)

    def _llm_query(self, text: str):
        """LLM にクエリを投げて結果を表示・保存する（バックグラウンド実行）"""
        response_file = os.path.join(DATA_DIR, ".clerk_response")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "shadow_clerk.llm_client", "query", text],
                capture_output=True, text=True, timeout=60,
            )
            answer = result.stdout.strip()
            if result.returncode != 0:
                logger.error("LLM クエリエラー: %s", result.stderr.strip())
                return
            if answer:
                print(f"[LLM] {answer}")
                with open(response_file, "w", encoding="utf-8") as f:
                    f.write(answer)
                logger.info("LLM 回答を .clerk_response に保存")
        except subprocess.TimeoutExpired:
            logger.error("LLM クエリがタイムアウトしました")
        except Exception as e:
            logger.error("LLM クエリ失敗: %s", e)

    def _translate_loop(self):
        """翻訳ループスレッド (llm_provider: api 用)"""
        config = load_config()
        lang = config.get("translate_language", "ja")
        offset_file = os.path.join(DATA_DIR, ".translate_offset")
        logger.info("翻訳ループ開始: lang=%s", lang)

        while not self.stop_event.is_set() and not self._translate_stop_event.is_set():
            try:
                transcript = self.output_path
                try:
                    with open(offset_file, "r", encoding="utf-8") as f:
                        offset = int(f.read().strip())
                except (OSError, ValueError):
                    offset = 0

                try:
                    size = os.path.getsize(transcript)
                except OSError:
                    size = 0

                if size > offset:
                    result = subprocess.run(
                        [sys.executable, "-m", "shadow_clerk.llm_client", "--verbose",
                         "translate", lang, "--file", transcript, "--offset", str(offset)],
                        capture_output=True, text=True, timeout=120,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        basename = os.path.basename(transcript)
                        tr_name = basename.replace(".txt", f"-{lang}.txt")
                        tr_path = os.path.join(os.path.dirname(transcript), tr_name)
                        with open(tr_path, "a", encoding="utf-8") as f:
                            f.write(result.stdout)
                        with open(offset_file, "w", encoding="utf-8") as f:
                            f.write(str(size))
                        logger.info("翻訳完了: %d bytes → %s", size - offset, tr_name)
                    elif result.returncode != 0:
                        logger.error("翻訳エラー: %s", result.stderr.strip()[:200])
            except subprocess.TimeoutExpired:
                logger.error("翻訳タイムアウト")
            except Exception as e:
                logger.error("翻訳ループエラー: %s", e)

            self._translate_stop_event.wait(timeout=5.0)

        logger.info("翻訳ループ終了")

    def _command_watch_thread(self):
        """コマンドファイルをポーリングして実行するスレッド"""
        logger.info("コマンド監視スレッド開始")
        while not self.stop_event.is_set():
            try:
                if os.path.exists(COMMAND_FILE):
                    with open(COMMAND_FILE, "r", encoding="utf-8") as f:
                        cmd = f.read().strip()
                    if cmd in ("translate_start", "translate_stop"):
                        config = load_config()
                        if config.get("llm_provider") == "api":
                            os.remove(COMMAND_FILE)
                            logger.info("コマンドファイル検出: %s", cmd)
                            self._execute_command(cmd)
                        # claude provider → SKILL.md 向けにファイルを残す
                    else:
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

        # ファイル書き込み用ラベル（データフォーマット固定）
        file_labels = {"mic": "自分", "monitor": "相手"}
        # ターミナル表示用ラベル（i18n 対応）
        display_labels = {"mic": t("speaker.mic"), "monitor": t("speaker.monitor")}

        while not self.stop_event.is_set():
            try:
                segment, timestamp, source, command_mode = self.transcribe_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # ミュート中のソースはスキップ
            if source == "mic" and self.mute_mic:
                logger.debug("マイクミュート中、スキップ")
                continue
            if source == "monitor" and self.mute_monitor:
                logger.debug("スピーカーミュート中、スキップ")
                continue

            duration = len(segment) / SAMPLE_RATE
            display_speaker = display_labels.get(source, source)
            logger.info("文字起こし中 (%s, %.1f秒)...", display_speaker, duration)

            text = self.transcriber.transcribe(segment)
            if text.strip():
                # mic ソースからの音声コマンド検出
                if source == "mic":
                    if command_mode:
                        if self._api_configured:
                            # LLM ベースマッチング（別スレッドで実行）
                            threading.Thread(
                                target=self._llm_match_and_execute,
                                args=(text.strip(),),
                                name="cmd-match", daemon=True,
                            ).start()
                        else:
                            # API 未設定時は従来の正規表現マッチングにフォールバック
                            voice_cmd = self._match_command_body(text)
                            if voice_cmd:
                                logger.info("音声コマンド検出 (PTT): %s → %s", text.strip(), voice_cmd)
                                if voice_cmd.startswith("custom_exec "):
                                    logger.info("[%s] [%s] %s", timestamp, display_speaker, text.strip())
                                self._execute_command(voice_cmd)
                        continue
                    else:
                        # 従来方式: プレフィックス/サフィックス検出
                        voice_cmd = self._check_voice_command(text)
                        if voice_cmd:
                            logger.info("音声コマンド検出: %s → %s", text.strip(), voice_cmd)
                            if voice_cmd.startswith("custom_exec "):
                                logger.info("[%s] [%s] %s", timestamp, display_speaker, text.strip())
                            self._execute_command(voice_cmd)
                            continue

                # 日付変更チェック（セッション中でなく、明示的 output 指定でない場合のみ）
                if not self._explicit_output and not os.path.exists(SESSION_FILE):
                    new_path = self._get_default_output()
                    if new_path != self.output_path:
                        logger.info("日付変更検出、出力先切り替え: %s", new_path)
                        self.output_path = new_path

                text = self.word_replacer.apply(text)
                file_speaker = file_labels.get(source, source)
                file_line = f"[{timestamp}] [{file_speaker}] {text}\n"
                with open(self.output_path, "a", encoding="utf-8") as f:
                    f.write(file_line)
                    f.flush()
                display_line = f"[{timestamp}] [{display_speaker}] {text}"
                print(f"  {display_line}")
                # 中間テキストをクリア
                if hasattr(self, "_file_watcher"):
                    self._file_watcher._broadcast("interim_clear", json.dumps(
                        {"source": source}, ensure_ascii=False))
            else:
                logger.debug("空テキスト、スキップ")

        # キュー残りを処理
        while not self.transcribe_queue.empty():
            try:
                segment, timestamp, source, _ = self.transcribe_queue.get_nowait()
                file_speaker = file_labels.get(source, source)
                display_speaker = display_labels.get(source, source)
                text = self.transcriber.transcribe(segment)
                if text.strip():
                    text = self.word_replacer.apply(text)
                    file_line = f"[{timestamp}] [{file_speaker}] {text}\n"
                    with open(self.output_path, "a", encoding="utf-8") as f:
                        f.write(file_line)
                        f.flush()
                    display_line = f"[{timestamp}] [{display_speaker}] {text}"
                    print(f"  {display_line}")
            except queue.Empty:
                break

    def _interim_transcribe_thread(self):
        """中間文字起こしスレッド（interim_transcription 有効時のみモデルをロード）"""
        display_labels = {"mic": t("speaker.mic"), "monitor": t("speaker.monitor")}
        interim_transcriber = None
        interim_model_name = None
        current_seq: dict[str, int] = {}  # source ごとの最新 seq

        while not self.stop_event.is_set():
            config = load_config()
            if not config.get("interim_transcription", False):
                # 無効中はモデルをロードせず待機
                self.stop_event.wait(timeout=2.0)
                continue

            # 有効化されたらモデルを遅延ロード（モデル変更時は再ロード）
            model_name = config.get("interim_model", "tiny")
            if interim_transcriber is None or interim_model_name != model_name:
                logger.info("中間文字起こし: %s モデル読み込み中...", model_name)
                interim_transcriber = Transcriber(
                    model_size=model_name,
                    language=self.transcriber.language,
                    initial_prompt=self.transcriber.initial_prompt,
                    beam_size=1,
                    compute_type=config.get("whisper_compute_type", "int8"),
                    device=config.get("whisper_device", "cpu"),
                )
                interim_transcriber.load_model()
                interim_model_name = model_name
                logger.info("中間文字起こし: %s モデル読み込み完了", model_name)

            try:
                audio_segment, timestamp, source, seq = self.interim_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # stale チェック
            if seq < current_seq.get(source, 0):
                continue
            current_seq[source] = seq

            try:
                text = interim_transcriber.transcribe(audio_segment)
                if text.strip() and hasattr(self, "_file_watcher"):
                    speaker = display_labels.get(source, source)
                    self._file_watcher._broadcast("interim_transcript", json.dumps(
                        {"source": source, "speaker": speaker, "text": text.strip(),
                         "timestamp": timestamp}, ensure_ascii=False))
                    # リアルタイム翻訳キューに投入（最新のみ保持）
                    try:
                        self._interim_translate_queue.put_nowait(
                            (text.strip(), source, speaker, timestamp, seq))
                    except queue.Full:
                        pass
            except Exception as e:
                logger.debug("中間文字起こしエラー: %s", e)

    def _interim_translate_thread(self):
        """リアルタイム interim 翻訳スレッド"""
        current_seq: dict[str, int] = {}
        client = None
        model = None

        while not self.stop_event.is_set():
            if not _HAS_LLM_CLIENT:
                self.stop_event.wait(timeout=5.0)
                continue

            config = load_config()
            if not config.get("api_endpoint"):
                self.stop_event.wait(timeout=2.0)
                continue

            try:
                text, source, speaker, timestamp, seq = self._interim_translate_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # stale チェック
            if seq < current_seq.get(source, 0):
                continue
            current_seq[source] = seq

            # api_model 未設定時はスキップ
            if not config.get("api_model"):
                continue

            try:
                # クライアント初期化（遅延）
                if client is None:
                    llm_load_dotenv()
                    client, model = get_api_client(config)

                lang = config.get("translate_language", "ja")
                glossary = load_glossary(lang)
                system_prompt = t("llm.translate_system", lang=lang)
                if glossary:
                    system_prompt += "\n" + glossary

                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"1: {text}"},
                    ],
                    max_tokens=512,
                    temperature=0.3,
                )
                translated = resp.choices[0].message.content.strip()
                # "1: " prefix を除去
                if translated.startswith("1:"):
                    translated = translated[2:].strip()

                if translated and hasattr(self, "_file_watcher"):
                    self._file_watcher._broadcast("interim_translation", json.dumps(
                        {"source": source, "speaker": speaker, "text": text,
                         "translated": translated, "timestamp": timestamp},
                        ensure_ascii=False))
            except SystemExit:
                logger.debug("interim 翻訳: API 設定不足のためスキップ")
                client = None
            except Exception as e:
                logger.debug("interim 翻訳エラー: %s", e)
                # API エラー時はクライアントをリセットして再接続を試みる
                client = None

    def run(self):
        """メイン実行"""
        self._setup_signal_handlers()

        # LogBuffer をロガーに追加
        self._log_buffer = LogBuffer()
        self._log_buffer.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(self._log_buffer)

        logger.info("Shadow-clerk recorder 開始")
        logger.info("バックエンド: %s", self.backend_name)
        logger.info("出力先: %s", self.output_path)
        logger.info("モデル: %s", self.args.model)
        logger.info("言語: %s", self.args.language or "auto")
        print(t("rec.recording"))
        print(t("rec.output", path=self.output_path))

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
            threading.Thread(target=self._interim_transcribe_thread, name="interim-transcribe", daemon=True),
            threading.Thread(target=self._interim_translate_thread, name="interim-translate", daemon=True),
            threading.Thread(target=self._command_watch_thread, name="cmd-watch", daemon=True),
        ]

        # Push-to-Talk キーリスナー（Wayland → evdev、X11 → pynput）
        if self._voice_command_key:
            is_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland"
            if is_wayland and _HAS_EVDEV:
                threads.append(
                    threading.Thread(target=self._key_listener_thread_evdev, name="key-listener", daemon=True),
                )
            elif _HAS_PYNPUT:
                threads.append(
                    threading.Thread(target=self._key_listener_thread, name="key-listener", daemon=True),
                )
            elif _HAS_EVDEV:
                # X11 でも pynput がなければ evdev にフォールバック
                threads.append(
                    threading.Thread(target=self._key_listener_thread_evdev, name="key-listener", daemon=True),
                )
            else:
                logger.warning("Push-to-Talk に必要なパッケージがありません。"
                               " Wayland: 'uv pip install evdev' + input グループ追加、"
                               " X11: 'uv pip install pynput'")

        # ダッシュボード
        if getattr(self.args, "dashboard", True):
            self._file_watcher = FileWatcher(self, self._log_buffer)
            threads.append(self._file_watcher)

            DashboardHandler.recorder = self
            DashboardHandler.log_buffer = self._log_buffer
            DashboardHandler.file_watcher = self._file_watcher

            port = getattr(self.args, "dashboard_port", 8765)
            self._dashboard_server = ThreadingHTTPServer(("", port), DashboardHandler)
            threads.append(threading.Thread(
                target=self._dashboard_server.serve_forever,
                name="dashboard", daemon=True))
            logger.info("ダッシュボード: http://localhost:%d", port)

        for th in threads:
            th.start()

        # メインスレッドで待機
        try:
            while not self.stop_event.is_set():
                self.stop_event.wait(timeout=0.5)
        except KeyboardInterrupt:
            self.stop_event.set()

        logger.info("スレッド終了待機中...")
        for th in threads:
            th.join(timeout=5.0)

        logger.info("Shadow-clerk recorder 終了")


# --- Web ダッシュボード ---

class LogBuffer(logging.Handler):
    """ログ用の循環バッファ（メモリ内でログ行を保持）"""

    def __init__(self, maxlen=500):
        super().__init__()
        self._buf = collections.deque(maxlen=maxlen)
        self._seq = 0
        self._buf_lock = threading.Lock()

    def emit(self, record):
        line = self.format(record)
        with self._buf_lock:
            self._buf.append((self._seq, line))
            self._seq += 1

    @property
    def counter(self):
        with self._buf_lock:
            return self._seq

    def get_lines(self, n=100):
        with self._buf_lock:
            items = list(self._buf)
        return [line for _, line in items[-n:]]

    def get_new_lines(self, since):
        with self._buf_lock:
            items = list(self._buf)
            seq = self._seq
        return [line for s, line in items if s >= since], seq


class FileWatcher(threading.Thread):
    """ファイル監視 + SSE ブロードキャスト"""

    def __init__(self, recorder, log_buffer):
        super().__init__(name="file-watcher", daemon=True)
        self._recorder = recorder
        self._log_buffer = log_buffer
        self._clients = []
        self._clients_lock = threading.Lock()
        self._file_offsets = {}
        self._mtimes = {}
        self._log_counter = 0
        self._last_status = None
        self._last_ptt = None

    def add_client(self):
        q = queue.Queue()
        running = not self._recorder.stop_event.is_set()
        q.put(("recorder_status", json.dumps({"running": running})))
        with self._clients_lock:
            self._clients.append(q)
        return q

    def remove_client(self, q):
        with self._clients_lock:
            try:
                self._clients.remove(q)
            except ValueError:
                pass

    def _broadcast(self, event, data):
        with self._clients_lock:
            for q in self._clients:
                try:
                    q.put_nowait((event, data))
                except Exception:
                    pass

    def _get_size(self, path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _get_mtime(self, path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0

    def _read_diff(self, path, old_size):
        try:
            new_size = os.path.getsize(path)
            if new_size <= old_size:
                return None, new_size
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(old_size)
                diff = f.read()
            return diff, new_size
        except OSError:
            return None, 0

    def run(self):
        t_path = self._recorder.output_path
        self._file_offsets[("transcript", t_path)] = self._get_size(t_path)
        self._log_counter = self._log_buffer.counter

        while not self._recorder.stop_event.is_set():
            try:
                self._poll()
            except Exception:
                pass
            self._recorder.stop_event.wait(timeout=1.0)

    def _poll(self):
        # Transcript
        t_path = self._recorder.output_path
        key = ("transcript", t_path)
        if key not in self._file_offsets:
            self._file_offsets[key] = self._get_size(t_path)
        diff, new_size = self._read_diff(t_path, self._file_offsets.get(key, 0))
        if diff:
            self._file_offsets[key] = new_size
            self._broadcast("transcript", json.dumps(
                {"file": os.path.basename(t_path), "diff": diff}, ensure_ascii=False))

        # Translation
        config = load_config()
        lang = config.get("translate_language", "ja")
        tr_name = os.path.basename(t_path).replace(".txt", f"-{lang}.txt")
        tr_path = os.path.join(os.path.dirname(t_path), tr_name)
        key = ("translation", tr_path)
        if key not in self._file_offsets:
            self._file_offsets[key] = self._get_size(tr_path)
        diff, new_size = self._read_diff(tr_path, self._file_offsets.get(key, 0))
        if diff:
            self._file_offsets[key] = new_size
            self._broadcast("translation", json.dumps(
                {"file": tr_name, "diff": diff}, ensure_ascii=False))

        # Metadata files (mtime-based)
        for evt, path in [
            ("session", SESSION_FILE),
            ("command", COMMAND_FILE),
            ("response", os.path.join(DATA_DIR, ".clerk_response")),
            ("config", CONFIG_FILE),
        ]:
            mtime = self._get_mtime(path)
            if mtime != self._mtimes.get(evt, 0):
                self._mtimes[evt] = mtime
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                except OSError:
                    content = ""
                self._broadcast(evt, json.dumps(
                    {"content": content}, ensure_ascii=False))

        # Recorder status
        running = not self._recorder.stop_event.is_set()
        if running != self._last_status:
            self._last_status = running
            self._broadcast("recorder_status", json.dumps({"running": running}))

        # PTT status
        ptt = self._recorder._command_mode
        if ptt != self._last_ptt:
            self._last_ptt = ptt
            self._broadcast("ptt", json.dumps({"active": ptt}))

        # Logs
        new_lines, self._log_counter = self._log_buffer.get_new_lines(
            self._log_counter)
        for line in new_lines:
            self._broadcast("log", json.dumps(
                {"line": line}, ensure_ascii=False))


class DashboardHandler(BaseHTTPRequestHandler):
    """ダッシュボード HTTP ハンドラ"""

    recorder = None
    log_buffer = None
    file_watcher = None

    def log_message(self, format, *args):
        pass  # suppress default request logging

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._serve_html()
        elif path == "/api/events":
            self._serve_sse()
        elif path == "/api/status":
            self._serve_status()
        elif path == "/api/files":
            self._serve_files()
        elif path == "/api/transcript":
            self._serve_transcript()
        elif path == "/api/translation":
            self._serve_translation()
        elif path == "/api/logs":
            self._serve_logs()
        elif path == "/api/config":
            self._serve_config()
        elif path == "/api/glossary":
            self._serve_glossary()
        elif path == "/api/summary":
            self._serve_summary()
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/command":
            self._handle_command()
        elif path == "/api/config":
            self._save_config()
        elif path == "/api/glossary":
            self._save_glossary()
        elif path == "/api/summary":
            self._generate_summary()
        else:
            self.send_error(404)

    def _send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        from shadow_clerk import i18n as _i18n
        _i18n.init()  # re-read config for ui_language changes
        html = _HTML_TEMPLATE
        html = re.sub(r'\{\{i18n:([^}]+)\}\}', lambda m: t(m.group(1)), html)
        html = html.replace("/*I18N_JSON*/", f"const I18N={json.dumps(t_all(), ensure_ascii=False)};")
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        client_q = self.file_watcher.add_client()
        try:
            while not self.recorder.stop_event.is_set():
                try:
                    event, data = client_q.get(timeout=15)
                    self.wfile.write(
                        f"event: {event}\ndata: {data}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.file_watcher.remove_client(client_q)

    def _serve_status(self):
        session = ""
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                session = f.read().strip()
        except OSError:
            pass
        translating = (self.recorder._translate_thread is not None
                       and self.recorder._translate_thread.is_alive())
        self._send_json({
            "running": not self.recorder.stop_event.is_set(),
            "backend": self.recorder.backend_name,
            "model": self.recorder.transcriber.model_size,
            "language": self.recorder.transcriber.language or "auto",
            "output_path": self.recorder.output_path,
            "session": session or None,
            "translating": translating,
            "mute_mic": self.recorder.mute_mic,
            "mute_monitor": self.recorder.mute_monitor,
            "ptt": self.recorder._command_mode,
        })

    def _serve_files(self):
        output_dir = self.recorder._output_dir
        files = []
        try:
            for f in sorted(os.listdir(output_dir), reverse=True):
                if (f.startswith("transcript-") and f.endswith(".txt")
                        and not re.search(r"-[a-z]{2}\.txt$", f)):
                    files.append(f)
        except OSError:
            pass
        self._send_json({
            "files": files,
            "active": os.path.basename(self.recorder.output_path),
        })

    def _serve_transcript(self):
        params = parse_qs(urlparse(self.path).query)
        file_param = params.get("file", [None])[0]
        if file_param:
            file_param = os.path.basename(file_param)
            filepath = os.path.join(self.recorder._output_dir, file_param)
        else:
            filepath = self.recorder.output_path
        lines = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            lines = [l.rstrip("\n") for l in all_lines[-50:]]
        except OSError:
            pass
        self._send_json({
            "file": os.path.basename(filepath), "lines": lines})

    def _serve_translation(self):
        params = parse_qs(urlparse(self.path).query)
        file_param = params.get("file", [None])[0]
        if file_param:
            file_param = os.path.basename(file_param)
            filepath = os.path.join(self.recorder._output_dir, file_param)
        else:
            config = load_config()
            lang = config.get("translate_language", "ja")
            basename = os.path.basename(self.recorder.output_path)
            tr_name = basename.replace(".txt", f"-{lang}.txt")
            filepath = os.path.join(self.recorder._output_dir, tr_name)
        lines = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            lines = [l.rstrip("\n") for l in all_lines[-50:]]
        except OSError:
            pass
        self._send_json({
            "file": os.path.basename(filepath), "lines": lines})

    def _serve_logs(self):
        self._send_json({"lines": self.log_buffer.get_lines(100)})

    def _handle_command(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            cmd = data.get("command", "").strip()
        except (json.JSONDecodeError, ValueError):
            self.send_error(400)
            return
        if not cmd:
            self.send_error(400)
            return
        with open(COMMAND_FILE, "w", encoding="utf-8") as f:
            f.write(cmd)
        logger.info("ダッシュボードからコマンド: %s", cmd)
        self._send_json({"status": "ok", "command": cmd})

    def _get_summary_path(self, transcript_path: str = None) -> str:
        """transcript パスから summary パスを導出する"""
        if transcript_path is None:
            transcript_path = self.recorder.output_path
        basename = os.path.basename(transcript_path)
        summary_name = basename.replace("transcript-", "summary-").replace(".txt", ".md")
        return os.path.join(self.recorder._output_dir, summary_name)

    def _serve_summary(self):
        """GET /api/summary — summary ファイルの内容を返す"""
        params = parse_qs(urlparse(self.path).query)
        file_param = params.get("file", [None])[0]
        if file_param:
            # transcript ファイル名から summary パスを導出
            file_param = os.path.basename(file_param)
            summary_name = file_param.replace("transcript-", "summary-").replace(".txt", ".md")
            summary_path = os.path.join(self.recorder._output_dir, summary_name)
        else:
            summary_path = self._get_summary_path()
        summary_name = os.path.basename(summary_path)
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._send_json({"file": summary_name, "content": content})
        except FileNotFoundError:
            self._send_json({"file": summary_name, "content": ""})

    def _generate_summary(self):
        """POST /api/summary — 要約生成をトリガーする"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            data = {}
        file_param = data.get("file")
        if file_param:
            transcript_path = os.path.join(self.recorder._output_dir, os.path.basename(file_param))
        else:
            transcript_path = self.recorder.output_path
        if not os.path.exists(transcript_path):
            self._send_json({"status": "error", "message": t("dash.transcript_not_found")})
            return
        self._send_json({"status": "ok", "message": t("dash.summary_generation_started")})
        threading.Thread(
            target=self.recorder._auto_summarize,
            args=(transcript_path,),
            name="dashboard-summary", daemon=True,
        ).start()

    def _serve_config(self):
        self._send_json(load_config())

    def _save_config(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self.send_error(400)
            return
        # Merge with existing config to preserve unknown keys
        config = load_config()
        for key in list(DEFAULT_CONFIG.keys()):
            if key in data:
                config[key] = data[key]
        # whisper_beam_size は数値に変換
        if "whisper_beam_size" in config:
            try:
                config["whisper_beam_size"] = int(config["whisper_beam_size"])
            except (TypeError, ValueError):
                config["whisper_beam_size"] = DEFAULT_CONFIG["whisper_beam_size"]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        logger.info("ダッシュボードから設定変更")
        self._send_json(config)

    def _serve_glossary(self):
        content = ""
        try:
            with open(GLOSSARY_FILE, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            pass
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _save_glossary(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
        except Exception:
            self.send_error(400)
            return
        with open(GLOSSARY_FILE, "w", encoding="utf-8") as f:
            f.write(body)
        logger.info("ダッシュボードから用語集を保存")
        self._send_json({"status": "ok"})


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shadow-clerk Dashboard</title>
<style>
:root {
  --bg: #0d1117;
  --panel: #161b22;
  --header: #010409;
  --border: #30363d;
  --text: #c9d1d9;
  --muted: #8b949e;
  --accent: #58a6ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --purple: #d2a8ff;
  --self: #79c0ff;
  --other: #ffa657;
  --btn: #21262d;
  --btn-h: #30363d;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  height: 100vh; display: flex; flex-direction: column; overflow: hidden;
}
header {
  background: var(--header); border-bottom: 1px solid var(--border);
  padding: 8px 16px; display: flex; align-items: center; gap: 12px;
  flex-shrink: 0; flex-wrap: wrap;
}
select, input[type=text] {
  background: var(--btn); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 5px 8px; font-size: 13px; outline: none;
}
select:focus, input:focus { border-color: var(--accent); }
button {
  background: var(--btn); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 5px 12px; font-size: 13px; cursor: pointer;
}
button:hover { background: var(--btn-h); }
.g { display:flex; gap:6px; align-items:center; }
.pri { background:#238636; border-color:#2ea043; }
.pri:hover { background:#2ea043; }
.dan { background:#da3633; border-color:#f85149; color:#fff; }
.dan:hover { background:#b62324; }
main {
  flex:1; display:flex; gap:1px; background:var(--border); min-height:0;
}
.panel {
  flex:1; background:var(--panel); display:flex; flex-direction:column; min-width:0;
}
.ph {
  padding:8px 12px; border-bottom:1px solid var(--border); font-size:13px;
  font-weight:600; color:var(--muted); flex-shrink:0; display:flex;
  justify-content:space-between; align-items:center;
}
.pc {
  flex:1; overflow-y:auto; padding:8px 12px;
  font-family: 'SF Mono','Monaco','Menlo','Consolas',monospace;
  font-size: 12px; line-height: 1.6;
}
.ln { margin-bottom:2px; word-break:break-word; }
.ts { color:var(--muted); }
.sp-s { color:var(--self); font-weight:600; }
.sp-o { color:var(--other); font-weight:600; }
.mk { color:var(--purple); font-weight:600; }
#logp {
  height:180px; flex-shrink:0; background:var(--panel);
  border-top:1px solid var(--border); display:flex; flex-direction:column;
}
#logc {
  flex:1; overflow-y:auto; padding:4px 12px;
  font-family: 'SF Mono','Monaco','Menlo','Consolas',monospace;
  font-size:11px; line-height:1.5; color:var(--muted);
}
.ll { white-space:pre-wrap; word-break:break-word; }
.ll.e { color:var(--red); }
.ll.w { color:var(--yellow); }
.interim {
  color: var(--muted); font-style: italic; opacity: 0.7;
  border-left: 2px solid var(--yellow); padding-left: 8px; margin-top: 4px;
}
#resp {
  display:none; background:var(--panel); border-bottom:1px solid var(--border);
  padding:8px 12px; font-size:13px; flex-shrink:0; max-height:120px; overflow-y:auto;
}
#resp.show { display:block; }
#resp .rh {
  display:flex; justify-content:space-between; align-items:center;
  color:var(--accent); font-weight:600; margin-bottom:4px;
}
#resp .rb {
  white-space:pre-wrap; word-break:break-word; color:var(--text);
  font-family:'SF Mono','Monaco','Menlo','Consolas',monospace; font-size:12px;
}
.toggle { font-size:12px; opacity:.7; cursor:pointer; padding:2px 6px; border:1px solid var(--border); border-radius:4px; background:transparent; color:var(--muted); }
.toggle:hover { opacity:1; }
.toggle.off { opacity:.4; text-decoration:line-through; }
.panel.hidden { display:none; }
#logp.collapsed #logc { display:none; }
#logp.collapsed { height:auto; }
.modal-overlay {
  display:none; position:fixed; inset:0; background:rgba(0,0,0,.6);
  z-index:100; justify-content:center; align-items:center;
}
.modal-overlay.open { display:flex; }
.modal {
  background:var(--panel); border:1px solid var(--border); border-radius:12px;
  width:520px; max-height:80vh; display:flex; flex-direction:column;
}
.modal-head {
  padding:12px 16px; border-bottom:1px solid var(--border);
  font-weight:600; display:flex; justify-content:space-between; align-items:center;
}
.modal-body {
  padding:16px; overflow-y:auto; flex:1;
  display:grid; grid-template-columns:140px 1fr; gap:8px 12px; align-items:center;
  font-size:13px;
}
.modal-body label { color:var(--muted); text-align:right; }
.modal-body input, .modal-body select, .modal-body textarea {
  background:var(--btn); color:var(--text); border:1px solid var(--border);
  border-radius:6px; padding:5px 8px; font-size:13px; width:100%; outline:none;
  font-family:inherit;
}
.modal-body input:focus, .modal-body select:focus, .modal-body textarea:focus {
  border-color:var(--accent);
}
.modal-body textarea { resize:vertical; min-height:60px; font-family:monospace; font-size:12px; }
#glossaryTable th, #glossaryTable td {
  border:1px solid var(--border); padding:4px 6px;
}
#glossaryTable th {
  background:var(--bg); color:var(--muted); font-weight:600; font-size:12px;
  text-align:left; position:sticky; top:0; padding:2px 4px;
}
#glossaryTable th select { width:100%; }
#glossaryTable td { padding:0; }
#glossaryTable td input {
  border:none; border-radius:0; width:100%; padding:5px 6px; font-size:13px;
  background:transparent; color:var(--text); outline:none;
}
#glossaryTable td input:focus { background:rgba(100,100,255,0.08); }
#glossaryTable td.gl-del { width:30px; text-align:center; cursor:pointer; color:var(--muted); }
#glossaryTable td.gl-del:hover { color:var(--red,#e55); }
#customCmdTable th, #customCmdTable td {
  border:1px solid var(--border); padding:4px 6px;
}
#customCmdTable th {
  background:var(--bg); color:var(--muted); font-weight:600; font-size:12px;
  text-align:left; position:sticky; top:0; padding:4px 6px;
}
#customCmdTable td { padding:0; }
#customCmdTable td input {
  border:none; border-radius:0; width:100%; padding:5px 6px; font-size:13px;
  background:transparent; color:var(--text); outline:none;
}
#customCmdTable td input:focus { background:rgba(100,100,255,0.08); }
#customCmdTable td.gl-del { width:30px; text-align:center; cursor:pointer; color:var(--muted); }
#customCmdTable td.gl-del:hover { color:var(--red,#e55); }
.modal-foot {
  padding:12px 16px; border-top:1px solid var(--border);
  display:flex; justify-content:flex-end; gap:8px;
}
.modal-foot .saved { color:var(--green); font-size:13px; margin-right:auto; display:none; }
</style>
</head>
<body>
<header>
  <label for="langSel" style="font-size:12px;color:#aaa;margin-right:2px">{{i18n:dash.detect_language}}</label><select id="langSel" onchange="onLangChange(this.value)">
    <option value="auto">auto</option>
    <option value="ja">ja</option>
    <option value="en">en</option>
    <option value="zh">zh</option>
    <option value="ko">ko</option>
    <option value="fr">fr</option>
    <option value="de">de</option>
    <option value="es">es</option>
    <option value="pt">pt</option>
    <option value="ru">ru</option>
  </select>
  <select id="fsel" onchange="onSel()"><option value="">...</option></select>
  <div class="g">
    <button class="pri" id="btnMeeting" onclick="togMeeting()">{{i18n:dash.meeting_toggle_start}}</button>
    <button id="btnTranslate" onclick="togTranslate()">{{i18n:dash.translate_start}}</button>
    <button onclick="genSummary()">{{i18n:dash.summary}}</button>
    <button onclick="viewSummary()">{{i18n:dash.view_summary}}</button>
  </div>
  <div class="g" style="margin-left:auto">
    <button class="toggle" id="togTR" onclick="cyclePanel()">T|R</button>
    <button onclick="openGlossary()">{{i18n:dash.glossary}}</button>
    <button class="toggle" id="btnPTT" onclick="togPTT()" style="min-width:auto;padding:2px 6px;font-size:11px">PTT</button>
    <button onclick="openCustomCmds()">{{i18n:dash.custom_commands}}</button>
    <button onclick="openCfg()" title="{{i18n:dash.settings}}">⚙</button>
    <button onclick="openHelp()" title="{{i18n:dash.help}}">❓</button>
  </div>
</header>
<div id="resp"><div class="rh"><span>LLM Response</span><button class="toggle" onclick="hideResp()">&times;</button></div><div class="rb" id="respBody"></div></div>
<main>
  <div class="panel" id="pnlT">
    <div class="ph"><span>Transcript</span><span style="display:flex;gap:4px;align-items:center"><button class="toggle" id="btnMuteMic" onclick="togMute('mic')" title="{{i18n:dash.mute_mic}}">🎤</button><button class="toggle" id="btnMuteMonitor" onclick="togMute('monitor')" title="{{i18n:dash.mute_monitor}}">🔊</button><span id="tf" style="font-weight:normal"></span></span></div>
    <div class="pc" id="tp"></div>
  </div>
  <div class="panel" id="pnlR">
    <div class="ph"><span>Translation</span><span id="rf" style="font-weight:normal"></span></div>
    <div class="pc" id="rp"></div>
  </div>
</main>
<div id="interim-area" style="display:none; border-top:1px solid var(--border); padding:4px 12px; flex-shrink:0;">
  <div id="interim-monitor" class="interim"></div>
  <div id="itp" class="interim"></div>
</div>
<div id="logp">
  <div class="ph" style="cursor:pointer" onclick="togLogs()"><span>Logs</span><span id="logArrow">▼</span></div>
  <div id="logc"></div>
</div>
<div class="modal-overlay" id="cfgModal" onclick="if(event.target===this)closeCfg()">
  <div class="modal">
    <div class="modal-head"><span>{{i18n:dash.settings_title}}</span><button onclick="closeCfg()">&times;</button></div>
    <div class="modal-body" id="cfgBody"></div>
    <div class="modal-foot">
      <span class="saved" id="cfgSaved">{{i18n:dash.saved}}</span>
      <button onclick="closeCfg()">{{i18n:dash.cancel}}</button>
      <button class="pri" onclick="saveCfg()">{{i18n:dash.save}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="glossaryModal" onclick="if(event.target===this)closeGlossary()">
  <div class="modal" style="max-width:700px;">
    <div class="modal-head"><span>{{i18n:dash.glossary_title}}</span><button onclick="closeGlossary()">&times;</button></div>
    <div class="modal-body" style="display:block;max-height:60vh;overflow-y:auto;">
      <table id="glossaryTable" style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr id="glossaryHead"></tr></thead>
        <tbody id="glossaryBody"></tbody>
      </table>
      <div style="margin-top:8px;">
        <button onclick="glossaryAddRow()" style="font-size:12px;">{{i18n:dash.add_row}}</button>
      </div>
    </div>
    <div class="modal-foot">
      <span class="saved" id="glossarySaved">{{i18n:dash.saved}}</span>
      <button onclick="closeGlossary()">{{i18n:dash.cancel}}</button>
      <button class="pri" onclick="saveGlossary()">{{i18n:dash.save}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="summaryModal" onclick="if(event.target===this)closeSummary()">
  <div class="modal" style="max-width:700px;">
    <div class="modal-head"><span id="summaryTitle">{{i18n:dash.summary_title}}</span><button onclick="closeSummary()">&times;</button></div>
    <div class="modal-body" style="display:block;max-height:60vh;overflow-y:auto;">
      <div id="summaryContent" style="white-space:pre-wrap;font-size:13px;line-height:1.6;"></div>
    </div>
    <div class="modal-foot">
      <button onclick="closeSummary()">{{i18n:dash.close}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="helpModal" onclick="if(event.target===this)closeHelp()">
  <div class="modal" style="max-width:600px;">
    <div class="modal-head"><span>{{i18n:dash.help_title}}</span><button onclick="closeHelp()">&times;</button></div>
    <div class="modal-body" style="display:block;max-height:70vh;overflow-y:auto;font-size:13px;line-height:1.7;">
      <div id="helpContent" style="white-space:pre-wrap;"></div>
    </div>
    <div class="modal-foot">
      <button onclick="closeHelp()">{{i18n:dash.close}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="customCmdModal" onclick="if(event.target===this)closeCustomCmds()">
  <div class="modal" style="max-width:700px;">
    <div class="modal-head"><span>{{i18n:dash.custom_commands_title}}</span><button onclick="closeCustomCmds()">&times;</button></div>
    <div class="modal-body" style="display:block;max-height:60vh;overflow-y:auto;">
      <table id="customCmdTable" style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr><th>{{i18n:dash.custom_cmd_pattern}}</th><th>{{i18n:dash.custom_cmd_action}}</th><th style="width:30px"></th></tr></thead>
        <tbody id="customCmdBody"></tbody>
      </table>
      <div style="margin-top:8px;">
        <button onclick="customCmdAddRow()" style="font-size:12px;">{{i18n:dash.add_row}}</button>
      </div>
      <div style="margin-top:12px;font-size:12px;color:var(--muted);line-height:1.5;">{{i18n:dash.custom_cmd_hint}}</div>
    </div>
    <div class="modal-foot">
      <span class="saved" id="customCmdSaved">{{i18n:dash.saved}}</span>
      <button onclick="closeCustomCmds()">{{i18n:dash.cancel}}</button>
      <button class="pri" onclick="saveCustomCmds()">{{i18n:dash.save}}</button>
    </div>
  </div>
</div>
<script>
/*I18N_JSON*/
let curFile='', activeFile='';
let meetingActive=false, translating=false, muteMic=false, muteMonitor=false, pttActive=false;
let panelMode=0; // 0=T|R, 1=T, 2=R
const as={tp:true,rp:true,logc:true};
['tp','rp','logc'].forEach(id=>{
  document.getElementById(id).addEventListener('scroll',function(){
    as[id]=this.scrollTop+this.clientHeight>=this.scrollHeight-30;
  });
});
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmtLine(t){
  if(/^---\\s.*\\s---$/.test(t)) return '<div class="ln"><span class="mk">'+esc(t)+'</span></div>';
  const m=t.match(/^\\[(\\d{4}-\\d{2}-\\d{2}\\s\\d{2}:\\d{2}:\\d{2})\\]\\s\\[([^\\]]+)\\]\\s(.*)$/);
  if(m){const sp=m[2],mic=I18N['speaker.mic']||'自分';const c=(sp===mic||sp==='自分')?'sp-s':'sp-o';
    const dl=sp===mic?mic:sp==='自分'?mic:(sp===(I18N['speaker.monitor']||'相手')||sp==='相手')?(I18N['speaker.monitor']||'相手'):sp;
    return '<div class="ln"><span class="ts">['+esc(m[1])+']</span> <span class="'+c+'">['+esc(dl)+']</span> '+esc(m[3])+'</div>';}
  return '<div class="ln">'+esc(t)+'</div>';
}
function addLines(id,text,fmt){
  const el=document.getElementById(id);
  text.split('\\n').forEach(l=>{if(l.trim())el.insertAdjacentHTML('beforeend',fmt(l));});
  if(as[id])el.scrollTop=el.scrollHeight;
}
/* --- Meeting toggle --- */
function updateMeetingBtn(session){
  meetingActive=!!session;
  const btn=document.getElementById('btnMeeting');
  if(meetingActive){
    btn.textContent='\\u25A0 '+I18N['dash.meeting_toggle_end'];
    btn.className='dan';
  }else{
    btn.textContent='\\u25B6 '+I18N['dash.meeting_toggle_start'];
    btn.className='pri';
  }
}
function togMeeting(){cmd(meetingActive?'end_meeting':'start_meeting');}
/* --- Translation toggle --- */
function updateTranslateBtn(active){
  translating=active;
  const btn=document.getElementById('btnTranslate');
  if(translating){
    btn.textContent='\\u25A0 '+I18N['dash.translate_stop'];
    btn.className='dan';
  }else{
    btn.textContent='\\u25B6 '+I18N['dash.translate_start'];
    btn.className='pri';
  }
}
async function togTranslate(){
  if(translating){cmd('translate_stop');updateTranslateBtn(false);return;}
  try{const d=await(await fetch('/api/config')).json();
    if(d.llm_provider!=='api'){alert(I18N['dash.translate_claude_hint']);return;}
  }catch(e){}
  cmd('translate_start');updateTranslateBtn(true);
}
/* --- Mute toggles --- */
function updateMuteBtn(type,muted){
  const btn=document.getElementById(type==='mic'?'btnMuteMic':'btnMuteMonitor');
  if(muted){btn.classList.add('off');btn.title=I18N[type==='mic'?'dash.unmute_mic':'dash.unmute_monitor'];}
  else{btn.classList.remove('off');btn.title=I18N[type==='mic'?'dash.mute_mic':'dash.mute_monitor'];}
}
function togMute(type){
  if(type==='mic'){muteMic=!muteMic;cmd(muteMic?'mute_mic':'unmute_mic');updateMuteBtn('mic',muteMic);}
  else{muteMonitor=!muteMonitor;cmd(muteMonitor?'mute_monitor':'unmute_monitor');updateMuteBtn('monitor',muteMonitor);}
}
/* --- PTT toggle --- */
function updatePTT(active){
  pttActive=active;
  const btn=document.getElementById('btnPTT');
  if(active){btn.style.background='var(--red)';btn.style.color='#fff';}
  else{btn.style.background='';btn.style.color='';}
}
function togPTT(){
  pttActive=!pttActive;
  cmd(pttActive?'ptt_on':'ptt_off');
  updatePTT(pttActive);
}
/* --- Panel cycling (T|R -> T -> R) --- */
function cyclePanel(){
  panelMode=(panelMode+1)%3;
  const t=document.getElementById('pnlT'),r=document.getElementById('pnlR'),btn=document.getElementById('togTR');
  if(panelMode===0){t.classList.remove('hidden');r.classList.remove('hidden');btn.textContent='T|R';}
  else if(panelMode===1){t.classList.remove('hidden');r.classList.add('hidden');btn.textContent='T';}
  else{t.classList.add('hidden');r.classList.remove('hidden');btn.textContent='R';}
}
/* --- Logs toggle --- */
function togLogs(){
  const lp=document.getElementById('logp'),arr=document.getElementById('logArrow');
  lp.classList.toggle('collapsed');
  arr.textContent=lp.classList.contains('collapsed')?'▲':'▼';
}
/* --- Status fetch --- */
async function fetchStatus(){
  try{const d=await(await fetch('/api/status')).json();
    const s=document.getElementById('langSel');if(s&&d.language)s.value=d.language;
    updateMeetingBtn(d.session);
    updateTranslateBtn(d.translating);
    muteMic=d.mute_mic;muteMonitor=d.mute_monitor;
    updateMuteBtn('mic',muteMic);updateMuteBtn('monitor',muteMonitor);
    if(d.ptt!==undefined)updatePTT(d.ptt);
  }catch(e){}
}
const es=new EventSource('/api/events');
es.addEventListener('transcript',e=>{
  const d=JSON.parse(e.data);
  if(!curFile||curFile===d.file){addLines('tp',d.diff,fmtLine);document.getElementById('tf').textContent=d.file;}
});
es.addEventListener('translation',e=>{
  const d=JSON.parse(e.data);addLines('rp',d.diff,fmtLine);document.getElementById('rf').textContent=d.file;
});
es.addEventListener('log',e=>{
  const d=JSON.parse(e.data);const el=document.getElementById('logc');
  const c=d.line.includes('ERROR')?'e':d.line.includes('WARNING')?'w':'';
  el.insertAdjacentHTML('beforeend','<div class="ll '+c+'">'+esc(d.line)+'</div>');
  if(as.logc)el.scrollTop=el.scrollHeight;
});
es.addEventListener('session',e=>{
  try{const d=JSON.parse(e.data);updateMeetingBtn(d.content||null);}catch(ex){}
  loadFiles();
});
es.addEventListener('ptt',e=>{
  try{const d=JSON.parse(e.data);updatePTT(d.active);}catch(ex){}
});
es.addEventListener('interim_transcript',e=>{
  const d=JSON.parse(e.data);
  const el=document.getElementById('interim-monitor');
  if(el){el.innerHTML='<span class="sp-o">['+esc(d.speaker)+']</span> '+esc(d.text);}
  document.getElementById('interim-area').style.display='block';
});
es.addEventListener('interim_translation',e=>{
  const d=JSON.parse(e.data);
  const el=document.getElementById('itp');
  if(el){el.innerHTML='<span class="sp-o">['+esc(d.speaker)+']</span> '+esc(d.translated);}
  document.getElementById('interim-area').style.display='block';
});
es.addEventListener('interim_clear',e=>{
  const el=document.getElementById('interim-monitor');
  if(el)el.innerHTML='';
  document.getElementById('interim-area').style.display='none';
  const itp=document.getElementById('itp');
  if(itp)itp.innerHTML='';
});
async function loadFiles(){
  try{const r=await fetch('/api/files'),d=await r.json(),s=document.getElementById('fsel'),p=s.value;
  s.innerHTML='';activeFile=d.active||'';
  d.files.forEach(f=>{const o=document.createElement('option');o.value=f;
    o.textContent=f+(f===d.active?' ★':'');s.appendChild(o);});
  s.value=(p&&d.files.includes(p))?p:(d.active||'');curFile=s.value;}catch(e){}
}
async function loadT(file){
  try{const u=file?'/api/transcript?file='+encodeURIComponent(file):'/api/transcript';
  const d=await(await fetch(u)).json(),el=document.getElementById('tp');el.innerHTML='';
  d.lines.forEach(l=>el.insertAdjacentHTML('beforeend',fmtLine(l)));
  document.getElementById('tf').textContent=d.file;el.scrollTop=el.scrollHeight;}catch(e){}
}
async function loadR(file){
  try{const u=file?'/api/translation?file='+encodeURIComponent(file):'/api/translation';
  const d=await(await fetch(u)).json(),el=document.getElementById('rp');el.innerHTML='';
  d.lines.forEach(l=>el.insertAdjacentHTML('beforeend',fmtLine(l)));
  document.getElementById('rf').textContent=d.file;el.scrollTop=el.scrollHeight;}catch(e){}
}
async function loadLogs(){
  try{const d=await(await fetch('/api/logs')).json(),el=document.getElementById('logc');
  d.lines.forEach(l=>{const c=l.includes('ERROR')?'e':l.includes('WARNING')?'w':'';
    el.insertAdjacentHTML('beforeend','<div class="ll '+c+'">'+esc(l)+'</div>');});
  el.scrollTop=el.scrollHeight;}catch(e){}
}
function onSel(){curFile=document.getElementById('fsel').value;loadT(curFile);loadR(curFile);}
async function cmd(c){try{await fetch('/api/command',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({command:c})});}catch(e){}}
function onLangChange(l){cmd(l==='auto'?'unset_language':'set_language '+l);}
fetchStatus();
es.addEventListener('response',e=>{
  const d=JSON.parse(e.data);if(d.content){
    document.getElementById('respBody').textContent=d.content;
    document.getElementById('resp').classList.add('show');}
});
es.addEventListener('alert',e=>{
  const d=JSON.parse(e.data);if(d.message){alert(d.message);}
});
function hideResp(){document.getElementById('resp').classList.remove('show');}
loadFiles();loadT('');loadR('');loadLogs();setInterval(loadFiles,10000);
const LANG_OPTS=['ja','en','zh','ko','fr','de','es','pt','ru'];
const CFG_FIELDS=[
  {key:'ui_language',label:I18N['cfg.ui_language'],type:'select',opts:['ja','en']},
  {key:'translate_language',label:I18N['cfg.translate_language'],type:'select',opts:LANG_OPTS},
  {key:'auto_translate',label:I18N['cfg.auto_translate'],type:'bool'},
  {key:'auto_summary',label:I18N['cfg.auto_summary'],type:'bool'},
  {key:'default_language',label:I18N['cfg.default_language'],type:'select',opts:['auto',...LANG_OPTS]},
  {key:'default_model',label:I18N['cfg.default_model'],type:'select',opts:['tiny','base','small','medium','large-v3']},
  {key:'output_directory',label:I18N['cfg.output_directory'],type:'text',ph:I18N['cfg.output_directory_ph']},
  {key:'llm_provider',label:I18N['cfg.llm_provider'],type:'select',opts:['claude','api']},
  {key:'api_endpoint',label:I18N['cfg.api_endpoint'],type:'text',ph:'https://...'},
  {key:'api_model',label:I18N['cfg.api_model'],type:'text',ph:'gpt-4o'},
  {key:'api_key_env',label:I18N['cfg.api_key_env'],type:'text',ph:'SHADOW_CLERK_API_KEY'},
  {key:'initial_prompt',label:I18N['cfg.initial_prompt'],type:'text',ph:I18N['cfg.initial_prompt_ph']},
  {key:'voice_command_key',label:I18N['cfg.voice_command_key'],type:'select',opts:['menu','f23','ctrl_r','ctrl_l','alt_r','alt_l','shift_r','shift_l']},
  {key:'whisper_beam_size',label:I18N['cfg.whisper_beam_size'],type:'select',opts:['1','2','3','5']},
  {key:'whisper_compute_type',label:I18N['cfg.whisper_compute_type'],type:'select',opts:['int8','float16','float32']},
  {key:'whisper_device',label:I18N['cfg.whisper_device'],type:'select',opts:['cpu','cuda']},
  {key:'interim_transcription',label:I18N['cfg.interim_transcription'],type:'bool'},
  {key:'interim_model',label:I18N['cfg.interim_model'],type:'select',opts:['tiny','base','small','medium']},
];
let cfgData={};
async function openCfg(){
  try{cfgData=await(await fetch('/api/config')).json();}catch(e){return;}
  const b=document.getElementById('cfgBody');b.innerHTML='';
  CFG_FIELDS.forEach(f=>{
    const lbl=document.createElement('label');lbl.textContent=f.label;b.appendChild(lbl);
    let el;const v=cfgData[f.key];
    if(f.type==='bool'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      ['true','false'].forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      el.value=v?'true':'false';
    }else if(f.type==='select'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      f.opts.forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      if(v!==null&&v!==undefined)el.value=String(v);
    }else if(f.type==='json'){
      el=document.createElement('textarea');el.id='cfg_'+f.key;
      el.value=JSON.stringify(v||[],null,2);
    }else{
      el=document.createElement('input');el.type='text';el.id='cfg_'+f.key;
      el.value=(v===null||v===undefined)?'':String(v);
      if(f.ph)el.placeholder=f.ph;
    }
    b.appendChild(el);
  });
  document.getElementById('cfgSaved').style.display='none';
  document.getElementById('cfgModal').classList.add('open');
}
function closeCfg(){document.getElementById('cfgModal').classList.remove('open');}
async function saveCfg(){
  const d={};
  CFG_FIELDS.forEach(f=>{
    const el=document.getElementById('cfg_'+f.key);if(!el)return;
    if(f.type==='bool'){d[f.key]=el.value==='true';}
    else if(f.type==='json'){try{d[f.key]=JSON.parse(el.value);}catch(e){d[f.key]=cfgData[f.key];}}
    else if(f.type==='select'){const sv=el.value;d[f.key]=(sv==='auto'&&f.key==='default_language')?null:sv;}
    else{const v=el.value.trim();d[f.key]=(v===''||v==='null')?null:v;}
  });
  const langChanged=d.ui_language&&d.ui_language!==cfgData.ui_language;
  try{await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(d)});
    if(langChanged){location.reload();return;}
    const s=document.getElementById('cfgSaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
const GL_COL_OPTS=[...LANG_OPTS,'note'];
let glossaryCols=[];
function glossaryAddRow(vals){
  const tb=document.getElementById('glossaryBody');
  const tr=document.createElement('tr');
  glossaryCols.forEach((c,i)=>{
    const td=document.createElement('td');
    const inp=document.createElement('input');
    inp.type='text'; inp.value=(vals&&vals[i])||'';
    inp.placeholder=c;
    td.appendChild(inp); tr.appendChild(td);
  });
  const del=document.createElement('td');
  del.className='gl-del'; del.textContent='\u00d7';
  del.onclick=()=>tr.remove();
  tr.appendChild(del); tb.appendChild(tr);
  return tr;
}
function glossaryMakeHeadSel(val){
  const sel=document.createElement('select');
  sel.style.cssText='background:transparent;color:var(--muted);border:none;font-weight:600;font-size:12px;cursor:pointer;padding:2px;';
  GL_COL_OPTS.forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;sel.appendChild(op);});
  sel.value=val;
  sel.onchange=()=>{const idx=[...sel.closest('tr').children].indexOf(sel.parentElement);glossaryCols[idx]=sel.value;};
  return sel;
}
async function openGlossary(){
  let text='';
  try{const r=await fetch('/api/glossary');text=await r.text();}catch(e){}
  const lines=text.split('\\n').filter(l=>l.trim()&&!l.startsWith('#'));
  glossaryCols=(lines.length>0)?lines[0].split('\\t'):['ja','en','note'];
  const head=document.getElementById('glossaryHead');
  head.innerHTML='';
  glossaryCols.forEach(c=>{const th=document.createElement('th');th.appendChild(glossaryMakeHeadSel(c));head.appendChild(th);});
  const thDel=document.createElement('th');thDel.style.width='30px';head.appendChild(thDel);
  const tb=document.getElementById('glossaryBody');
  tb.innerHTML='';
  for(let i=1;i<lines.length;i++){
    const cols=lines[i].split('\\t');
    glossaryAddRow(cols);
  }
  if(lines.length<=1)glossaryAddRow();
  document.getElementById('glossarySaved').style.display='none';
  document.getElementById('glossaryModal').classList.add('open');
}
function closeGlossary(){document.getElementById('glossaryModal').classList.remove('open');}
async function saveGlossary(){
  glossaryCols=[...document.querySelectorAll('#glossaryHead select')].map(s=>s.value);
  const rows=[glossaryCols.join('\\t')];
  document.querySelectorAll('#glossaryBody tr').forEach(tr=>{
    const vals=Array.from(tr.querySelectorAll('input')).map(i=>i.value);
    if(vals.some(v=>v.trim()))rows.push(vals.join('\\t'));
  });
  const text=rows.join('\\n')+'\\n';
  try{await fetch('/api/glossary',{method:'POST',headers:{'Content-Type':'text/plain; charset=utf-8'},
    body:text});
    const s=document.getElementById('glossarySaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
async function genSummary(){
  const f=curFile||undefined;
  const b=f?JSON.stringify({file:f}):'{}';
  try{await fetch('/api/summary',{method:'POST',headers:{'Content-Type':'application/json'},body:b});
    alert(I18N['dash.summary_started']);}catch(e){}
}
async function viewSummary(){
  const f=curFile?'?file='+encodeURIComponent(curFile):'';
  try{const d=await(await fetch('/api/summary'+f)).json();
    document.getElementById('summaryTitle').textContent=I18N['dash.summary_prefix']+(d.file||'');
    document.getElementById('summaryContent').textContent=d.content||I18N['dash.no_summary'];
    document.getElementById('summaryModal').classList.add('open');
  }catch(e){}
}
function closeSummary(){document.getElementById('summaryModal').classList.remove('open');}
function customCmdAddRow(pattern,action){
  const tb=document.getElementById('customCmdBody');
  const tr=document.createElement('tr');
  const td1=document.createElement('td');
  const inp1=document.createElement('input');inp1.type='text';inp1.value=pattern||'';inp1.placeholder='regex pattern';
  td1.appendChild(inp1);tr.appendChild(td1);
  const td2=document.createElement('td');
  const inp2=document.createElement('input');inp2.type='text';inp2.value=action||'';inp2.placeholder='shell command';
  td2.appendChild(inp2);tr.appendChild(td2);
  const del=document.createElement('td');
  del.className='gl-del';del.textContent='\\u00d7';
  del.onclick=()=>tr.remove();
  tr.appendChild(del);tb.appendChild(tr);
  return tr;
}
async function openCustomCmds(){
  let cmds=[];
  try{const d=await(await fetch('/api/config')).json();cmds=d.custom_commands||[];}catch(e){}
  const tb=document.getElementById('customCmdBody');tb.innerHTML='';
  cmds.forEach(c=>customCmdAddRow(c.pattern||'',c.action||''));
  if(cmds.length===0)customCmdAddRow();
  document.getElementById('customCmdSaved').style.display='none';
  document.getElementById('customCmdModal').classList.add('open');
}
function closeCustomCmds(){document.getElementById('customCmdModal').classList.remove('open');}
async function saveCustomCmds(){
  const rows=[];
  document.querySelectorAll('#customCmdBody tr').forEach(tr=>{
    const inputs=tr.querySelectorAll('input');
    const p=(inputs[0]||{}).value||'';
    const a=(inputs[1]||{}).value||'';
    if(p.trim()||a.trim())rows.push({pattern:p,action:a});
  });
  try{
    const cfg=await(await fetch('/api/config')).json();
    cfg.custom_commands=rows;
    await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
    const s=document.getElementById('customCmdSaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
function openHelp(){
  document.getElementById('helpContent').textContent=I18N['dash.help_body'];
  document.getElementById('helpModal').classList.add('open');
}
function closeHelp(){document.getElementById('helpModal').classList.remove('open');}
</script>
</body>
</html>
"""


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
    parser.add_argument(
        "--dashboard",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="ダッシュボード有効/無効 (default: 有効)",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=8765,
        help="ダッシュボードポート (default: 8765)",
    )
    parser.add_argument(
        "--beam-size",
        type=int,
        default=None,
        help="Whisper beam size (1=高速, 5=高精度)",
    )
    parser.add_argument(
        "--compute-type",
        default=None,
        choices=["int8", "float16", "float32"],
        help="Whisper 計算精度 (default: int8)",
    )
    parser.add_argument(
        "--device",
        default=None,
        choices=["cpu", "cuda"],
        help="Whisper デバイス (default: cpu)",
    )

    args = parser.parse_args()

    # データディレクトリ作成
    os.makedirs(DATA_DIR, exist_ok=True)

    # i18n 初期化
    from shadow_clerk import i18n as _i18n
    _i18n.init()

    # config.yaml の値を CLI 未指定の場合のみ適用
    config = load_config()
    if args.model == "small" and config.get("default_model"):
        args.model = config["default_model"]
    if args.language is None and config.get("default_language"):
        args.language = config["default_language"]
    args.whisper_beam_size = args.beam_size if args.beam_size is not None else config.get("whisper_beam_size", 5)
    args.whisper_compute_type = args.compute_type if args.compute_type is not None else config.get("whisper_compute_type", "int8")
    args.whisper_device = args.device if args.device is not None else config.get("whisper_device", "cpu")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_devices:
        backend_name, backend = detect_backend(args.backend)
        print(t("rec.backend", name=backend_name))
        list_all_devices(backend_name, backend)
        return

    recorder = Recorder(args)
    recorder.run()


if __name__ == "__main__":
    main()
