"""shadow-clerk: Web会議 議事録アシスタント"""
from __future__ import annotations

import os
import sys

__version__ = "0.2.0"


def is_microsoft_store_python() -> bool:
    """Microsoft Store 版 Python(AppContainer サンドボックスあり)で動作中か判定。"""
    if sys.platform != "win32":
        return False
    exe = (sys.executable or "").replace("\\", "/").lower()
    return (
        "windowsapps/pythonsoftwarefoundation" in exe
        or "/packages/pythonsoftwarefoundation" in exe
    )


def get_data_dir() -> str:
    """データディレクトリのパスを返す。

    SHADOW_CLERK_DATA_DIR 環境変数で上書き可能。
    デフォルト:
      - Windows: %APPDATA%\\shadow-clerk
      - Linux/その他: ~/.local/share/shadow-clerk

    注意: Microsoft Store 版 Python では %APPDATA% が AppContainer
    サンドボックス(`%LOCALAPPDATA%\\Packages\\<pkg-id>\\LocalCache\\Roaming\\`)
    にリダイレクトされるため、Python マイナーバージョンが変わるとデータが
    別パスに移ることになる。uv 管理 Python(`uv python install`)か
    python.org 版 Python を推奨。
    """
    if env := os.environ.get("SHADOW_CLERK_DATA_DIR"):
        return env
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, "shadow-clerk")
        return os.path.expanduser("~/AppData/Roaming/shadow-clerk")
    return os.path.expanduser("~/.local/share/shadow-clerk")


DATA_DIR = get_data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, "config.yaml")
