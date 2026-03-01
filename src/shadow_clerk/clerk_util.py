#!/usr/bin/env python3
"""shadow-clerk ユーティリティ — データディレクトリ操作 + プロセス管理"""

import importlib.resources
import json
import os
import shutil
import subprocess
import sys
import time

from shadow_clerk import DATA_DIR, CONFIG_FILE, get_data_dir, get_skill_dir

# config.yaml から output_directory を読む
OUTPUT_DIR = DATA_DIR


def _read_output_directory():
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


def resolve_path(name):
    """ファイル名に応じてディレクトリを解決する"""
    if name.startswith("transcript-") or name.startswith("summary-"):
        return os.path.join(OUTPUT_DIR, name)
    return os.path.join(DATA_DIR, name)


# --- サブコマンド実装 ---


def cmd_read(args):
    path = resolve_path(args[0])
    try:
        with open(path) as f:
            sys.stdout.write(f.read())
    except FileNotFoundError:
        pass


def cmd_read_from(args):
    path = resolve_path(args[0])
    offset = int(args[1])
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            data = f.read()
            sys.stdout.buffer.write(data)
    except FileNotFoundError:
        pass


def cmd_write(args):
    path = resolve_path(args[0])
    with open(path, "w") as f:
        f.write(args[1] + "\n")


def cmd_append(args):
    path = resolve_path(args[0])
    if len(args) >= 3 and args[1] == "-f":
        with open(args[2]) as src, open(path, "a") as dst:
            dst.write(src.read())
    elif len(args) >= 2:
        with open(path, "a") as f:
            f.write(args[1] + "\n")
    else:
        with open(path, "a") as f:
            f.write(sys.stdin.read())


def cmd_lines(args):
    path = resolve_path(args[0])
    try:
        with open(path) as f:
            count = sum(1 for _ in f)
        print(count)
    except FileNotFoundError:
        print(0)


def cmd_size(args):
    path = resolve_path(args[0])
    try:
        print(os.path.getsize(path))
    except FileNotFoundError:
        pass


def cmd_mtime(args):
    path = resolve_path(args[0])
    try:
        st = os.stat(path)
        # stat -c %y 互換のフォーマット
        from datetime import datetime

        dt = datetime.fromtimestamp(st.st_mtime)
        print(dt.strftime("%Y-%m-%d %H:%M:%S.%f") + " " + time.strftime("%z"))
    except FileNotFoundError:
        pass


def cmd_exists(args):
    path = resolve_path(args[0])
    print("yes" if os.path.isfile(path) else "no")


def cmd_ls(args):
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


def cmd_command(args):
    cmd_text = " ".join(args)
    with open(os.path.join(DATA_DIR, ".clerk_command"), "w") as f:
        f.write(cmd_text)


def _is_recorder_running():
    """clerk-daemon プロセスが動作中か"""
    result = subprocess.run(
        ["pgrep", "-f", "clerk-daemon|clerk_daemon"], capture_output=True, text=True
    )
    return result.returncode == 0


def cmd_recorder_status(args):
    print("running" if _is_recorder_running() else "stopped")


