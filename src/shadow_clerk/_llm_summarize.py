"""shadow-clerk LLM client: サマリー生成"""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys

from openai import OpenAI

from shadow_clerk import DATA_DIR
from shadow_clerk.i18n import t, nt
from shadow_clerk._llm_config import load_config, get_api_client, resolve_path, call_claude_cli
from shadow_clerk._llm_glossary import load_glossary_for_summary
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain import Summary

logger = logging.getLogger("llm-client")


def _load_attendees_block(transcript_path: str) -> str:
    """transcript ファイルと同ディレクトリの attendees.json を読み込み、
    プロンプト埋め込み用の参加予定者ブロックを返す。無ければ空文字。"""
    tn = TranscriptName.parse(os.path.basename(transcript_path))
    if tn is None:
        return ""
    path = os.path.join(os.path.dirname(transcript_path), tn.attendees_filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return ""
    attendees = [a for a in (data.get("attendees") or []) if isinstance(a, str) and a.strip()]
    if not attendees:
        return ""
    formatted = "\n".join(f"- {name}" for name in attendees)
    return nt("llm.summary_attendees_block", attendees=formatted) or ""


def _get_hiragana_step(config: dict) -> str:
    """summary_hiragana_step が有効なら平仮名思考ステップのテキストを返す"""
    if config.get("summary_hiragana_step", True):
        return nt("llm.summary_hiragana_step") or ""
    return ""


_LANG_CODE_TO_NAME: dict[str, str] = {
    "ja": "Japanese", "en": "English", "zh": "Chinese", "ko": "Korean",
    "fr": "French", "de": "German", "es": "Spanish", "pt": "Portuguese", "ru": "Russian",
}


def _resolve_summary_language(config: dict) -> str:
    """summary_language 設定を解決する。未指定なら ui_language にフォールバック。
    プロンプト埋め込み用に言語名（例: "Japanese"）を返す。"""
    code = config.get("summary_language") or config.get("ui_language") or "ja"
    return _LANG_CODE_TO_NAME.get(code, code)


def _get_length_instruction(config: dict) -> str:
    """summary_length 設定に応じた長さ指示テキストを返す"""
    length = config.get("summary_length", "half")
    key = f"llm.summary_length_{length}"
    return t(key) or ""


# summary_length → max_tokens (上限なし方針のため余裕を持たせる)
_LENGTH_MAX_TOKENS: dict[str, int] = {
    "half": 4096,
    "1page": 8192,
    "2pages": 12288,
    "3pages": 16384,
    "4pages": 16384,
    "5pages": 16384,
}


def _get_max_tokens(config: dict) -> int:
    """summary_length に基づく max_tokens を返す"""
    length = config.get("summary_length", "half")
    return _LENGTH_MAX_TOKENS.get(length, 4096)


def _get_summary_format() -> str:
    """summary_template.md があればそちらを優先、なければ i18n デフォルトを使用"""
    template_path = os.path.join(DATA_DIR, "summary_template.md")
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                logger.debug("summary_template.md を使用: %s", template_path)
                return content
    except FileNotFoundError:
        pass
    return nt("llm.summary_format")


def summarize(args: argparse.Namespace) -> None:
    """transcript から議事録を生成する。"""
    config = load_config()
    provider = config.get("llm_provider") or "claude"
    if provider == "claude":
        client, model = None, config.get("claude_cli_model") or "haiku"
        logger.info("要約開始: provider=claude (cli_model=%s), mode=%s", model, args.mode)
    else:
        client, model = get_api_client(config)
        logger.info("要約開始: provider=api (model=%s), mode=%s", model, args.mode)

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

    attendees_block = _load_attendees_block(transcript_path)
    if attendees_block:
        logger.info("参加予定者情報を読み込み（プロンプトに付与）")

    if args.mode == "full":
        result = _summarize_full(client, model, transcript, attendees_block, provider=provider)
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
        result = _summarize_update(client, model, transcript, existing_summary, attendees_block, provider=provider)

    if not result:
        # rc=0 で終了すると呼び出し側（自動要約）が成功と誤認して完了通知を出すため、
        # LLM 失敗・応答不足は異常終了で伝える
        print(t("err.summary_failed"), file=sys.stderr)
        sys.exit(1)

    # Summary バリューオブジェクトとして扱う
    tn = TranscriptName.parse(os.path.basename(transcript_path))
    summary = Summary(transcript_name=tn, content=result) if tn else None

    if args.output:
        output_path = os.path.expanduser(args.output)
        if not os.path.isabs(output_path):
            output_path = resolve_path(output_path, config)
    elif summary:
        # args.output 未指定かつ TranscriptName をパースできた場合は
        # transcript と同ディレクトリに summary ファイルを自動生成
        output_path = summary.file_path(os.path.dirname(transcript_path))
    else:
        output_path = None

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result)
        logger.info("summary 保存: %s", output_path)
    print(result)


