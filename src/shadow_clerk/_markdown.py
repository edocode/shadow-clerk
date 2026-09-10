"""Shadow-clerk daemon: AI アシスタントの生成物 (Markdown) を HTML に起こす"""
from __future__ import annotations
import logging

from markdown_it import MarkdownIt

logger = logging.getLogger("shadow-clerk")

# 生成物は AI が書いた任意テキストなので、**ソース中の生 HTML を許さない**。
# markdown-it の html オプションを False にすると `<script>` 等は実体参照に
# 落ちるため、別途サニタイザを挟む必要がない。
# image を無効にするのは、生成物に混ざった画像 URL でダッシュボードから外部へ
# 通信させないため（会議の内容を扱う画面なので、意図しない発信を作らない）。
# commonmark プリセットは table を持たない（GFM の拡張のため）。無効のままだと
# テーブルが段落として扱われ、CommonMark が段落内の改行を空白に潰すので
# 「| 時刻 | 発言 | |---|---| | 08:18 | …」のような 1 行に崩れる。実際に起きた。
# gfm-like プリセットは linkify-it-py を要求するので、必要な拡張だけを足す。
_MD = MarkdownIt("commonmark").disable("image").enable(["table", "strikethrough"])
_MD.options["html"] = False


def render_markdown(text: str) -> str:
    """Markdown を HTML にする。失敗しても表示は止めない"""
    if not text:
        return ""
    try:
        return _MD.render(text)
    except Exception as e:  # pylint: disable=broad-except
        logger.warning("Markdown のレンダリングに失敗: %s", e)
        return ""
