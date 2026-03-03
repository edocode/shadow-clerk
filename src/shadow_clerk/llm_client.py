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


def _translate_libretranslate(texts: list[str], lang: str, endpoint: str, api_key: str | None) -> list[str]:
    """LibreTranslate API で翻訳する。

    全テキストを改行で結合して一括送信し、レスポンスを改行で分割して返す。
    """
    import urllib.request
    joined = "\n".join(texts)
    payload = {
        "q": joined,
        "source": "auto",
        "target": lang,
        "format": "text",
    }
    if api_key:
        payload["api_key"] = api_key

    data = json.dumps(payload).encode("utf-8")
    url = endpoint.rstrip("/") + "/translate"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    logger.debug("LibreTranslate request: url=%s, %d texts", url, len(texts))
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        translated = result.get("translatedText", "")
        logger.debug("LibreTranslate response: %r", translated[:200])
        lines = translated.split("\n")
        # LibreTranslate bug: 入力に全大文字英単語(AI等)があると出力全体が大文字になる
        # 各文の先頭を大文字にし、それ以外を小文字にする（title case ではなく sentence case）
        fixed = []
        for line in lines:
            if line and len(line) > 3 and line == line.upper() and line != line.lower():
                import re as _re
                line = line.lower()
                line = _re.sub(r'(^|[.!?]\s+)([a-z])', lambda m: m.group(1) + m.group(2).upper(), line)
                # "i " / "i'" を "I " / "I'" に修正
                line = _re.sub(r"\bi\b(?=['\s])", "I", line)
                logger.debug("LibreTranslate uppercase fix: %r", line[:80])
            fixed.append(line)
        return fixed
    except Exception as e:
        logger.error("LibreTranslate error: %s", e)
        return texts  # フォールバック: 原文をそのまま返す


# --- spell check (transformers) ---

_spell_checker_cache: dict[str, tuple] = {}  # model_name -> (tokenizer, model)


def _load_spell_checker(model_name: str):
    """transformers モデルをロードしてキャッシュする。"""
    if model_name in _spell_checker_cache:
        return _spell_checker_cache[model_name]
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        logger.info("spell-check モデルロード中: %s", model_name)
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForSeq2SeqLM.from_pretrained(model_name)
        _spell_checker_cache[model_name] = (tokenizer, model)
        logger.info("spell-check モデルロード完了: %s", model_name)
        return tokenizer, model
    except Exception as e:
        logger.error("spell-check モデルロード失敗: %s: %s", model_name, e)
        return None, None


def _spell_check(texts: list[str], model_name: str) -> list[str]:
    """transformers の Seq2Seq モデルで誤字訂正を行う。"""
    tokenizer, model = _load_spell_checker(model_name)
    if tokenizer is None or model is None:
        return texts

    results = []
    for text in texts:
        if not text.strip():
            results.append(text)
            continue
        try:
            inputs = tokenizer(text, return_tensors="pt", max_length=512, truncation=True)
            outputs = model.generate(
                **inputs,
                max_length=512,
                num_beams=4,
                early_stopping=True,
            )
            corrected = tokenizer.decode(outputs[0], skip_special_tokens=True)
            if corrected != text:
                logger.debug("spell-check: %r → %r", text, corrected)
            results.append(corrected)
        except Exception as e:
            logger.debug("spell-check error for %r: %s", text[:50], e)
            results.append(text)
    return results


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

    # ヘッダー解析: 言語列以外の特殊列（note, reading）を識別
    headers = [h.strip() for h in data_lines[0].split("\t")]
    special_cols = {"note", "reading"}
    lang_cols = []
    meta_indices = {}  # {"note": idx, "reading": idx}
    for i, h in enumerate(headers):
        if h.lower() in special_cols:
            meta_indices[h.lower()] = i
        else:
            lang_cols.append((i, h))

    # 翻訳先言語の列インデックスを特定
    target_idx = None
    for i, lc in lang_cols:
        if lc == lang:
            target_idx = i
            break
    if target_idx is None:
        return ""

    # 他の言語列を「原文」、lang 列を「翻訳先」としてペアを作成
    note_idx = meta_indices.get("note")
    reading_idx = meta_indices.get("reading")
    pairs = []
    for row_line in data_lines[1:]:
        cols = row_line.split("\t")
        target_term = cols[target_idx].strip() if target_idx < len(cols) else ""
        if not target_term:
            continue
        note = cols[note_idx].strip() if note_idx is not None and note_idx < len(cols) else ""
        reading = cols[reading_idx].strip() if reading_idx is not None and reading_idx < len(cols) else ""
        for col_idx, lc in lang_cols:
            if col_idx == target_idx:
                continue
            source_term = cols[col_idx].strip() if col_idx < len(cols) else ""
            if not source_term:
                continue
            entry = f"{source_term} → {target_term}"
            annotations = []
            if reading:
                annotations.append(f"読み: {reading}")
            if note:
                annotations.append(note)
            if annotations:
                entry += f" ({', '.join(annotations)})"
            pairs.append(entry)

    if not pairs:
        return ""

    return "5. 以下の用語集を参考にしてください:\n" + "\n".join(f"  {p}" for p in pairs)


