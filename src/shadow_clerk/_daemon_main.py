"""Shadow-clerk daemon: エントリーポイント"""
import argparse
import atexit
import logging
import os
import sys
from shadow_clerk import DATA_DIR
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import PID_FILE, LOG_FILE
from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_audio import detect_backend, list_all_devices
from shadow_clerk._daemon_recorder import Recorder

logger = logging.getLogger("shadow-clerk")


def _daemonize():
    """ダブルフォークでデーモン化"""
    pid = os.fork()
    if pid > 0:
        sys.exit(0)
    os.setsid()
    pid = os.fork()
    if pid > 0:
        sys.exit(0)
    # 標準入出力を /dev/null にリダイレクト
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)


def _write_pid_file():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid_file():
    try:
        os.unlink(PID_FILE)
    except FileNotFoundError:
        pass


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
    parser.add_argument(
        "--daemon", "-d",
        action="store_true",
        help="デーモンとして起動（バックグラウンド実行、ログは daemon.log に出力）",
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

    log_level = logging.DEBUG if args.verbose else logging.INFO
    log_format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    log_datefmt = "%H:%M:%S"

    if args.daemon:
        # デーモン化（ダブルフォークでバックグラウンド実行）
        _daemonize()
        # ログはファイルのみ（stderr には出さない）
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setFormatter(logging.Formatter(log_format, datefmt=log_datefmt))
        logging.basicConfig(level=log_level, handlers=[file_handler])
    else:
        logging.basicConfig(
            level=log_level,
            format=log_format,
            datefmt=log_datefmt,
        )

    # PID ファイルは常に書き込む（clerk-util recorder-status で使用）
    _write_pid_file()
    atexit.register(_remove_pid_file)

    if args.list_devices:
        backend_name, backend = detect_backend(args.backend)
        print(t("rec.backend", name=backend_name))
        list_all_devices(backend_name, backend)
        return

    recorder = Recorder(args)
    recorder.run()


if __name__ == "__main__":
    main()
