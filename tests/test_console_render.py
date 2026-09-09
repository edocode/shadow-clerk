"""grid 差分レンダラの検証

実行: uv run python tests/test_console_render.py
"""
from __future__ import annotations

import pyte

from shadow_clerk._daemon_console_render import render_row, render_rows, style_key

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def feed(text: str, cols: int = 20, lines: int = 5) -> pyte.Screen:
    screen = pyte.Screen(cols, lines)
    pyte.Stream(screen).feed(text)
    return screen


def test_plain_row() -> None:
    screen = feed("hi")
    row = render_row(screen, 0)
    check("素のテキストは1ラン", row == [["hi", "default"]], repr(row))


def test_trailing_blank_trimmed() -> None:
    screen = feed("hi")
    row = render_row(screen, 0)
    joined = "".join(seg[0] for seg in row)
    check("行末の空白を落とす", joined == "hi", repr(joined))


def test_empty_row() -> None:
    screen = feed("hi")
    check("空行は空リスト", render_row(screen, 3) == [], repr(render_row(screen, 3)))


def test_color_runs_split() -> None:
    # 赤で ab、既定で cd
    screen = feed("\x1b[31mab\x1b[0mcd")
    row = render_row(screen, 0)
    check("色の切れ目でランが分かれる", len(row) == 2, repr(row))
    check("最初のランが赤", row[0] == ["ab", "fg:red"], repr(row))
    check("次のランが既定", row[1] == ["cd", "default"], repr(row))


def test_bold_in_style_key() -> None:
    screen = feed("\x1b[1mX")
    check("bold が style に乗る", "bold" in style_key(screen.buffer[0][0]),
          style_key(screen.buffer[0][0]))


def test_render_rows_keys_are_strings() -> None:
    screen = feed("a\r\nb")
    out = render_rows(screen, [0, 1])
    check("キーは行番号の文字列", set(out.keys()) == {"0", "1"}, repr(out))


def test_styled_trailing_whitespace_preserved() -> None:
    # 背景色つき空白だけの行は空リストにならず、色つきランとして残る
    screen = feed("\x1b[41m          \x1b[0m")
    row = render_row(screen, 0)
    check("背景色つきスペースだけの行は消えない", len(row) > 0, repr(row))
    check("背景色がランに含まれる", row[0][1] == "bg:red", repr(row))


def test_styled_trailing_whitespace_after_text() -> None:
    # テキスト + 背景色つきスペースで行末まで埋めた行で、末尾の色つきランが残る
    # 背景色つきスペース10個
    screen = feed("ab" + "\x1b[41m" + " " * 10 + "\x1b[0m", cols=20, lines=5)
    row = render_row(screen, 0)
    check("末尾の背景色つきランが残る", len(row) >= 2, repr(row))
    if len(row) >= 2:
        check("最後のランが赤背景", row[-1][1] == "bg:red", repr(row[-1]))


def test_default_trailing_whitespace_still_trimmed() -> None:
    # 既定スタイルの行末空白は従来どおり落ちる
    screen = feed("hi    ")
    row = render_row(screen, 0)
    joined = "".join(seg[0] for seg in row)
    check("既定スタイルの末尾空白は落ちる", joined == "hi", repr(joined))


def main() -> int:
    test_plain_row()
    test_trailing_blank_trimmed()
    test_empty_row()
    test_color_runs_split()
    test_bold_in_style_key()
    test_render_rows_keys_are_strings()
    test_styled_trailing_whitespace_preserved()
    test_styled_trailing_whitespace_after_text()
    test_default_trailing_whitespace_still_trimmed()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
