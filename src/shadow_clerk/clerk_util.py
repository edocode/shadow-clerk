#!/usr/bin/env python3
"""shadow-clerk ユーティリティ — データディレクトリ操作 + プロセス管理"""
from __future__ import annotations
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

from shadow_clerk import DATA_DIR, CONFIG_FILE
from shadow_clerk._transcript_name import TranscriptName

# config.yaml から output_directory を読む
OUTPUT_DIR = DATA_DIR


def _read_output_directory() -> None:
    """config.yaml の output_directory を読んで OUTPUT_DIR を返す"""
    global OUTPUT_DIR
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            for line in f:
                if line.startswith("output_directory:"):
                    val = line.split(":", 1)[1].strip()
                    if val and val != "null":
                        OUTPUT_DIR = os.path.expanduser(val)
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        return
    OUTPUT_DIR = DATA_DIR


_read_output_directory()


# --- サブコマンド実装 ---


def cmd_ls(args: list[str]) -> None:
    try:
        result = subprocess.run(["ls", "-la", DATA_DIR + "/"], capture_output=True, text=True)
        sys.stdout.write(result.stdout)
    except Exception:
        pass
    if OUTPUT_DIR != DATA_DIR:
        print()
        print(f"Output directory ({OUTPUT_DIR}):")
        try:
            result = subprocess.run(["ls", "-la", OUTPUT_DIR + "/"], capture_output=True, text=True)
            sys.stdout.write(result.stdout)
        except Exception:
            pass


