"""shadow-clerk LLM client: サマリー生成"""
import argparse
import logging
import os
import sys

from openai import OpenAI

from shadow_clerk import DATA_DIR
from shadow_clerk.i18n import t
from shadow_clerk._llm_config import load_config, get_api_client, resolve_path
from shadow_clerk._llm_glossary import load_glossary_for_summary

logger = logging.getLogger("llm-client")


def _get_summary_format():
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


def _estimate_tokens(text: str) -> int:
    """テキストのトークン数を概算する（日本語: ~1文字/token, 英語: ~4文字/token）"""
    cjk = sum(1 for c in text if "\u3000" <= c <= "\u9fff" or "\uf900" <= c <= "\ufaff" or "\uff00" <= c <= "\uffef")
    ascii_chars = len(text) - cjk
    return cjk + ascii_chars // 4


def _split_transcript_lines(transcript: str, max_tokens: int) -> list[str]:
    """transcript を行単位でチャンクに分割する。各チャンクが max_tokens 以下になるように。"""
    lines = transcript.split("\n")
    chunks = []
    current_chunk = []
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


def _summarize_full(client: OpenAI, model: str, transcript: str):
    """transcript 全文から議事録を生成する。長い場合はチャンク分割で段階的に要約。"""
    summary_format = _get_summary_format()

    # コンテキスト上限の概算（65536 に対して余裕を持たせる）
    max_context = 45000
    transcript_tokens = _estimate_tokens(transcript)
    overhead = _PROMPT_OVERHEAD_TOKENS + _estimate_tokens(summary_format)

    if transcript_tokens + overhead <= max_context:
        # 1回で処理できる場合
        return _summarize_full_single(client, model, transcript, summary_format)
    else:
        # チャンク分割: 各チャンクを update モードで段階的に要約
        # 既存 summary が蓄積されるため十分なマージンを確保 (8000 tokens)
        chunk_max = max_context - overhead - 8000
        chunks = _split_transcript_lines(transcript, chunk_max)
        logger.info("transcript をチャンク分割: %d チャンク (概算 %d tokens)", len(chunks), transcript_tokens)
        summary = ""
        for i, chunk in enumerate(chunks):
            logger.info("チャンク %d/%d を要約中...", i + 1, len(chunks))
            summary = _summarize_update_single(client, model, chunk, summary, summary_format)
            if not summary:
                return None
        return summary


def _summarize_full_single(client: OpenAI, model: str, transcript: str, summary_format: str):
    """transcript 全文から議事録を生成する（単一リクエスト）。"""
    system_prompt = t("llm.summary_full_system", summary_format=summary_format)
    config = load_config()
    default_lang = config.get("default_language")
    glossary_text = load_glossary_for_summary(default_lang if default_lang != "auto" else None)
    if glossary_text:
        system_prompt += "\n\n" + glossary_text

    user_content = t("llm.summary_full_user", transcript=transcript, summary_format=summary_format)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    result = response.choices[0].message.content
    if not result or len(result.strip()) < 50:
        logger.warning("要約結果が短すぎます (%d文字)、スキップ", len(result.strip()) if result else 0)
        return None
    return result


def _summarize_update(
    client: OpenAI, model: str, transcript: str, existing_summary: str
):
    """既存の summary を踏まえて差分 transcript から議事録を更新する。長い場合はチャンク分割。"""
    summary_format = _get_summary_format()

    max_context = 45000
    transcript_tokens = _estimate_tokens(transcript)
    overhead = _PROMPT_OVERHEAD_TOKENS + _estimate_tokens(summary_format) + _estimate_tokens(existing_summary)

    if transcript_tokens + overhead <= max_context:
        return _summarize_update_single(client, model, transcript, existing_summary, summary_format)
    else:
        # 既存 summary が蓄積されるため十分なマージンを確保 (8000 tokens)
        chunk_max = max_context - _PROMPT_OVERHEAD_TOKENS - _estimate_tokens(summary_format) - 8000
        chunks = _split_transcript_lines(transcript, chunk_max)
        logger.info("差分 transcript をチャンク分割: %d チャンク (概算 %d tokens)", len(chunks), transcript_tokens)
        summary = existing_summary
        for i, chunk in enumerate(chunks):
            logger.info("チャンク %d/%d を要約中...", i + 1, len(chunks))
            summary = _summarize_update_single(client, model, chunk, summary, summary_format)
            if not summary:
                return None
        return summary


def _summarize_update_single(
    client: OpenAI, model: str, transcript: str, existing_summary: str, summary_format: str
):
    """既存の summary を踏まえて差分 transcript から議事録を更新する（単一リクエスト）。"""
    system_prompt = t("llm.summary_update_system", summary_format=summary_format)
    config = load_config()
    default_lang = config.get("default_language")
    glossary_text = load_glossary_for_summary(default_lang if default_lang != "auto" else None)
    if glossary_text:
        system_prompt += "\n\n" + glossary_text

    existing = existing_summary if existing_summary else t("llm.summary_update_none")
    user_content = t("llm.summary_update_user", existing=existing, transcript=transcript, summary_format=summary_format)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    result = response.choices[0].message.content
    if not result or len(result.strip()) < 50:
        logger.warning("要約結果が短すぎます (%d文字)、スキップ", len(result.strip()) if result else 0)
        return None
    return result
