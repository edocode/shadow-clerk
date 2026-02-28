#!/usr/bin/env python3
"""shadow-clerk LLM client: OpenAI Compatible API による翻訳・Summary 生成"""

import argparse
import json
import logging
import os
import re
import sys

import yaml
from openai import OpenAI

from i18n import t

logger = logging.getLogger("llm-client")

# --- データディレクトリ ---
DATA_DIR = os.path.expanduser("~/.claude/skills/shadow-clerk/data")
CONFIG_FILE = os.path.join(DATA_DIR, "config.yaml")
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


# --- translate サブコマンド ---

def load_glossary(lang: str) -> str:
    """glossary.txt を読み込み、翻訳先言語 lang に対する用語集テキストを返す。

    ファイルが存在しない/空/対象言語がヘッダーにない場合は空文字列を返す。
    """
    if not os.path.exists(GLOSSARY_FILE):
        return ""
    try:
        with open(GLOSSARY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return ""

    # 空行・コメント行を除外
    data_lines = [l.rstrip("\n") for l in lines if l.strip() and not l.strip().startswith("#")]
    if not data_lines:
        return ""

    # ヘッダー解析
    headers = data_lines[0].split("\t")
    has_note = headers[-1].strip().lower() == "note"
    lang_cols = [h.strip() for h in headers]
    if has_note:
        lang_cols = lang_cols[:-1]

    # 翻訳先言語の列インデックスを特定
    try:
        target_idx = lang_cols.index(lang)
    except ValueError:
        return ""

    # 他の言語列を「原文」、lang 列を「翻訳先」としてペアを作成
    note_idx = len(headers) - 1 if has_note else None
    pairs = []
    for row_line in data_lines[1:]:
        cols = row_line.split("\t")
        target_term = cols[target_idx].strip() if target_idx < len(cols) else ""
        if not target_term:
            continue
        note = cols[note_idx].strip() if note_idx is not None and note_idx < len(cols) else ""
        for i, lc in enumerate(lang_cols):
            if i == target_idx:
                continue
            source_term = cols[i].strip() if i < len(cols) else ""
            if not source_term:
                continue
            entry = f"{source_term} → {target_term}"
            if note:
                entry += f" ({note})"
            pairs.append(entry)

    if not pairs:
        return ""

    return "5. 以下の用語集を参考にしてください:\n" + "\n".join(f"  {p}" for p in pairs)


MARKER_RE = re.compile(r"^---\s+.+\s+---$")
TIMESTAMP_RE = re.compile(
    r"^(\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*\[[^\]]+\])\s*(.*)$"
)


def translate(args: argparse.Namespace):
    """transcript を翻訳して stdout に出力する。"""
    config = load_config()
    client, model = get_api_client(config)
    lang = args.lang

    # --file 指定時はファイルから読む（--offset 対応）、なければ stdin
    if args.file:
        file_path = args.file
        file_path = os.path.expanduser(file_path)
        if not os.path.isabs(file_path):
            file_path = resolve_path(file_path, config)
        offset = int(args.offset) if args.offset else 0
        logger.debug("translate: file=%s, offset=%d", file_path, offset)
        logger.debug("translate: file exists=%s", os.path.exists(file_path))
        if os.path.exists(file_path):
            logger.debug("translate: file size=%d", os.path.getsize(file_path))
        try:
            file_size = os.path.getsize(file_path)
            if offset > file_size:
                logger.warning("translate: offset(%d) > file size(%d), reading from beginning",
                               offset, file_size)
                offset = 0
            # バイトオフセットなので rb で開いてデコード
            with open(file_path, "rb") as f:
                if offset:
                    f.seek(offset)
                raw = f.read()
            lines = raw.decode("utf-8", errors="replace")
        except FileNotFoundError:
            print(t("err.file_not_found", path=file_path), file=sys.stderr)
            sys.exit(1)
    else:
        logger.debug("translate: reading from stdin")
        lines = sys.stdin.read()

    logger.debug("translate: input %d bytes, %d lines",
                 len(lines), len(lines.splitlines()))
    if not lines.strip():
        logger.debug("translate: input is empty, returning")
        return

    # 行をパースして翻訳対象を特定
    input_lines = lines.splitlines()
    translatable = []
    line_map = []  # (index, prefix, text) or (index, None, original_line)

    for i, line in enumerate(input_lines):
        stripped = line.strip()
        if not stripped:
            line_map.append((i, None, ""))
            continue
        if MARKER_RE.match(stripped):
            line_map.append((i, None, stripped))
            continue
        m = TIMESTAMP_RE.match(stripped)
        if m:
            prefix, text = m.group(1), m.group(2)
            translatable.append((i, text))
            line_map.append((i, prefix, text))
        else:
            translatable.append((i, stripped))
            line_map.append((i, "", stripped))

    logger.debug("translate: %d translatable lines, %d total lines",
                 len(translatable), len(line_map))
    if not translatable:
        # 翻訳対象なし、そのまま出力
        logger.debug("translate: no translatable lines, passing through")
        print(lines, end="")
        return

    # バッチで翻訳（全テキストをまとめて送信）
    numbered_lines = "\n".join(
        f"{idx}: {text}" for idx, (_, text) in enumerate(translatable)
    )
    logger.debug("translate: API request:\n%s", numbered_lines)

    system_prompt = t("llm.translate_system", lang=lang)

    glossary_section = load_glossary(lang)
    if glossary_section:
        system_prompt += "\n" + glossary_section

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": numbered_lines},
        ],
        temperature=0.3,
    )

    raw_content = response.choices[0].message.content
    logger.debug("translate: API response (raw): %r", raw_content)
    translated_text = raw_content.strip() if raw_content else ""

    if not translated_text:
        logger.warning("translate: API returned empty response")

    # 翻訳結果をパース
    translated_map = {}
    for tline in translated_text.splitlines():
        tline = tline.strip()
        if not tline:
            continue
        m = re.match(r"^(\d+):\s*(.*)$", tline)
        if m:
            translated_map[int(m.group(1))] = m.group(2)
        else:
            logger.debug("translate: unparsed response line: %r", tline)

    logger.debug("translate: parsed %d/%d translations",
                 len(translated_map), len(translatable))

    # 出力を組み立て
    translate_idx = 0
    for i, prefix, text in line_map:
        if prefix is None:
            # マーカー行 or 空行
            print(text)
        else:
            # 翻訳対象行
            translated = translated_map.get(translate_idx, text)
            if prefix:
                print(f"{prefix} {translated}")
            else:
                print(translated)
            translate_idx += 1


