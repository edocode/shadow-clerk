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
    "wake_word": "シェルク",
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

# 音声コマンド検出パターン生成
# 既知のウェイクワードには Whisper の誤認識揺れを許容するパターンを用意
_KNOWN_WAKE_PATTERNS: dict[str, str] = {
    "シェルク": r"(?:sheruku|シェル[クグ]|シエル[クグ]|シュル[クグ])",
    "クラーク": r"(?:clerk|[ブプグクフ][ラー]{1,3}[ーッ]?[クゴグ]|フランク)",
}

# 清音/濁音/半濁音グループ（各文字がどのグループに属するか）
_DAKUTEN_GROUPS: list[str] = [
    "カガ", "キギ", "クグ", "ケゲ", "コゴ",
    "サザ", "シジ", "スズ", "セゼ", "ソゾ",
    "タダ", "チヂ", "ツヅ", "テデ", "トド",
    "ハバパ", "ヒビピ", "フブプ", "ヘベペ", "ホボポ",
]
_CHAR_TO_GROUP: dict[str, str] = {}
for _g in _DAKUTEN_GROUPS:
    for _ch in _g:
        _CHAR_TO_GROUP[_ch] = _g

# 小書き↔通常ペア
_KOGAKI_PAIRS: dict[str, str] = {}
for _pair in ["ァア", "ィイ", "ゥウ", "ェエ", "ォオ", "ャヤ", "ュユ", "ョヨ", "ッツ"]:
    for _ch in _pair:
        _KOGAKI_PAIRS[_ch] = _pair


def _generate_katakana_pattern(word: str) -> str:
    """カタカナ文字列から Whisper 誤認識揺れを許容する正規表現パターンを生成。

    非カタカナ入力は re.escape() にフォールバック。
    """
    # None/空文字はそのまま escape
    if not word:
        return re.escape(word or "")
    # カタカナ判定（長音符も許容）
    if not all(
        '\u30A0' <= ch <= '\u30FF' or ch == 'ー' for ch in word
    ):
        return re.escape(word)

    parts: list[str] = []
    for ch in word:
        if ch == 'ー':
            parts.append('ー?')
        elif ch in _CHAR_TO_GROUP:
            group = _CHAR_TO_GROUP[ch]
            # 小書きペアも含める
            chars = set(group)
            for g_ch in group:
                if g_ch in _KOGAKI_PAIRS:
                    chars.update(_KOGAKI_PAIRS[g_ch])
            parts.append(f'[{"".join(sorted(chars))}]')
        elif ch in _KOGAKI_PAIRS:
            parts.append(f'[{_KOGAKI_PAIRS[ch]}]')
        else:
            parts.append(re.escape(ch))

    kata_pat = ''.join(parts)

    # ひらがなバリアント生成（カタカナ→ひらがな: U+30A0→U+3040 差分=0x60）
    hira_pat = ''.join(
        chr(ord(ch) - 0x60) if '\u30A1' <= ch <= '\u30F6' else ch
        for ch in kata_pat
    )

    return f'(?:{kata_pat}|{hira_pat})'


def build_wake_word_patterns(wake_word: str | None) -> tuple[re.Pattern, re.Pattern]:
    """wake_word 設定値から PREFIX/SUFFIX パターンを生成。

    None/空文字の場合は絶対にマッチしないパターンを返す。
    """
    if not wake_word or not wake_word.strip():
        wake_word = DEFAULT_CONFIG["wake_word"]
    pat = _KNOWN_WAKE_PATTERNS.get(wake_word)
    if pat is None:
        pat = _generate_katakana_pattern(wake_word)
    prefix = re.compile(rf"(?i)^[\s]*{pat}[,、\s]*")
    suffix = re.compile(rf"(?i)[,、\s]*{pat}[\s]*$")
    return prefix, suffix


# デフォルトパターン（後方互換）
VOICE_CMD_PREFIX, VOICE_CMD_SUFFIX = build_wake_word_patterns(
    DEFAULT_CONFIG["wake_word"]
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
