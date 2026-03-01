"""shadow-clerk: Web会議 議事録アシスタント"""

import os

__version__ = "0.2.0"


def get_data_dir() -> str:
    """データディレクトリのパスを返す。

    SHADOW_CLERK_DATA_DIR 環境変数で上書き可能。
    デフォルト: ~/.local/share/shadow-clerk
    """
    return os.environ.get(
        "SHADOW_CLERK_DATA_DIR",
        os.path.expanduser("~/.local/share/shadow-clerk"),
    )


def get_skill_dir() -> str:
    """Claude Code skill ディレクトリのパスを返す。"""
    return os.path.expanduser("~/.claude/skills/shadow-clerk")


DATA_DIR = get_data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, "config.yaml")
