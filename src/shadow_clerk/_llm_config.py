"""shadow-clerk LLM client: 設定・API クライアント"""
from __future__ import annotations
import json
import logging
import os
import subprocess
import sys

from openai import OpenAI

from shadow_clerk import DATA_DIR
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import DEFAULT_CONFIG, GLOSSARY_FILE
from shadow_clerk._daemon_config import load_config, get_translation_provider

logger = logging.getLogger("llm-client")

# --- データディレクトリ ---
ENV_FILE = os.path.join(DATA_DIR, ".env")


def load_dotenv() -> None:
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


def call_claude_cli(
    user_content: str,
    system_prompt: str,
    config: dict,
    *,
    timeout: int = 180,
) -> str:
    """`claude -p` を呼び出してレスポンステキストを返す。

    config から `claude_cli_path` (default: "claude") と `claude_cli_model`
    (default: "haiku") を読み取る。stdout は --output-format json で受け取り、
    `.result` を返す。エラー時は RuntimeError。
    """
    claude_path = config.get("claude_cli_path") or "claude"
    model = config.get("claude_cli_model") or "haiku"
    cmd = [
        claude_path, "-p",
        "--tools", "",
        "--no-session-persistence",
        "--output-format", "json",
        "--model", model,
        "--system-prompt", system_prompt,
    ]
    logger.debug("claude -p invoke: model=%s, system_len=%d, user_len=%d",
                 model, len(system_prompt), len(user_content))
    try:
        proc = subprocess.run(
            cmd, input=user_content, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"claude CLI not found at {claude_path!r}: {e}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"claude -p timed out after {timeout}s") from e
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[:500]
        raise RuntimeError(f"claude -p exited {proc.returncode}: {stderr}")
    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"claude -p output not valid JSON: {proc.stdout[:500]!r}"
        ) from e
    if parsed.get("is_error"):
        err = parsed.get("api_error_status") or parsed.get("result") or "unknown"
        raise RuntimeError(f"claude -p reported error: {err}")
    cost = parsed.get("total_cost_usd")
    if cost is not None:
        logger.info("claude -p: model=%s, cost=$%.4f, duration=%dms",
                    model, cost, parsed.get("duration_ms", 0))
    return parsed.get("result", "") or ""
