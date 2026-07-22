"""Minimal i18n for shadow-clerk (ja/en)."""

import os

import yaml

from shadow_clerk import CONFIG_FILE
from shadow_clerk._i18n_ja import STRINGS_JA
from shadow_clerk._i18n_en import STRINGS_EN

_current_lang = "ja"


def init(lang: str | None = None) -> None:
    """config.yaml から ui_language を読み、設定する。lang 引数で上書き可能。"""
    global _current_lang
    if lang:
        _current_lang = lang
        return
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            if isinstance(cfg, dict) and cfg.get("ui_language"):
                _current_lang = cfg["ui_language"]
    except Exception:
        pass


def get_lang() -> str:
    return _current_lang


def t(key: str, **kwargs) -> str:
    """翻訳文字列を返す。フォールバック: current_lang → en → ja → key"""
    s = STRINGS.get(_current_lang, {}).get(key)
    if s is None:
        s = STRINGS.get("en", {}).get(key)
    if s is None:
        s = STRINGS.get("ja", {}).get(key)
    if s is None:
        return key
    if kwargs:
        return s.format(**kwargs)
    return s


def nt(key: str, **kwargs) -> str:
    """常に英語文字列を返す（LLMプロンプト用・locale非依存）。フォールバック: en → ja → key"""
    s = STRINGS.get("en", {}).get(key)
    if s is None:
        s = STRINGS.get("ja", {}).get(key)
    if s is None:
        return key
    if kwargs:
        return s.format(**kwargs)
    return s


def t_all() -> dict:
    """現在言語の全文字列 dict を返す（dashboard JS 注入用）"""
    merged = {}
    merged.update(STRINGS.get("ja", {}))
    merged.update(STRINGS.get("en", {}))
    merged.update(STRINGS.get(_current_lang, {}))
    return merged


STRINGS = {
    "ja": STRINGS_JA,
    "en": STRINGS_EN,
}
