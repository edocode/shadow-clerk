"""shadow-clerk: Web会議 議事録アシスタント"""

import os
import sys

__version__ = "0.2.0"


def get_data_dir() -> str:
    """データディレクトリのパスを返す。

    SHADOW_CLERK_DATA_DIR 環境変数で上書き可能。
    デフォルト:
      - Windows: %APPDATA%\\shadow-clerk
      - Linux/その他: ~/.local/share/shadow-clerk
    """
    if env := os.environ.get("SHADOW_CLERK_DATA_DIR"):
        return env
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, "shadow-clerk")
        return os.path.expanduser("~/AppData/Roaming/shadow-clerk")
    return os.path.expanduser("~/.local/share/shadow-clerk")


def get_skill_dir() -> str:
    """Claude Code skill ディレクトリのパスを返す。"""
    return os.path.expanduser("~/.claude/skills/shadow-clerk")


DATA_DIR = get_data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, "config.yaml")
