"""Shadow-clerk daemon: pyte に渡す前に private CSI を取り除く

pyte は CSI のプライベートパラメータ接頭辞 `<` `=` `>` を解釈しない。

- `>` は読み飛ばされるだけなので、`ESC[>4m` (XTMODKEYS。キー入力の
  報告方式を切り替える列で、表示とは無関係) が `ESC[4m` = SGR 4 =
  下線として適用されてしまう。以降に描かれる文字がすべて下線付きになり、
  さらに pyte の消去は「消したセルを現在の SGR で埋める」実装なので、
  空行まで全幅の下線になる。
- `<` は未知の終端文字として扱われ列がそこで打ち切られるため、
  `ESC[<u` (Kitty keyboard protocol の pop) の `u` が本文として
  グリッドに描かれる。

どちらも端末の入力プロトコル制御で画面表示には関係しないため、
pyte に渡す前に落とす。`?` (DEC private mode) は pyte が正しく
扱うのでそのまま通す。

あわせて SGR 2 (faint) を書き換える。pyte の属性表に 2 は無く、そのまま
渡すと黙って捨てられる。claude の TUI は入力欄の候補テキストを faint で
描くので、落とすと自分が打った文字と見分けが付かなくなる。
"""
from __future__ import annotations

_ESC = "\x1b"
# 2 (faint) の写し先。pyte が持っていて claude の TUI が使わない属性を選ぶ。
# レンダラはこれを dim として薄く出す
_FAINT_TO = "5"
_FAINT_OFF_TO = "25"
# 38/48/58 は色指定で、続くパラメータを従える。ここに現れる 2 は
# 「24bit 色」の意味なので、faint と取り違えてはいけない
_COLOR_KEYS = {"38", "48", "58"}
_PRIVATE_PREFIXES = "<=>"
# CSI の終端バイトは 0x40-0x7E
_FINAL_LO = "\x40"
_FINAL_HI = "\x7e"
# 終端が来ないまま持ち越す上限。これを超えたら壊れた列とみなして素通しする
_MAX_PENDING = 64


def rewrite_sgr(params: str) -> str:
    """SGR のパラメータ列で、単独の 2 / 22 だけを pyte が扱える形に写す

    2 は 38;2;R;G;B のような色指定の副パラメータにも現れるため、色の並びを
    読み飛ばしながら走査する。22 は太字と faint の両方を解除するので、
    写し先の解除 (25) も足す。
    """
    if not params:
        return params
    parts = params.split(";")
    out: list[str] = []
    i = 0
    while i < len(parts):
        cur = parts[i]
        if cur in _COLOR_KEYS:
            # 38;5;n / 38;2;r;g;b。壊れた並びはそのまま渡して pyte に任せる
            nxt = parts[i + 1] if i + 1 < len(parts) else ""
            span = 3 if nxt == "5" else 5 if nxt == "2" else 1
            out.extend(parts[i:i + span])
            i += span
            continue
        if cur == "2":
            out.append(_FAINT_TO)
        elif cur == "22":
            out.extend(("22", _FAINT_OFF_TO))
        else:
            out.append(cur)
        i += 1
    return ";".join(out)


class PrivateCsiFilter:
    """CSI のプライベート接頭辞 `<` `=` `>` を持つ列を取り除く

    PTY の読み出しはチャンク境界が列の途中に落ちるので、終端まで見えない
    末尾は次の feed に持ち越して判定する。
    """

    def __init__(self) -> None:
        self._pending = ""

    def reset(self) -> None:
        """持ち越しを捨てる。PTY を張り直したときに呼ぶ"""
        self._pending = ""

    def feed(self, text: str) -> str:
        buf = self._pending + text
        self._pending = ""
        out: list[str] = []
        i, n = 0, len(buf)
        while i < n:
            j = buf.find(_ESC, i)
            if j < 0:
                out.append(buf[i:])
                break
            out.append(buf[i:j])
            if j + 1 >= n:                 # ESC の次がまだ見えていない
                self._pending = buf[j:]
                break
            if buf[j + 1] != "[":          # CSI 以外 (ESC 7 / OSC など) は素通し
                out.append(buf[j:j + 2])
                i = j + 2
                continue
            if j + 2 >= n:                 # パラメータの先頭が見えていない
                self._pending = buf[j:]
                break
            private = buf[j + 2] in _PRIVATE_PREFIXES
            k = j + 3 if private else j + 2
            while k < n and not _FINAL_LO <= buf[k] <= _FINAL_HI:
                k += 1
            if k >= n:                     # 終端がまだ来ていない
                if n - j > _MAX_PENDING:   # 長すぎるものは壊れた列とみなして通す
                    out.append(buf[j:])
                else:
                    self._pending = buf[j:]
                break
            if not private:
                if buf[k] == "m":
                    out.append(_ESC + "[" + rewrite_sgr(buf[j + 2:k]) + "m")
                else:
                    out.append(buf[j:k + 1])
            i = k + 1                      # private は終端ごと捨てる
        return "".join(out)
