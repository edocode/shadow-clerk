#!/usr/bin/env python3
"""shadow-clerk LLM client: OpenAI Compatible API による翻訳・Summary 生成"""
import argparse
import json
import logging
import sys

from openai import OpenAI  # noqa: F401

from shadow_clerk._llm_config import (  # noqa: F401
    load_dotenv, load_config, resolve_path, get_api_client, get_translation_provider,
    ENV_FILE, GLOSSARY_FILE,
)
from shadow_clerk._llm_glossary import (  # noqa: F401
    load_glossary, load_glossary_replacements, load_glossary_for_summary, _seems_target_language,
)
from shadow_clerk._llm_translate import (  # noqa: F401
    _translate_libretranslate, _load_spell_checker, _spell_check, translate,
)
from shadow_clerk._llm_summarize import (  # noqa: F401
    _get_summary_format, summarize, _estimate_tokens, _split_transcript_lines,
    _summarize_full, _summarize_full_single, _summarize_update, _summarize_update_single,
)
from shadow_clerk.i18n import t

logger = logging.getLogger("llm-client")


# --- query サブコマンド ---


def query(args: argparse.Namespace):
    """LLM に自由形式のクエリを投げて結果を stdout に出力する。"""
    config = load_config()
    client, model = get_api_client(config)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": t("llm.query_system")},
            {"role": "user", "content": args.prompt},
        ],
        temperature=0.7,
    )

    answer = response.choices[0].message.content
    if answer:
        print(answer.strip())


# --- match-command サブコマンド ---


def match_command(args: argparse.Namespace):
    """stdin から JSON を読み取り、音声テキストに最も近いコマンドを LLM で推測する。"""
    config = load_config()
    client, model = get_api_client(config)

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"command": "", "confidence": 0}))
        logger.error("JSON パースエラー: %s", e)
        return

    text = payload.get("text", "")
    commands = payload.get("commands", [])

    if not text or not commands:
        print(json.dumps({"command": "", "confidence": 0}))
        return

    commands_desc = "\n".join(f"- {c}" for c in commands)

    system_prompt = t("llm.match_command_system", commands=commands_desc)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        temperature=0.1,
    )

    raw_content = response.choices[0].message.content or ""
    logger.debug("match-command: API response: %r", raw_content)

    # JSON 抽出（コードブロック対応）
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Remove first and last ``` lines
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines).strip()

    try:
        result = json.loads(cleaned)
        # command と confidence を保証
        output = {
            "command": result.get("command", ""),
            "confidence": int(result.get("confidence", 0)),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("match-command: JSON パース失敗: %r", cleaned)
        output = {"command": "", "confidence": 0}

    print(json.dumps(output, ensure_ascii=False))


# --- spell-check サブコマンド ---


def spell_check_cmd(args: argparse.Namespace):
    """stdin からテキストを読み取り、誤字訂正して stdout に出力する。"""
    config = load_config()
    model_name = config.get("spell_check_model", "mbyhphat/t5-japanese-typo-correction")
    text = sys.stdin.read().strip()
    if not text:
        print("")
        return
    results = _spell_check([text], model_name)
    print(results[0])


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(
        description="shadow-clerk LLM client: OpenAI Compatible API による翻訳・Summary 生成",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # translate
    translate_parser = subparsers.add_parser(
        "translate", help="transcript を翻訳して stdout に出力"
    )
    translate_parser.add_argument("lang", help="翻訳先言語コード (ja, en, etc.)")
    translate_parser.add_argument(
        "--file", default=None, help="transcript ファイルパス（省略時は stdin）"
    )
    translate_parser.add_argument(
        "--offset", default=None, help="ファイル読み込み開始バイトオフセット"
    )
    translate_parser.add_argument(
        "--max-bytes", default=None, help="読み込み最大バイト数"
    )

    # query
    query_parser = subparsers.add_parser(
        "query", help="LLM に自由形式のクエリを投げて回答を取得"
    )
    query_parser.add_argument("prompt", help="クエリ文字列")

    # match-command
    subparsers.add_parser(
        "match-command", help="音声テキストからコマンドを推測（stdin から JSON を読み取り）"
    )

    # summarize
    summarize_parser = subparsers.add_parser(
        "summarize", help="transcript から議事録を生成"
    )
    summarize_parser.add_argument(
        "--mode",
        required=True,
        choices=["full", "update"],
        help="生成モード: full=全文から生成, update=差分更新",
    )
    summarize_parser.add_argument(
        "--file", required=True, help="transcript ファイルパス"
    )
    summarize_parser.add_argument(
        "--output", default=None, help="出力先ファイルパス（省略時は stdout のみ）"
    )
    summarize_parser.add_argument(
        "--existing", default=None, help="既存の summary ファイルパス (update モード用)"
    )

    # spell-check
    subparsers.add_parser(
        "spell-check", help="stdin のテキストを誤字訂正して stdout に出力"
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="デバッグログを stderr に出力"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="[%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    from shadow_clerk import i18n as _i18n
    _i18n.init()

    load_dotenv()

    if args.command == "translate":
        translate(args)
    elif args.command == "query":
        query(args)
    elif args.command == "summarize":
        summarize(args)
    elif args.command == "match-command":
        match_command(args)
    elif args.command == "spell-check":
        spell_check_cmd(args)


if __name__ == "__main__":
    main()