def load_glossary_readings() -> list[str]:
    """glossary.txt から reading 列の値を返す（Whisper initial_prompt 用）。

    各行の用語名と reading を返す。reading がない行はスキップ。
    """
    if not os.path.exists(GLOSSARY_FILE):
        return []
    try:
        with open(GLOSSARY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []

    data_lines = [l.rstrip("\n") for l in lines if l.strip() and not l.strip().startswith("#")]
    if not data_lines:
        return []

    headers = [h.strip() for h in data_lines[0].split("\t")]
    reading_idx = None
    for i, h in enumerate(headers):
        if h.lower() == "reading":
            reading_idx = i
            break
    if reading_idx is None:
        return []

    # 全言語列の用語 + reading を収集
    results = []
    for row_line in data_lines[1:]:
        cols = row_line.split("\t")
        reading = cols[reading_idx].strip() if reading_idx < len(cols) else ""
        if not reading:
            continue
        # 各言語列の用語も追加（Whisper が認識できるように）
        for i, h in enumerate(headers):
            if h.lower() in ("note", "reading"):
                continue
            term = cols[i].strip() if i < len(cols) else ""
            if term and term not in results:
                results.append(term)
        if reading not in results:
            results.append(reading)
    return results


MARKER_RE = re.compile(r"^---\s+.+\s+---$")
TIMESTAMP_RE = re.compile(
    r"^(\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]\s*\[[^\]]+\])\s*(.*)$"
)


def _seems_target_language(text: str, lang: str) -> bool:
    """テキストが対象言語らしいか簡易判定（未翻訳フォールバック防止用）"""
    if not text.strip():
        return True
    has_cjk = any("\u3000" <= c <= "\u9fff" or "\uff00" <= c <= "\uffef" for c in text)
    if lang in ("ja", "zh"):
        return has_cjk
    if lang in ("en", "de", "fr", "es", "pt", "it"):
        return not has_cjk
    return True


def translate(args: argparse.Namespace):
    """transcript を翻訳して stdout に出力する。"""
    config = load_config()
    provider = get_translation_provider(config)
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
            max_bytes = int(args.max_bytes) if getattr(args, "max_bytes", None) else None
            with open(file_path, "rb") as f:
                if offset:
                    f.seek(offset)
                raw = f.read(max_bytes) if max_bytes else f.read()
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

    if provider == "libretranslate":
        # LibreTranslate: 直接翻訳（オプションで誤字訂正）
        endpoint = config.get("libretranslate_endpoint")
        if not endpoint:
            print("Error: libretranslate_endpoint is not configured.", file=sys.stderr)
            sys.exit(1)
        api_key = config.get("libretranslate_api_key")
        texts = [text for _, text in translatable]

        # spell check（有効時）
        if config.get("libretranslate_spell_check"):
            spell_model = config.get("spell_check_model", "mbyhphat/t5-japanese-typo-correction")
            logger.debug("spell-check enabled: model=%s, %d texts", spell_model, len(texts))
            texts = _spell_check(texts, spell_model)

        translated_list = _translate_libretranslate(texts, lang, endpoint, api_key)

        # 翻訳結果が不足していればリトライ
        if len(translated_list) < len(texts):
            missing_texts = texts[len(translated_list):]
            logger.info("translate: libretranslate %d/%d missing, retrying", len(missing_texts), len(texts))
            try:
                retry_list = _translate_libretranslate(missing_texts, lang, endpoint, api_key)
                translated_list.extend(retry_list)
            except Exception as e:
                logger.warning("translate: libretranslate retry failed: %s", e)

        # 出力を組み立て
        translate_idx = 0
        for i, prefix, text in line_map:
            if prefix is None:
                print(text)
            else:
                if translate_idx < len(translated_list):
                    translated = translated_list[translate_idx]
                else:
                    translated = text  # リトライでも不足 — 元テキスト維持
                if prefix:
                    print(f"{prefix} {translated}")
                else:
                    print(translated)
                translate_idx += 1


    else:
        # api (OpenAI compatible) provider
        client, model = get_api_client(config)

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

        # 未翻訳行をリトライ
        missing = [idx for idx in range(len(translatable)) if idx not in translated_map]
        if missing:
            logger.info("translate: %d/%d lines missing, retrying", len(missing), len(translatable))
            retry_numbered = "\n".join(
                f"{idx}: {translatable[idx][1]}" for idx in missing
            )
            try:
                retry_resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": retry_numbered},
                    ],
                    temperature=0.3,
                )
                retry_raw = retry_resp.choices[0].message.content
                if retry_raw:
                    for rline in retry_raw.strip().splitlines():
                        rline = rline.strip()
                        if not rline:
                            continue
                        rm = re.match(r"^(\d+):\s*(.*)$", rline)
                        if rm:
                            translated_map[int(rm.group(1))] = rm.group(2)
                logger.info("translate: after retry %d/%d translated",
                            len(translated_map), len(translatable))
            except Exception as e:
                logger.warning("translate: retry failed: %s", e)

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