def cmd_command(args: list[str]) -> None:
    cmd_text = " ".join(args)
    if not _is_recorder_running():
        print("error: clerk-daemon is not running", file=sys.stderr)
        sys.exit(1)
    import yaml
    try:
        with open(CONFIG_FILE) as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    port = cfg.get("dashboard_port", 8765)
    try:
        import urllib.request
        req = urllib.request.Request(
            f"http://localhost:{port}/api/command",
            data=json.dumps({"command": cmd_text}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        print(f"error: command send failed: {e}", file=sys.stderr)
        sys.exit(1)


PID_FILE = os.path.join(DATA_DIR, "daemon.pid")


def _read_pid() -> int | None:
    """PID ファイルから PID を読み取る。ファイルがなければ None"""
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _is_pid_alive(pid: int) -> bool:
    """プロセスが存在するか"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _is_recorder_running() -> bool:
    """clerk-daemon プロセスが動作中か"""
    pid = _read_pid()
    return bool(pid and _is_pid_alive(pid))


def cmd_recorder_status(args: list[str]) -> None:
    print("running" if _is_recorder_running() else "stopped")


def cmd_read_config(args: list[str]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            sys.stdout.write(f.read())
    else:
        default_config = """# shadow-clerk 設定
translate_language: ja
auto_translate: false
auto_summary: false
default_language: null
default_model: small
output_directory: null
llm_provider: claude
api_endpoint: null
api_model: null
api_key_env: SHADOW_CLERK_API_KEY
custom_commands: []
initial_prompt: null
voice_command_key: f23
wake_word: シェルク
ui_language: ja"""
        with open(CONFIG_FILE, "w") as f:
            f.write(default_config + "\n")
        with open(CONFIG_FILE) as f:
            sys.stdout.write(f.read())


def cmd_write_config_value(args: list[str]) -> None:
    """YAML を読み込み、指定キーを更新して書き戻す"""
    key = args[0]
    value_str = args[1]

    # 値の型変換
    if value_str == "true":
        yaml_value = "true"
    elif value_str == "false":
        yaml_value = "false"
    elif value_str == "null":
        yaml_value = "null"
    else:
        yaml_value = value_str

    # config.yaml を読み込み
    if os.path.isfile(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            lines = f.readlines()
    else:
        # read-config でデフォルト生成
        cmd_read_config([])
        with open(CONFIG_FILE) as f:
            lines = f.readlines()

    # 指定キーの行を更新
    found = False
    new_lines = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(key + ":"):
            new_lines.append(f"{key}: {yaml_value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}: {yaml_value}\n")

    with open(CONFIG_FILE, "w") as f:
        f.writelines(new_lines)


def _exec_clerk_daemon(args: list[str]) -> None:
    """同じ環境の clerk-daemon をフォアグラウンドで起動する。

    Linux: os.execv で現在のプロセスを置き換える(Ctrl+C で停止可能)。
    Windows: os.execv は新プロセスを spawn して親が即終了するため見かけ上
    バックグラウンド化する。これを避けるため subprocess.run で待機する。
    """
    names = ("clerk-daemon.exe", "clerk-daemon") if sys.platform == "win32" else ("clerk-daemon",)
    exe: str | None = None
    for base in (pathlib.Path(sys.executable).parent, pathlib.Path(sys.argv[0]).resolve().parent):
        for name in names:
            candidate = base / name
            if candidate.exists():
                exe = str(candidate)
                break
        if exe:
            break
    if not exe:
        # PATH フォールバック: shutil.which は Windows で .exe を自動補完
        exe = shutil.which("clerk-daemon") or "clerk-daemon"

    if sys.platform == "win32":
        try:
            result = subprocess.run([exe] + args, check=False)
        except KeyboardInterrupt:
            sys.exit(130)
        sys.exit(result.returncode)
    os.execv(exe, [exe] + args)


def cmd_start(args: list[str]) -> None:
    """clerk-daemon [opts] を exec"""
    _exec_clerk_daemon(list(args))


def _terminate_pid(pid: int) -> None:
    """OS に応じて clerk-daemon プロセスを終了させる。

    Linux: SIGTERM。
    Windows: taskkill /PID (graceful) → 5秒待っても残るなら taskkill /F。
    """
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid)],
                capture_output=True, timeout=5, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        # 残っていたら強制終了
        for _ in range(10):
            if not _is_pid_alive(pid):
                return
            time.sleep(0.5)
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, timeout=5, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return
    import signal as _signal
    os.kill(pid, _signal.SIGTERM)


def cmd_stop(args: list[str]) -> None:
    """clerk-daemon プロセスを停止 (Linux: SIGTERM, Windows: taskkill)"""
    pid = _read_pid()
    if pid and _is_pid_alive(pid):
        _terminate_pid(pid)
    elif sys.platform != "win32":
        subprocess.run(["pkill", "-f", "clerk-daemon|clerk_daemon"])
    else:
        print("warning: PIDファイルが見つかりません。実行中の clerk-daemon を特定できません。", file=sys.stderr)


def cmd_restart(args: list[str]) -> None:
    """clerk-daemon を停止 → 待機 → 起動"""
    # 停止
    if _is_recorder_running():
        pid = _read_pid()
        if pid and _is_pid_alive(pid):
            _terminate_pid(pid)
        elif sys.platform != "win32":
            subprocess.run(["pkill", "-f", "clerk-daemon|clerk_daemon"])
        else:
            print("warning: PIDファイルが見つかりません。実行中の clerk-daemon を特定できません。", file=sys.stderr)
        # 終了待機（最大10秒）
        for _ in range(20):
            time.sleep(0.5)
            if not _is_recorder_running():
                break
        else:
            print("warning: clerk-daemon が停止しませんでした", file=sys.stderr)
            sys.exit(1)
    # 起動 (exec)
    _exec_clerk_daemon(list(args))


def cmd_run_llm(args: list[str]) -> None:
    """python -m shadow_clerk.llm_client <args...> を exec"""
    os.execvp(sys.executable, [sys.executable, "-m", "shadow_clerk.llm_client"] + list(args))


def cmd_summarize(args: list[str]) -> None:
    """clerk-util summarize [YYYYMMDD|YYYYMMDDHHMM[@name]|transcript-*.txt] [--mode full|update]

    日付またはファイル名からファイルを自動解決し、llm_client summarize を実行する。

    引数の解決順:
      1. transcript-*.txt 形式 → そのまま使用
      2. YYYYMMDDHHMM@name 形式 → 該当ファイルを使用
      3. YYYYMMDDHHMM(名前なし)形式: transcript-YYYYMMDDHHMM.txt が存在すればそれ、
         無ければ同タイムスタンプの会議ファイル `transcript-YYYYMMDDHHMM@*.txt` を
         glob で検索(1件なら自動選択、複数ヒットならエラーにして候補を表示)
      4. YYYYMMDD 形式 → transcript-YYYYMMDD.txt(日次ファイル)
      5. 引数なし → .clerk_session → 今日の日付

    --mode 省略時は full。
    """
    import datetime

    # 引数パース
    date_str = None
    mode = "full"
    i = 0
    while i < len(args):
        if args[i] == "--mode" and i + 1 < len(args):
            mode = args[i + 1]
            i += 2
        elif not args[i].startswith("-"):
            date_str = args[i]
            i += 1
        else:
            i += 1

    # transcript-*.txt 形式のファイル名 → TranscriptName で解析
    if date_str and (tn := TranscriptName.parse(date_str)):
        pass
    elif date_str:
        tn = TranscriptName.from_date_str(date_str)
    else:
        tn = None

    # 日付が未指定の場合: .clerk_session → 今日の日付
    if tn is None:
        session_file = os.path.join(DATA_DIR, ".clerk_session")
        if os.path.isfile(session_file):
            with open(session_file) as f:
                session_name = f.read().strip()
            if session_name:
                tn = TranscriptName.parse(os.path.basename(session_name))
        if tn is None:
            tn = TranscriptName(datetime.datetime.now().strftime("%Y%m%d"))

    # ファイルパス解決
    transcript_name = tn.filename
    transcript_path = os.path.join(OUTPUT_DIR, transcript_name)

    # 名前なしで指定された(`tn.meeting_name is None`) かつ実ファイル無し →
    # 同タイムスタンプの会議名付きファイル `transcript-<dt>@*.txt` を探す
    # (TranscriptName.parse は翻訳ファイル `-{lang}.txt` を除外するので候補から自動的に外れる)
    if not os.path.isfile(transcript_path) and tn.meeting_name is None:
        import glob
        pattern = os.path.join(OUTPUT_DIR, f"transcript-{tn.datetime_str}@*.txt")
        candidates = sorted(
            (f for f in glob.glob(pattern)
             if TranscriptName.parse(os.path.basename(f)) is not None),
        )
        if len(candidates) == 1:
            tn = TranscriptName.parse(os.path.basename(candidates[0])) or tn
            transcript_name = tn.filename
            transcript_path = candidates[0]
        elif len(candidates) > 1:
            print("複数の会議ファイルがマッチしました。明示的に指定してください:", file=sys.stderr)
            for c in candidates:
                print(f"  {os.path.basename(c)}", file=sys.stderr)
            sys.exit(1)

    summary_name = tn.summary_filename
    summary_path = os.path.join(OUTPUT_DIR, summary_name)

    # summary_source 設定をチェック
    # - "transcript": 強制的に transcript
    # - "translate":  強制的に translation（無ければ transcript にフォールバック）
    # - None (未指定): translation があれば translation、無ければ transcript
    source_path = transcript_path
    if os.path.isfile(CONFIG_FILE):
        import yaml
        with open(CONFIG_FILE) as f:
            config = yaml.safe_load(f) or {}
        summary_source = config.get("summary_source")
        if summary_source in ("translate", None):
            translate_lang = config.get("translate_language", "en")
            translation_name = tn.translation_filename(translate_lang)
            translation_path = os.path.join(OUTPUT_DIR, translation_name)
            if os.path.isfile(translation_path):
                source_path = translation_path
            elif summary_source == "translate":
                print(f"Warning: translation file not found ({translation_name}), falling back to transcript", file=sys.stderr)

    if not os.path.isfile(source_path):
        print(f"Error: file not found: {source_path}", file=sys.stderr)
        sys.exit(1)

    # llm_client summarize を実行
    import subprocess
    llm_args = [sys.executable, "-m", "shadow_clerk.llm_client",
                "summarize", "--mode", mode, "--file", source_path, "--output", summary_path]
    if mode == "update" and os.path.isfile(summary_path):
        llm_args += ["--existing", summary_path]

    result = subprocess.run(llm_args)

    # 完了通知をダッシュボードに送信
    if result.returncode == 0:
        import yaml
        try:
            with open(CONFIG_FILE) as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            cfg = {}
        port = cfg.get("dashboard_port", 8765)
        try:
            import urllib.request
            req = urllib.request.Request(
                f"http://localhost:{port}/api/summary/notify",
                data=json.dumps({"name": summary_name}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # daemon が動いていない場合は無視

    sys.exit(result.returncode)


def cmd_gcal_auth(args: list[str]) -> None:
    """Google Calendar OAuth 認証フローを実行してトークンを保存する"""
    if not args:
        print("Usage: clerk-util gcal-auth <credentials.json> [token_file]", file=sys.stderr)
        print("  credentials.json: Google Cloud Console でダウンロードした OAuth 2.0 クライアント認証情報", file=sys.stderr)
        sys.exit(1)
    credentials_file = args[0]
    token_file = args[1] if len(args) > 1 else None
    try:
        from shadow_clerk.gcal_monitor import run_auth
        run_auth(credentials_file, token_file)
    except ImportError:
        print("エラー: google-auth-oauthlib が見つかりません。", file=sys.stderr)
        print("  uv sync --extra gcal", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"認証エラー: {e}", file=sys.stderr)
        sys.exit(1)
    # 認証成功後に config を自動更新
    abs_creds = os.path.abspath(credentials_file)
    cmd_write_config_value(["gcal_integration", "true"])
    cmd_write_config_value(["gcal_credentials_file", abs_creds])
    print(f"config を更新しました: gcal_integration=true, gcal_credentials_file={abs_creds}")


def cmd_help(args: list[str]) -> None:
    print("clerk-util — shadow-clerk ユーティリティ")
    print()
    print("Usage: clerk-util <subcommand> [args]")
    print()
    print("Data subcommands:")
    print("  ls                         データディレクトリの一覧")
    print("  command <cmd>              clerk-daemon にコマンドを送信 (HTTP /api/command)")
    print("  recorder-status            clerk-daemon の動作状態 (running/stopped)")
    print("  read-config                config.yaml を読む（なければデフォルト生成）")
    print("  write-config-value <k> <v> config.yaml の指定キーを更新")
    print()
    print("Process subcommands:")
    print("  start [opts]      clerk-daemon を起動 (exec)")
    print("  stop              clerk-daemon を停止 (SIGTERM)")
    print("  restart [opts]    clerk-daemon を停止→待機→起動 (exec)")
    print("  run-llm <args...>          llm_client を実行 (exec)")
    print("  summarize [DATE|FILE] [--mode full|update]  議事録を生成")
    print("                             DATE: YYYYMMDD / YYYYMMDDHHMM[@name]、FILE: transcript-*.txt")
    print("                             名前なしタイムスタンプ指定なら同 dt の会議ファイルを自動検索")
    print()
    print("Setup subcommands:")
    print("  gcal-auth <credentials.json> [token_file]  Google Calendar OAuth 認証")
    print()
    print(f"Data directory: {DATA_DIR}")


COMMANDS = {
    "ls": cmd_ls,
    "command": cmd_command,
    "recorder-status": cmd_recorder_status,
    "read-config": cmd_read_config,
    "write-config-value": cmd_write_config_value,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "run-llm": cmd_run_llm,
    "summarize": cmd_summarize,
    "gcal-auth": cmd_gcal_auth,
    "help": cmd_help,
}


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    if len(sys.argv) < 2:
        cmd_help([])
        sys.exit(1)

    subcmd = sys.argv[1]
    rest = sys.argv[2:]

    handler = COMMANDS.get(subcmd)
    if handler is None:
        cmd_help([])
        sys.exit(1)

    handler(rest)


if __name__ == "__main__":
    main()