def cmd_read_config(args):
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
ui_language: ja"""
        with open(CONFIG_FILE, "w") as f:
            f.write(default_config + "\n")
        with open(CONFIG_FILE) as f:
            sys.stdout.write(f.read())


def cmd_write_config(args):
    with open(CONFIG_FILE, "w") as f:
        f.write(sys.stdin.read())


def cmd_write_config_value(args):
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


def cmd_path(args):
    print(shutil.which("clerk-util") or os.path.abspath(__file__))


def cmd_poll_command(args):
    """
    .clerk_command を interval 秒ごとにチェックし、
    コマンドがあればその内容を stdout に出力して終了。
    recorder-status が stopped なら 'stopped' を出力して終了。
    """
    interval = float(args[0])
    cmd_file = os.path.join(DATA_DIR, ".clerk_command")

    while True:
        # コマンドファイルをチェック
        if os.path.isfile(cmd_file):
            try:
                with open(cmd_file) as f:
                    content = f.read().strip()
                if content:
                    print(content)
                    return
            except FileNotFoundError:
                pass

        # recorder-status をチェック
        if not _is_recorder_running():
            print("stopped")
            return

        time.sleep(interval)


def cmd_start(args):
    """clerk-daemon [opts] を exec"""
    os.execvp("clerk-daemon", ["clerk-daemon"] + list(args))


def cmd_stop(args):
    """clerk-daemon プロセスに SIGTERM 送信"""
    subprocess.run(["pkill", "-f", "clerk-daemon|clerk_daemon"])


def cmd_restart(args):
    """clerk-daemon を停止 → 待機 → 起動"""
    # 停止
    if _is_recorder_running():
        subprocess.run(["pkill", "-f", "clerk-daemon|clerk_daemon"])
        # 終了待機（最大10秒）
        for _ in range(20):
            time.sleep(0.5)
            if not _is_recorder_running():
                break
        else:
            print("warning: clerk-daemon が停止しませんでした", file=sys.stderr)
            sys.exit(1)
    # 起動 (exec)
    os.execvp("clerk-daemon", ["clerk-daemon"] + list(args))


def cmd_run_llm(args):
    """python -m shadow_clerk.llm_client <args...> を exec"""
    os.execvp(sys.executable, [sys.executable, "-m", "shadow_clerk.llm_client"] + list(args))


def cmd_claude_setup(args):
    """Claude Code skill として登録する"""
    # 言語オプションの解析
    lang = args[0] if args else None

    skill_dir = get_skill_dir()

    # 既存シンボリックリンクがあれば警告
    if os.path.islink(skill_dir):
        print(f"WARNING: {skill_dir} はシンボリックリンクです。")
        print(f"  削除してから再実行してください: rm {skill_dir}")
        sys.exit(1)

    os.makedirs(skill_dir, exist_ok=True)
    os.makedirs(get_data_dir(), exist_ok=True)

    # clerk-util のインストールパスを取得
    clerk_util_path = shutil.which("clerk-util")
    if not clerk_util_path:
        print("ERROR: clerk-util がパスに見つかりません。", file=sys.stderr)
        print("  pip install shadow-clerk でインストールしてください。", file=sys.stderr)
        sys.exit(1)

    # テンプレートファイルを選択: SKILL.<lang>.md.template があればそれを使う
    template_name = "SKILL.md.template"
    if lang:
        lang_template = f"SKILL.{lang}.md.template"
        lang_resource = importlib.resources.files("shadow_clerk").joinpath(f"data/{lang_template}")
        if lang_resource.is_file():
            template_name = lang_template
        else:
            print(f"NOTE: {lang_template} not found, using default SKILL.md.template")

    template = importlib.resources.files("shadow_clerk").joinpath(f"data/{template_name}").read_text()
    skill_md = template.replace("{clerk_util_path}", clerk_util_path)
    skill_md = skill_md.replace("{data_dir}", get_data_dir())

    skill_md_path = os.path.join(skill_dir, "SKILL.md")
    with open(skill_md_path, "w", encoding="utf-8") as f:
        f.write(skill_md)
    lang_label = f" ({lang})" if lang and template_name != "SKILL.md.template" else ""
    print(f"SKILL.md を生成しました{lang_label}: {skill_md_path}")

    # settings.local.json に permission エントリ追加
    _register_permissions(clerk_util_path)


def _register_permissions(clerk_util_path):
    """~/.claude/settings.local.json に clerk-util の permission を追加する"""
    settings_path = os.path.expanduser("~/.claude/settings.local.json")

    # 既存の settings を読み込み
    settings = {}
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    permissions = settings.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])

    entries = [
        f"Bash({clerk_util_path} *)",
    ]

    added = []
    for entry in entries:
        if entry not in allow:
            allow.append(entry)
            added.append(entry)

    if added:
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print("permissions を追加しました:")
        for e in added:
            print(f"  {e}")
    else:
        print("permissions は既に登録済みです。")


def cmd_help(args):
    print("clerk-util — shadow-clerk ユーティリティ")
    print()
    print("Usage: clerk-util <subcommand> [args]")
    print()
    print("Data subcommands:")
    print("  read <file>                ファイルを読む")
    print("  read-from <file> <offset>  オフセット位置から読む")
    print("  write <file> <text>        ファイルに書き込む")
    print("  append <file> <text>       ファイルに追記する")
    print("  lines <file>               行数を表示")
    print("  size <file>                バイト数を表示")
    print("  mtime <file>               最終更新日時を表示")
    print("  exists <file>              ファイルの存在確認")
    print("  ls                         データディレクトリの一覧")
    print("  command <cmd>              clerk-daemon にコマンドを送信")
    print("  recorder-status            clerk-daemon の動作状態 (running/stopped)")
    print("  read-config                config.yaml を読む（なければデフォルト生成）")
    print("  write-config               stdin から config.yaml を書き込む")
    print("  write-config-value <k> <v> config.yaml の指定キーを更新")
    print("  path                       clerk-util 自身のフルパスを出力")
    print()
    print("Process subcommands:")
    print("  poll-command <interval>    .clerk_command を定期チェック")
    print("  start [opts]      clerk-daemon を起動 (exec)")
    print("  stop              clerk-daemon を停止 (SIGTERM)")
    print("  restart [opts]    clerk-daemon を停止→待機→起動 (exec)")
    print("  run-llm <args...>          llm_client を実行 (exec)")
    print()
    print("Setup subcommands:")
    print("  claude-setup [lang]  Claude Code skill として登録 (lang: ja, en, ...)")
    print()
    print(f"Data directory: {DATA_DIR}")


COMMANDS = {
    "read": cmd_read,
    "read-from": cmd_read_from,
    "write": cmd_write,
    "append": cmd_append,
    "lines": cmd_lines,
    "size": cmd_size,
    "mtime": cmd_mtime,
    "exists": cmd_exists,
    "ls": cmd_ls,
    "command": cmd_command,
    "recorder-status": cmd_recorder_status,
    "read-config": cmd_read_config,
    "write-config": cmd_write_config,
    "write-config-value": cmd_write_config_value,
    "path": cmd_path,
    "poll-command": cmd_poll_command,
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "run-llm": cmd_run_llm,
    "claude-setup": cmd_claude_setup,
    "help": cmd_help,
}


def main():
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
