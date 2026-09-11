# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Windows 向けの 1 ディレクトリ配布

使い方 (**Windows の上で**):

    uv sync
    uv pip install pyinstaller
    uv run pyinstaller packaging/shadow-clerk.spec
    dist\\shadow-clerk\\clerk-daemon.exe

**クロスコンパイルはできない。** PyInstaller は動かしている OS 向けの実行
ファイルしか作らないので、Windows のバイナリは Windows で作る。Linux 上で
このファイルを流すと Linux 版が出来る（動作はするが配布物としては別物）。

`hooks/` には PyInstaller 同梱フックの差し替えが入っている(理由は各ファイルの
先頭に書いてある)。

**Whisper のモデルは同梱しない。** small で ~500MB あり、初回起動時に
HuggingFace から取得されて %USERPROFILE%\\.cache\\huggingface に残る。
オフライン配布したいなら、そのキャッシュを datas に足すか、
CT2 形式に変換したモデルを同梱して --model にパスを渡す。
"""
import importlib.util
import os

from PyInstaller.utils.hooks import collect_all

_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (spec の組み込み)
# 同梱フックを差し替えるためのディレクトリ。hooks/hook-webrtcvad.py を参照
_HOOKS = [os.path.join(SPECPATH, "hooks")]           # noqa: F821

# ネイティブ拡張と、その隣に置かれる DLL / データ。**どれも欠けると実行時に
# 落ちる**——PyInstaller はコード中の import しか追わないので、
# データファイルは明示的に集める:
#   ctranslate2     CTranslate2 本体の DLL (faster-whisper の推論エンジン)
#   av              FFmpeg の DLL 群 (音声の読み込み)
#   faster_whisper  assets/ に Silero VAD の onnx が入っている
#   tokenizers      Rust 拡張
#   onnxruntime     reazonspeech extra 用。入っていなければ飛ばす
#   langdetect      profiles/ が無いと言語判定が例外で落ちる
#   sounddevice     _sounddevice_data に PortAudio の DLL
#   pywinpty        AI Console の ConPTY。winpty の DLL を連れてくる
#   pyaudiowpatch   WASAPI ループバック (モニター音声の取り込み)
#   googleapiclient gcal extra 用。discovery のキャッシュを持つ
#   sherpa_onnx     reazonspeech extra 用。lib/ に onnxruntime の DLL を抱える
#   reazonspeech.k2.asr  同上。名前空間パッケージなので末端まで指定する
_PACKAGES = ("ctranslate2", "av", "faster_whisper", "tokenizers", "onnxruntime",
             "langdetect", "sounddevice", "webrtcvad", "pywinpty", "winpty",
             "pyaudiowpatch", "openai", "markdown_it", "pyte",
             "googleapiclient", "google_auth_oauthlib",
             "sherpa_onnx", "reazonspeech.k2.asr")

datas, binaries, hiddenimports = [], [], []
for _pkg in _PACKAGES:
    # **パッケージでないものは飛ばす。** sounddevice / webrtcvad / pywinpty は
    # 単一モジュールなので collect_all は「not a package」と警告するだけで
    # 何も集められない。これらの DLL は PyInstaller 同梱のフック
    # (hook-sounddevice.py など) が集めるので、ここで拾う必要は無い。
    # 警告だけが残ると、本当に失敗したときにそれが埋もれる
    try:
        _spec = importlib.util.find_spec(_pkg)
    except (ImportError, ValueError):
        continue                            # 任意の extra は入っていなくてよい
    if _spec is None or _spec.submodule_search_locations is None:
        continue
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# 使わない重量級を落とす。torch / transformers は spell-check extra だけの
# 依存で、入れると配布物が数 GB になる
_EXCLUDES = ["torch", "transformers", "sentencepiece", "tkinter", "matplotlib",
             "IPython", "pytest"]

_SRC = os.path.join(_ROOT, "src")
_daemon = Analysis([os.path.join(_SRC, "shadow_clerk", "clerk_daemon.py")],
                   pathex=[_SRC], binaries=binaries, datas=datas,
                   hiddenimports=hiddenimports, hookspath=_HOOKS,
                   excludes=_EXCLUDES, noarchive=False)
_util = Analysis([os.path.join(_SRC, "shadow_clerk", "clerk_util.py")],
                 pathex=[_SRC], binaries=binaries, datas=datas,
                 hiddenimports=hiddenimports, hookspath=_HOOKS,
                 excludes=_EXCLUDES, noarchive=False)

_daemon_exe = EXE(PYZ(_daemon.pure, _daemon.zipped_data), _daemon.scripts, [],
                  exclude_binaries=True, name="clerk-daemon", console=True)
_util_exe = EXE(PYZ(_util.pure, _util.zipped_data), _util.scripts, [],
                exclude_binaries=True, name="clerk-util", console=True)

# 1 つのディレクトリに両方入れる。DLL は共有されるので二重にはならない
coll = COLLECT(_daemon_exe, _daemon.binaries, _daemon.datas,
               _util_exe, _util.binaries, _util.datas,
               strip=False, upx=False, name="shadow-clerk")
