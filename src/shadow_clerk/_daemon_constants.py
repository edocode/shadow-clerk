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
MAX_SEGMENT_DURATION = 20.0  # 最大セグメント長(秒)
# 30秒→20秒に短縮 (2026-08): ASR 推論アリーナは最長セグメント長にスケールし、
# 実測で 10秒 segment は +165MB、30秒 segment は +457MB。20秒はその中間で
# ピークメモリを抑えつつ、20秒を超える発話は強制分割されるトレードオフを許容する。
INTERIM_MAX_DURATION = 10.0  # interim 転写に渡す直近音声の最大長(秒)

# 音声ストリーム監視 (サスペンド復帰・出力デバイス切替からの自動復帰)
# 正常時のコールバックは SAMPLE_RATE/FRAME_SIZE ≒ 33 回/秒 で、無音の sink でも
# 途切れない。数秒の途絶は即ストリーム死亡を意味する。
STREAM_STALL_SEC = 15.0  # フレーム途絶をこの秒数で死亡と判定
STREAM_CHECK_INTERVAL = 2.0  # ウォッチドッグのチェック間隔(秒)
STREAM_RESOLVE_INTERVAL = 10.0  # デフォルト Sink 変更チェックの間隔(秒)
STREAM_RETRY_SEC = 5.0  # 再接続失敗時の待機(秒)
STREAM_DEGRADED_RETRY_SEC = 30.0  # 一部デバイスを開けなかった場合の再試行間隔(秒)
# 再試行は全ストリームの張り替えを伴い音が欠ける。空振りが続く間は指数的に伸ばす
STREAM_DEGRADED_RETRY_MAX_SEC = 300.0

# wpctl / pactl / pw-dump などローカル IPC の呼び出しタイムアウト(秒)。
# いずれもローカルのサウンドサーバーに聞くだけで通常は数十ミリ秒で返る。
# 待たされる = サーバーが刺さっているということなので、長い上限を置いても
# 復帰は早まらない。これらはキャプチャスレッド上で同期的に走り、shutdown の
# join は 5 秒なので、その予算に収まる長さにしておく必要がある
IPC_TIMEOUT_SEC = 1.5

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
    # reasoning/thinking モデルで interim・翻訳の思考過程出力を抑制する
    # (Qwen3 等の vLLM で enable_thinking=false を送る)。要約は品質のため常に思考する。
    "api_disable_thinking": False,
    "claude_cli_path": "claude",
    "claude_cli_model": "haiku",
    "custom_commands": [],
    "initial_prompt": None,
    # 音声デバイス。null = OS のデフォルトに追従。値はデバイス名（番号は不安定）
    "mic_device": None,
    "monitor_device": None,
    "voice_command_key": "f23",
    "wake_word": "シェルク",
    "whisper_beam_size": 5,        # beam_size (1=高速, 5=高精度)
    "whisper_compute_type": "int8", # int8/float16/float32
    "whisper_device": "cpu",       # cpu/cuda
    "interim_transcription": False,
    "interim_translation": True,  # interim_transcription の出力を翻訳して dashboard に流す
    "interim_translation_provider": None,  # null=auto / "api" / "libretranslate" / "claude"
    "interim_model": "base",
    "ui_language": "ja",
    "translation_provider": None,
    "libretranslate_endpoint": None,
    "libretranslate_api_key": None,
    "libretranslate_spell_check": False,
    "spell_check_model": "mbyhphat/t5-japanese-typo-correction",
    "summary_source": None,
    "summary_language": None,
    "summary_hiragana_step": True,
    "summary_length": "half",
    "translation_hiragana_step": True,
    "japanese_asr_model": "default",
    "kotoba_whisper_model": "kotoba-tech/kotoba-whisper-v2.0-faster",
    "interim_japanese_asr_model": "default",
    "reazonspeech_precision": "fp32",  # fp32 / int8 / int8-fp32 (fp16 は無効)
    # Google Calendar 連携
    "gcal_integration": False,
    "gcal_credentials_file": None,   # OAuth credentials.json のパス
    "gcal_token_file": None,         # 認証済みトークンの保存先 (default: DATA_DIR/gcal_token.json)
    "gcal_calendar_id": "primary",
    "gcal_buffer_minutes": 2,        # 開始 N 分前に start_meeting を送信
    "gcal_end_buffer_minutes": 1,    # 終了 N 分後に end_meeting を送信
}

# セッションファイル
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
        wake_word = str(DEFAULT_CONFIG["wake_word"])
    pat = _KNOWN_WAKE_PATTERNS.get(wake_word)
    if pat is None:
        pat = _generate_katakana_pattern(wake_word)
    prefix = re.compile(rf"(?i)^[\s]*{pat}[,、\s]*")
    suffix = re.compile(rf"(?i)[,、\s]*{pat}[\s]*$")
    return prefix, suffix


# デフォルトパターン（後方互換）
VOICE_CMD_PREFIX, VOICE_CMD_SUFFIX = build_wake_word_patterns(
    str(DEFAULT_CONFIG["wake_word"])
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