def _estimate_tokens(text: str) -> int:
    """テキストのトークン数を概算する（日本語: ~1文字/token, 英語: ~4文字/token）"""
    cjk = sum(1 for c in text if "\u3000" <= c <= "\u9fff" or "\uf900" <= c <= "\ufaff" or "\uff00" <= c <= "\uffef")
    ascii_chars = len(text) - cjk
    return cjk + ascii_chars // 4


def _split_transcript_lines(transcript: str, max_tokens: int) -> list[str]:
    """transcript を行単位でチャンクに分割する。各チャンクが max_tokens 以下になるように。"""
    lines = transcript.split("\n")
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_tokens = 0

    for line in lines:
        line_tokens = _estimate_tokens(line)
        if current_chunk and current_tokens + line_tokens > max_tokens:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_tokens = 0
        current_chunk.append(line)
        current_tokens += line_tokens

    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


# プロンプト部分のトークン概算（system + template + フォーマット指示）
_PROMPT_OVERHEAD_TOKENS = 2000


def _summarize_full(
    client: OpenAI | None, model: str, transcript: str, attendees_block: str = "",
    *, provider: str = "api",
) -> str | None:
    """transcript 全文から議事録を生成する。長い場合はチャンク分割で段階的に要約。"""
    summary_format = _get_summary_format()

    # コンテキスト上限の概算（65536 に対して余裕を持たせる）
    max_context = 45000
    transcript_tokens = _estimate_tokens(transcript)
    overhead = _PROMPT_OVERHEAD_TOKENS + _estimate_tokens(summary_format) + _estimate_tokens(attendees_block)

    if transcript_tokens + overhead <= max_context:
        # 1回で処理できる場合
        return _summarize_full_single(client, model, transcript, summary_format, attendees_block, provider=provider)
    else:
        # チャンク分割: 各チャンクを update モードで段階的に要約
        # 既存 summary が蓄積されるため十分なマージンを確保 (8000 tokens)
        chunk_max = max_context - overhead - 8000
        chunks = _split_transcript_lines(transcript, chunk_max)
        logger.info("transcript をチャンク分割: %d チャンク (概算 %d tokens)", len(chunks), transcript_tokens)
        summary = ""
        for i, chunk in enumerate(chunks):
            logger.info("チャンク %d/%d を要約中...", i + 1, len(chunks))
            summary = _summarize_update_single(client, model, chunk, summary, summary_format, attendees_block, provider=provider)
            if not summary:
                return None
        return summary


