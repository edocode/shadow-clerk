"""private CSI フィルタの検証

実行: uv run python tests/test_console_csi_filter.py
daemon も PTY も不要。pyte だけを使う。

回帰の元ネタは実際に claude の TUI から PTY 経由で採った列:
  ESC[>4m  … XTMODKEYS。pyte が `>` を読み飛ばして SGR 4 = 下線にする
  ESC[<u   … Kitty keyboard protocol。pyte が `u` を本文として描く
"""
from __future__ import annotations

import pyte

from shadow_clerk._daemon_console_filter import PrivateCsiFilter

results: list[bool] = []
E = "\x1b"


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def run(chunks: list[str], cols: int = 40) -> pyte.Screen:
    """フィルタを通した列を pyte に流し、結果の Screen を返す"""
    screen = pyte.Screen(cols, 4)
    stream = pyte.Stream(screen)
    filt = PrivateCsiFilter()
    for c in chunks:
        stream.feed(filt.feed(c))
    return screen


# --- 元のバグ ---

check("1. ESC[>4m が下線として適用されない",
      run([f"{E}[>4mAB"]).buffer[0][0].underscore is False)

check("2. ESC[>4;2m も同様",
      run([f"{E}[>4;2mAB"]).buffer[0][0].underscore is False)

check("3. ESC[<u の u が本文に落ちない",
      run([f"{E}[<uAB"]).display[0].rstrip() == "AB")

check("4. ESC[=1c も落ちる",
      run([f"{E}[=1cAB"]).display[0].rstrip() == "AB")

# --- 通すべきものを壊さない ---

check("5. 通常の SGR は効く",
      run([f"{E}[4mAB"]).buffer[0][0].underscore is True)

check("6. DEC private mode (?) は通す",
      run([f"{E}[?25lAB"]).display[0].rstrip() == "AB")

check("7. 色つきの文字はそのまま",
      run([f"{E}[33mAB"]).buffer[0][0].fg == "brown")

check("8. カーソル移動は効く",
      run([f"{E}[3GX"]).display[0].rstrip() == "  X")

check("9. OSC 8 のハイパーリンクは素通し",
      run([f"{E}]8;id=x;https://e.example\x07link{E}]8;;\x07"]).display[0].rstrip() == "link")

check("10. ESC 単体のエスケープ (ESC7) を壊さない",
      run([f"{E}7AB{E}8C"]).display[0].rstrip() == "CB")

# --- チャンク境界 ---

for cut in range(1, 6):
    seq = f"{E}[>4mAB"
    s = run([seq[:cut], seq[cut:]])
    check(f"11.{cut} ESC[>4m が {cut} 文字目で割れても落ちる",
          s.buffer[0][0].underscore is False and s.display[0].rstrip() == "AB",
          repr(s.display[0].rstrip()))

check("12. ESC で終わるチャンクを持ち越す",
      run([f"A{E}", "[>4mB"]).buffer[0][0].underscore is False)

check("13. 1文字ずつ流しても結果が同じ",
      run(list(f"{E}[>4mAB")).buffer[0][0].underscore is False)

# --- 異常系 ---

check("14. 終端が来ない長い列は素通しして詰まらせない",
      run([f"{E}[>" + "1" * 80]).display[0] is not None)

filt = PrivateCsiFilter()
filt.feed(f"A{E}[>")
filt.reset()
check("15. reset() で持ち越しを捨てる", filt.feed("B") == "B")

check("16. ESC を含まない文字列は素通し",
      PrivateCsiFilter().feed("hello") == "hello")

# --- 実測した起動時の列（抜粋） ---

real = (f"{E}[>4m{E}[<u{E}[?1004l{E}[?2031l{E}[?2004l{E}[?25h"
        f"{E}[93m───{E}[39m")
s = run([real])
check("17. 実測列で下線が付かない", s.buffer[0][0].underscore is False)
check("18. 実測列で罫線だけが残る", s.display[0].rstrip() == "───",
      repr(s.display[0].rstrip()))

# claude の TUI は ESC[0m を使わず 39/22/49 の個別リセットで戻すため、
# 起動時の ESC[>4;2m で入った下線はセッション中ずっと解除されない
startup = f"{E}[>4;2m"
body = f"{E}[33mwarn{E}[39m{E}[1mbold{E}[22m plain"
s_raw = pyte.Screen(40, 4)
pyte.Stream(s_raw).feed(startup + body)
check("19. フィルタ無しなら本文全体が下線になる（回帰の再現）",
      all(s_raw.buffer[0][x].underscore for x in range(len("warnbold plain"))))
s_ok = run([startup + body])
check("20. フィルタありなら本文に下線が付かない",
      not any(s_ok.buffer[0][x].underscore for x in range(40)))
check("21. 色・太字はフィルタ後も残る",
      s_ok.buffer[0][0].fg == "brown" and s_ok.buffer[0][4].bold is True)

# --- SGR 2 (faint) ---
# pyte の属性表に 2 は無く、そのまま渡すと候補テキストが通常の入力と
# 同じ濃さで描かれる

from shadow_clerk._daemon_console_filter import rewrite_sgr  # noqa: E402

check("22. 単独の 2 は写し先へ", rewrite_sgr("2") == "5", rewrite_sgr("2"))
check("23. 22 は写し先の解除も足す", rewrite_sgr("22") == "22;25", rewrite_sgr("22"))
check("24. 24bit 色の 2 は触らない",
      rewrite_sgr("38;2;10;20;30") == "38;2;10;20;30", rewrite_sgr("38;2;10;20;30"))
check("25. 256色の 5 も触らない", rewrite_sgr("48;5;2") == "48;5;2", rewrite_sgr("48;5;2"))
check("26. 色の後ろに続く 2 は写す",
      rewrite_sgr("38;2;1;2;3;2") == "38;2;1;2;3;5", rewrite_sgr("38;2;1;2;3;2"))
check("27. 空のパラメータはそのまま", rewrite_sgr("") == "")
check("28. 関係ない値は変えない", rewrite_sgr("1;31;4") == "1;31;4", rewrite_sgr("1;31;4"))

s_dim = run([f"{E}[2mghost{E}[22m plain"])
check("29. faint が属性として残る", s_dim.buffer[0][0].blink is True)
check("30. 22 で faint が解除される", s_dim.buffer[0][len("ghost")+1].blink is False)
check("31. 本文は壊れない", s_dim.display[0].rstrip() == "ghost plain",
      repr(s_dim.display[0].rstrip()))

s_col = run([f"{E}[38;2;255;136;0mX"])
check("32. 24bit 色は色のまま届く", s_col.buffer[0][0].fg == "ff8800", s_col.buffer[0][0].fg)

# レンダラとクラス名まで通っているか
from shadow_clerk._daemon_console_render import style_key  # noqa: E402
check("33. レンダラが dim を出す", "dim" in style_key(s_dim.buffer[0][0]),
      style_key(s_dim.buffer[0][0]))
from shadow_clerk._daemon_dashboard_css import _CSS_TEMPLATE as _CSS  # noqa: E402
check("34. CSS に .cs-dim がある", ".cs-dim" in _CSS)

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
