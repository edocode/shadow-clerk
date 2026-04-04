"""shadow-clerk LLM client: 用語集"""
import logging
import os
import re

from shadow_clerk import DATA_DIR
from shadow_clerk._llm_config import GLOSSARY_FILE, load_config, resolve_path

logger = logging.getLogger("llm-client")


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
                annotations.append(f"reading: {reading}")
            if note:
                annotations.append(note)
            if annotations:
                entry += f" ({', '.join(annotations)})"
            pairs.append(entry)

    # reading → target_term のマッピングも追加（同言語翻訳・誤認識修正用）
    # reading と target_term が異なる場合のみ
    # reading はカンマ区切りで複数指定可能。長さ降順でソート（長いreadingを優先）
    reading_pairs_raw = []  # (reading_len, entry)
    if reading_idx is not None:
        for row_line in data_lines[1:]:
            cols = row_line.split("\t")
            target_term = cols[target_idx].strip() if target_idx < len(cols) else ""
            reading_raw = cols[reading_idx].strip() if reading_idx < len(cols) else ""
            if not target_term or not reading_raw:
                continue
            note = cols[note_idx].strip() if note_idx is not None and note_idx < len(cols) else ""
            for reading in [r.strip() for r in reading_raw.split(",") if r.strip()]:
                if reading == target_term:
                    continue
                entry = f"reading「{reading}」→ {target_term}"
                if note:
                    entry += f" ({note})"
                reading_pairs_raw.append((len(reading), entry))
    reading_pairs = [e for _, e in sorted(reading_pairs_raw, key=lambda x: x[0], reverse=True)]

    if not pairs and not reading_pairs:
        return ""

    section = "以下の用語集を参考にしてください:\n"
    if pairs:
        section += "\n".join(f"  {p}" for p in pairs)
    if reading_pairs:
        if pairs:
            section += "\n"
        section += "  音声認識の誤変換を修正する際は、以下のreadingマッピングを上から順に優先的に照合してください:\n"
        section += "\n".join(f"  {p}" for p in reading_pairs)
    return section


def load_glossary_replacements(lang: str | None = None) -> list[tuple[str, str]]:
    """glossary.txt から reading → 言語列の置換ペアを返す（transcription 後のテキスト置換用）。

    lang 指定時: reading → lang列 の置換ペアを返す。
    lang=None (auto): 全言語列について reading → 各言語列 の置換ペアをすべて返す。
    reading が空、または reading と対象列の値が同一の行はスキップ。
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
    special_cols = {"note", "reading"}
    reading_idx = None
    lang_cols = []  # [(col_idx, lang_name), ...]
    for i, h in enumerate(headers):
        if h.lower() == "reading":
            reading_idx = i
        elif h.lower() not in special_cols:
            lang_cols.append((i, h))

    if reading_idx is None:
        return []

    # 対象言語列を決定
    if lang is not None:
        target_cols = [(i, h) for i, h in lang_cols if h == lang]
    else:
        target_cols = lang_cols

    if not target_cols:
        return []

    pairs = []
    for row_line in data_lines[1:]:
        cols = row_line.split("\t")
        reading_raw = cols[reading_idx].strip() if reading_idx < len(cols) else ""
        if not reading_raw:
            continue
        for col_idx, _ in target_cols:
            target_val = cols[col_idx].strip() if col_idx < len(cols) else ""
            if not target_val:
                continue
            # reading はカンマ区切りで複数指定可能
            for reading in [r.strip() for r in reading_raw.split(",") if r.strip()]:
                if target_val == reading:
                    continue
                pairs.append((reading, target_val))

    # reading の長さ降順でソート（長いreadingを先に置換して部分マッチを防ぐ）
    return sorted(pairs, key=lambda x: len(x[0]), reverse=True)


def load_glossary_for_summary(lang: str | None = None) -> str:
    """glossary.txt を読み込み、要約用の用語集テキストを返す。

    lang 指定時: その言語列を主軸にした用語集テキスト。
    lang=None (auto): 全言語列を使った用語集テキスト。
    ファイルが存在しない/空の場合は空文字列を返す。
    """
    if not os.path.exists(GLOSSARY_FILE):
        return ""
    try:
        with open(GLOSSARY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return ""

    data_lines = [l.rstrip("\n") for l in lines if l.strip() and not l.strip().startswith("#")]
    if not data_lines:
        return ""

    headers = [h.strip() for h in data_lines[0].split("\t")]
    special_cols = {"note", "reading"}
    reading_idx = None
    note_idx = None
    lang_cols = []
    for i, h in enumerate(headers):
        hl = h.lower()
        if hl == "reading":
            reading_idx = i
        elif hl == "note":
            note_idx = i
        else:
            lang_cols.append((i, h))

    if lang is not None:
        display_cols = [(i, h) for i, h in lang_cols if h == lang]
        if not display_cols:
            display_cols = lang_cols
    else:
        display_cols = lang_cols

    entries = []
    for row_line in data_lines[1:]:
        cols = row_line.split("\t")
        terms = []
        for col_idx, lc in display_cols:
            val = cols[col_idx].strip() if col_idx < len(cols) else ""
            if val:
                terms.append(val)
        if not terms:
            continue
        reading = cols[reading_idx].strip() if reading_idx is not None and reading_idx < len(cols) else ""
        note = cols[note_idx].strip() if note_idx is not None and note_idx < len(cols) else ""
        entry = " / ".join(terms)
        annotations = []
        if reading:
            annotations.append(reading)
        if note:
            annotations.append(note)
        if annotations:
            entry += f" ({', '.join(annotations)})"
        entries.append(f"- {entry}")

    if not entries:
        return ""

    return "以下の用語集を参考にしてください（正しい表記で出力してください）:\n" + "\n".join(entries)


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
