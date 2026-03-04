"""Shadow-clerk daemon: 定数・デフォルト設定"""

import os
import re
from shadow_clerk import DATA_DIR, CONFIG_FILE

# --- オプショナル依存パッケージ ---
try:
    from pynput import keyboard as pynput_keyboard
    _HAS_PYNPUT = True
except ImportError:
    pynput_keyboard = None  # type: ignore[assignment]
    _HAS_PYNPUT = False

try:
    import evdev
    from evdev import ecodes as _ecodes
    _HAS_EVDEV = True
except ImportError:
    evdev = None  # type: ignore[assignment]
    _ecodes = None  # type: ignore[assignment]
    _HAS_EVDEV = False

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

DEFAULT_CONFIG = {
    "translate_language": "en",
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
    "interim_model": "base",
    "ui_language": "ja",
    "translation_provider": None,
    "libretranslate_endpoint": None,
    "libretranslate_api_key": None,
    "libretranslate_spell_check": False,
    "spell_check_model": "mbyhphat/t5-japanese-typo-correction",
    "summary_source": "transcript",
    "japanese_asr_model": "default",
    "kotoba_whisper_model": "kotoba-tech/kotoba-whisper-v2.0-faster",
    "interim_japanese_asr_model": "default",
}

# コマンド・セッションファイル
COMMAND_FILE = os.path.join(DATA_DIR, ".clerk_command")
SESSION_FILE = os.path.join(DATA_DIR, ".clerk_session")
PID_FILE = os.path.join(DATA_DIR, "daemon.pid")
LOG_FILE = os.path.join(DATA_DIR, "daemon.log")
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
