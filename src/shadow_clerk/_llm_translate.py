"""shadow-clerk LLM client: 翻訳"""
import argparse
import json
import logging
import os
import re
import sys

from shadow_clerk.i18n import t
from shadow_clerk._llm_config import load_config, get_api_client, get_translation_provider, resolve_path
from shadow_clerk._llm_glossary import load_glossary, MARKER_RE, TIMESTAMP_RE, _seems_target_language

logger = logging.getLogger("llm-client")


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