def _summarize_full_single(
    client: OpenAI | None, model: str, transcript: str, summary_format: str,
    attendees_block: str = "", *, provider: str = "api",
) -> str | None:
    """transcript 全文から議事録を生成する（単一リクエスト）。"""
    config = load_config()
    length_instruction = _get_length_instruction(config)
    max_tokens = _get_max_tokens(config)
    summary_language = _resolve_summary_language(config)
    system_prompt = nt("llm.summary_full_system", summary_format=summary_format,
                      length_instruction=length_instruction)
    default_lang = config.get("default_language")
    glossary_text = load_glossary_for_summary(default_lang if default_lang != "auto" else None)
    if glossary_text:
        system_prompt += "\n\n" + glossary_text

    hiragana_step = _get_hiragana_step(config)
    user_content = nt("llm.summary_full_user", transcript=transcript,
                     summary_format=summary_format, hiragana_step=hiragana_step,
                     length_instruction=length_instruction,
                     summary_language=summary_language,
                     attendees_block=attendees_block)

    if provider == "claude":
        try:
            result = call_claude_cli(user_content, system_prompt, config)
        except RuntimeError as e:
            logger.error("summarize: claude call failed: %s", e)
            return None
    else:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        result = response.choices[0].message.content

    if not result or len(result.strip()) < 50:
        logger.warning("要約結果が短すぎます (%d文字)、スキップ", len(result.strip()) if result else 0)
        return None
    return result


def _summarize_update(
    client: OpenAI | None, model: str, transcript: str, existing_summary: str,
    attendees_block: str = "", *, provider: str = "api",
) -> str | None:
    """既存の summary を踏まえて差分 transcript から議事録を更新する。長い場合はチャンク分割。"""
    summary_format = _get_summary_format()

    max_context = 45000
    transcript_tokens = _estimate_tokens(transcript)
    overhead = (
        _PROMPT_OVERHEAD_TOKENS
        + _estimate_tokens(summary_format)
        + _estimate_tokens(existing_summary)
        + _estimate_tokens(attendees_block)
    )

    if transcript_tokens + overhead <= max_context:
        return _summarize_update_single(client, model, transcript, existing_summary, summary_format, attendees_block, provider=provider)
    else:
        # 既存 summary が蓄積されるため十分なマージンを確保 (8000 tokens)
        chunk_max = (
            max_context
            - _PROMPT_OVERHEAD_TOKENS
            - _estimate_tokens(summary_format)
            - _estimate_tokens(attendees_block)
            - 8000
        )
        chunks = _split_transcript_lines(transcript, chunk_max)
        logger.info("差分 transcript をチャンク分割: %d チャンク (概算 %d tokens)", len(chunks), transcript_tokens)
        summary = existing_summary
        for i, chunk in enumerate(chunks):
            logger.info("チャンク %d/%d を要約中...", i + 1, len(chunks))
            summary = _summarize_update_single(client, model, chunk, summary, summary_format, attendees_block, provider=provider)
            if not summary:
                return None
        return summary


def _summarize_update_single(
    client: OpenAI | None, model: str, transcript: str, existing_summary: str,
    summary_format: str, attendees_block: str = "", *, provider: str = "api",
) -> str | None:
    """既存の summary を踏まえて差分 transcript から議事録を更新する（単一リクエスト）。"""
    config = load_config()
    length_instruction = _get_length_instruction(config)
    max_tokens = _get_max_tokens(config)
    summary_language = _resolve_summary_language(config)
    system_prompt = nt("llm.summary_update_system", summary_format=summary_format,
                      length_instruction=length_instruction)
    default_lang = config.get("default_language")
    glossary_text = load_glossary_for_summary(default_lang if default_lang != "auto" else None)
    if glossary_text:
        system_prompt += "\n\n" + glossary_text

    hiragana_step = _get_hiragana_step(config)
    existing = existing_summary if existing_summary else nt("llm.summary_update_none")
    user_content = nt("llm.summary_update_user", existing=existing, transcript=transcript,
                     summary_format=summary_format, hiragana_step=hiragana_step,
                     length_instruction=length_instruction,
                     summary_language=summary_language,
                     attendees_block=attendees_block)

    if provider == "claude":
        try:
            result = call_claude_cli(user_content, system_prompt, config)
        except RuntimeError as e:
            logger.error("summarize: claude call failed: %s", e)
            return None
    else:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        result = response.choices[0].message.content

    if not result or len(result.strip()) < 50:
        logger.warning("要約結果が短すぎます (%d文字)、スキップ", len(result.strip()) if result else 0)
        return None
    return result
