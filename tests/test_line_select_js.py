"""文字起こしの行のチェックボックス（Shift＋クリックの範囲選択）を node で検証する

実行: uv run python tests/test_line_select_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_js_core import _JS_TEMPLATE_CORE

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_SRC = _JS_TEMPLATE_CORE[_JS_TEMPLATE_CORE.index("/* --- Selection management --- */"):
                         _JS_TEMPLATE_CORE.index("/* --- Meeting toggle --- */")]

_BODY = r"""
const I18N={};
const cbs=[0,1,2,3,4].map(i=>({i,checked:false,closest(){return {i};}}));
const els={selActions:{classList:{add(){},remove(){}}},selCount:{},btnExtract:{style:{}}};
const document={getElementById:id=>els[id],
  querySelectorAll:q=>q==='#tp .ln-cb'?cbs:q==='#tp .ln-cb:checked'?cbs.filter(c=>c.checked):[]};
const click=(i,shiftKey)=>{cbs[i].checked=!cbs[i].checked;onLnCbClick({target:cbs[i],shiftKey});
  return [cbs.map(c=>c.checked?1:0).join(''),els.btnExtract.style.display];};
const out={};
out.plain=click(1,false);
out.shiftDown=click(3,true);
out.shiftUncheck=click(2,true);
out.plainOther=click(4,false);
out.shiftUp=click(0,true);
deselectAll();out.cleared=cbs.map(c=>c.checked?1:0).join('');
console.log(JSON.stringify(out));
"""


def main() -> None:
    check("行のチェックボックスはクリックで onLnCbClick を呼ぶ",
          'class="ln-cb" onclick="onLnCbClick(event)"' in _JS_TEMPLATE_CORE and 'class="ln-cb" onchange' not in _JS_TEMPLATE_CORE)
    r = subprocess.run(["node", "-e", _SRC + _BODY], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-500:])
        sys.exit(1)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    check("Shift なしのクリックはその行だけ", out["plain"] == ["01000", "none"], repr(out["plain"]))
    check("Shift＋クリックで前回の行からの間をすべて入れる", out["shiftDown"] == ["01110", "none"], repr(out["shiftDown"]))
    check("Shift＋クリックで外すと、前回の行からの間をすべて外す", out["shiftUncheck"] == ["01000", "none"], repr(out["shiftUncheck"]))
    check("上向きの範囲も同じ（2 行選択なら切り出しボタンを出す）",
          out["plainOther"] == ["01001", ""] and out["shiftUp"] == ["11111", "none"], repr((out["plainOther"], out["shiftUp"])))
    check("選択の解除", out["cleared"] == "00000", repr(out["cleared"]))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
