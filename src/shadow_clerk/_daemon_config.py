"""Shadow-clerk daemon: 設定管理"""

import logging
import os
import yaml
from shadow_clerk import CONFIG_FILE
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import DEFAULT_CONFIG

logger = logging.getLogger("shadow-clerk")

_config_cache: dict | None = None
_config_mtime: float = 0.0


def load_config() -> dict:
    """config.yaml を読み込む。ファイルがなければデフォルト値を返す。

    mtime ベースのキャッシュにより、ファイルが変更されていなければ再パースしない。
    """
    global _config_cache, _config_mtime
    try:
        st = os.stat(CONFIG_FILE)
    except OSError:
        return dict(DEFAULT_CONFIG)
    if _config_cache is not None and st.st_mtime == _config_mtime:
        return dict(_config_cache)
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            user_config = yaml.safe_load(f)
        if isinstance(user_config, dict):
            merged = dict(DEFAULT_CONFIG)
            merged.update(user_config)
            _config_cache = merged
            _config_mtime = st.st_mtime
            return dict(merged)
    except Exception as e:
        logger.warning("config.yaml の読み込みに失敗: %s", e)
    return dict(DEFAULT_CONFIG)


def get_translation_provider(config: dict) -> str:
    """翻訳プロバイダーを返す。translation_provider が未設定なら llm_provider にフォールバック。"""
    provider = config.get("translation_provider")
    if provider:
        return provider
    return config.get("llm_provider", "claude")

def _builtin_command_descs():
    return [
        {"command": "start_meeting", "description": t("vcmd.start_meeting")},
        {"command": "end_meeting", "description": t("vcmd.end_meeting")},
        {"command": "translate_start", "description": t("vcmd.translate_start")},
        {"command": "translate_stop", "description": t("vcmd.translate_stop")},
        {"command": "set_language ja", "description": t("vcmd.set_language_ja")},
        {"command": "set_language en", "description": t("vcmd.set_language_en")},
        {"command": "unset_language", "description": t("vcmd.unset_language")},
    ]
