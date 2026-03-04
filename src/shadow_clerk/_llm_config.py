"""shadow-clerk LLM client: 設定・API クライアント"""
import logging
import os
import sys

import yaml
from openai import OpenAI

from shadow_clerk import DATA_DIR, CONFIG_FILE
from shadow_clerk.i18n import t

logger = logging.getLogger("llm-client")

# --- データディレクトリ ---
ENV_FILE = os.path.join(DATA_DIR, ".env")
GLOSSARY_FILE = os.path.join(DATA_DIR, "glossary.txt")


def load_dotenv():
    """データディレクトリの .env ファイルから環境変数を読み込む。

    既に設定済みの環境変数は上書きしない。
    """
    if not os.path.exists(ENV_FILE):
        logger.debug(".env ファイルなし: %s", ENV_FILE)
        return
    logger.debug(".env 読み込み: %s", ENV_FILE)
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # クォート除去
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception as e:
        print(t("err.dotenv_load_fail", error=e), file=sys.stderr)


DEFAULT_CONFIG = {
    "translate_language": "ja",
    "auto_translate": False,
    "auto_summary": False,
    "default_language": None,
    "default_model": "small",
    "output_directory": None,
    "llm_provider": "claude",
    "api_endpoint": None,
    "api_model": None,
    "api_key_env": "SHADOW_CLERK_API_KEY",
    "custom_commands": [],
    "initial_prompt": None,
    "voice_command_key": "f23",
    "ui_language": "ja",
    "translation_provider": None,
    "libretranslate_endpoint": None,
    "libretranslate_api_key": None,
    "libretranslate_spell_check": False,
    "spell_check_model": "mbyhphat/t5-japanese-typo-correction",
    "summary_source": "transcript",
}


def load_config() -> dict:
    """config.yaml を読み込む。ファイルがなければデフォルト値を返す。"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_config = yaml.safe_load(f)
            if isinstance(user_config, dict):
                merged = dict(DEFAULT_CONFIG)
                merged.update(user_config)
                return merged
        except Exception as e:
            print(t("err.config_load_fail", error=e), file=sys.stderr)
    return dict(DEFAULT_CONFIG)


def resolve_path(filename: str, config: dict) -> str:
    """ファイル名からフルパスを解決する。

    transcript-*/summary-* → output_directory（設定時）またはデータディレクトリ
    それ以外 → データディレクトリ
    """
    output_dir = DATA_DIR
    out_config = config.get("output_directory")
    if out_config:
        output_dir = os.path.expanduser(out_config)

    if filename.startswith("transcript-") or filename.startswith("summary-"):
        return os.path.join(output_dir, filename)
    return os.path.join(DATA_DIR, filename)


def get_api_client(config: dict) -> tuple[OpenAI, str]:
    """config から OpenAI クライアントとモデル名を生成する。"""
    endpoint = config.get("api_endpoint")
    model = config.get("api_model")

    if not endpoint:
        print(t("err.api_endpoint_missing"), file=sys.stderr)
        print(t("err.api_endpoint_hint"), file=sys.stderr)
        sys.exit(1)

    if not model:
        print(t("err.api_model_missing"), file=sys.stderr)
        print(t("err.api_model_hint"), file=sys.stderr)
        sys.exit(1)

    # API キー取得
    api_key_env = config.get("api_key_env")
    if api_key_env:
        api_key = os.environ.get(api_key_env)
        if not api_key:
            print(t("err.api_key_missing"), file=sys.stderr)
            print(t("err.api_key_hint", dir=DATA_DIR, env_var=api_key_env), file=sys.stderr)
            sys.exit(1)
    else:
        # api_key_env: null の場合（ローカル API 用）ダミーキーを使用
        api_key = "dummy"

    logger.debug("API client: endpoint=%s, model=%s, key=%s...)",
                 endpoint, model, api_key[:8] if len(api_key) > 8 else "***")
    client = OpenAI(base_url=endpoint, api_key=api_key)
    return client, model


def get_translation_provider(config: dict) -> str:
    """翻訳プロバイダーを返す。translation_provider が未設定なら llm_provider にフォールバック。"""
    provider = config.get("translation_provider")
    if provider:
        return provider
    return config.get("llm_provider", "claude")
