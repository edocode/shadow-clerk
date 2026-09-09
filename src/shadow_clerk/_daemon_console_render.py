"""Shadow-clerk daemon: pyte の grid を配信用の差分ペイロードに変換する"""
from __future__ import annotations
from typing import Any, Iterable

# 1行を [[text, style], ...] のランに畳む。1文字ずつ span を作ると
# 120 列 × 更新頻度で DOM もペイロードも膨れるため、同じ属性は必ずまとめる。
_DEFAULT_STYLE = "default"


def style_key(char: Any) -> str:
    """pyte の Char から、同じ見た目の文字をまとめるためのキーを作る"""
    parts: list[str] = []
    if char.fg and char.fg != "default":
        parts.append(f"fg:{char.fg}")
    if char.bg and char.bg != "default":
        parts.append(f"bg:{char.bg}")
    if char.bold:
        parts.append("bold")
    if char.italics:
        parts.append("italic")
    if char.underscore:
        parts.append("underline")
    if char.reverse:
        parts.append("reverse")
    if char.blink:
        # blink は SGR 2 (faint) の写し先。_daemon_console_filter を参照
        parts.append("dim")
    if char.strikethrough:
        parts.append("strike")
    return ",".join(parts) if parts else _DEFAULT_STYLE


def render_row(screen: Any, y: int) -> list[list[str]]:
    """1行を [[text, style], ...] にする。行末の空白は落とす"""
    line = screen.buffer[y]
    runs: list[list[str]] = []
    for x in range(screen.columns):
        char = line[x]
        key = style_key(char)
        if runs and runs[-1][1] == key:
            runs[-1][0] += char.data
        else:
            runs.append([char.data, key])
    # 行末の既定スタイル空白ランだけを落とす
    # 非既定スタイル（背景色など）のランは、空白でも保持する
    while runs and not runs[-1][0].strip() and runs[-1][1] == _DEFAULT_STYLE:
        runs.pop()
    # 最後のランのテキストをトリムするのも、既定スタイルのときだけ
    if runs and runs[-1][1] == _DEFAULT_STYLE:
        runs[-1][0] = runs[-1][0].rstrip()
    return runs


def render_rows(screen: Any, ys: Iterable[int]) -> dict[str, list[list[str]]]:
    """指定した行だけをレンダリングする。キーは行番号の文字列 (JSON 用)"""
    return {str(y): render_row(screen, y) for y in ys if 0 <= y < screen.lines}