# --- summarize サブコマンド ---

def _get_summary_format():
    return t("llm.summary_format")


def summarize(args: argparse.Namespace):
    """transcript から議事録を生成する。"""
    config = load_config()
    client, model = get_api_client(config)

    # transcript ファイルを読む
    transcript_path = os.path.expanduser(args.file)
    if not os.path.isabs(transcript_path):
        transcript_path = resolve_path(transcript_path, config)

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = f.read()
    except FileNotFoundError:
        print(t("err.transcript_not_found", path=transcript_path), file=sys.stderr)
        sys.exit(1)

    if not transcript.strip():
        print(t("err.transcript_empty"), file=sys.stderr)
        sys.exit(1)

    if args.mode == "full":
        result = _summarize_full(client, model, transcript)
    elif args.mode == "update":
        existing_summary = ""
        if args.existing:
            existing_path = os.path.expanduser(args.existing)
            if not os.path.isabs(existing_path):
                existing_path = resolve_path(existing_path, config)
            try:
                with open(existing_path, "r", encoding="utf-8") as f:
                    existing_summary = f.read()
            except FileNotFoundError:
                pass
        result = _summarize_update(client, model, transcript, existing_summary)

    if result:
        if args.output:
            output_path = os.path.expanduser(args.output)
            if not os.path.isabs(output_path):
                output_path = resolve_path(output_path, config)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(result)
            logger.info("summary 保存: %s", output_path)
        print(result)


def _summarize_full(client: OpenAI, model: str, transcript: str):
    """transcript 全文から議事録を生成する。"""
    system_prompt = t("llm.summary_full_system", summary_format=_get_summary_format())

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcript},
        ],
        temperature=0.3,
    )

    return response.choices[0].message.content


def _summarize_update(
    client: OpenAI, model: str, transcript: str, existing_summary: str
):
    """既存の summary を踏まえて差分 transcript から議事録を更新する。"""
    system_prompt = t("llm.summary_update_system", summary_format=_get_summary_format())

    existing = existing_summary if existing_summary else t("llm.summary_update_none")
    user_content = t("llm.summary_update_user", existing=existing, transcript=transcript)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    return response.choices[0].message.content


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

    commands_desc = "\n".join(
        f"- {c['command']}: {c['description']}" for c in commands
    )

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

    parser.add_argument(
        "--verbose", "-v", action="store_true", help="デバッグログを stderr に出力"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="[%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    import i18n as _i18n
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


if __name__ == "__main__":
    main()
