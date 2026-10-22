"""本文中のファイル名をリンクにする JS（FILE_REF_RE / _fileRefLink）を node で検証する

実行: uv run python tests/test_file_links_js.py
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


# 正規表現からリンク生成までを切り出して動かす（DOM の走査は実ブラウザで見る）
_SRC = _JS_TEMPLATE_CORE[_JS_TEMPLATE_CORE.index("const FILE_REF_RE"):_JS_TEMPLATE_CORE.index("function linkifyFiles")]
_SRC += _JS_TEMPLATE_CORE[_JS_TEMPLATE_CORE.index("function _fileRefLink"):
                          _JS_TEMPLATE_CORE.index("/* 下端追従")]

_BODY = r"""
const calls=[];let curFile='transcript-20261020.txt';
const fileInfo={'transcript-20261020.txt':{},'transcript-202610201529@ad-hoc.txt':{},'transcript-202609081610@勉強会.txt':{}};
const document={createElement:()=>({})};
function selectMtgFile(f){calls.push(['sel',f]);}
function switchSumTab(t){calls.push(['tab',t]);}
const texts=[
 '本体は `summary-202610201529@ad-hoc.md` |',
 '画面キャプチャ: shot-202609081610@勉強会-161622.png | タイトル',
 '対象: transcript-20261020-en.txt（翻訳）と analysis-202609081610@勉強会.md、advice-202609081610@勉強会.md。',
 'my-transcript-20261020.txt / summary-20990101.md',
];
const out=texts.map(t=>[...t.matchAll(FILE_REF_RE)].map(m=>{
  const a=_fileRefLink(m);
  if(!a)return [m[0],null];
  calls.length=0;
  if(a.onclick)a.onclick({preventDefault(){},stopPropagation(){}});
  return [m[0],a.href,a.target||'',calls.slice()];
}));
console.log(JSON.stringify(out));
"""


def main() -> None:
    r = subprocess.run(["node", "-e", _SRC + _BODY], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-500:])
        sys.exit(1)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    enc = "%E5%8B%89%E5%BC%B7%E4%BC%9A"  # 勉強会
    check("summary は対応する transcript を選んで要約タブを出す", out[0] == [[
        "summary-202610201529@ad-hoc.md", "#transcript-202610201529%40ad-hoc.txt", "",
        [["sel", "transcript-202610201529@ad-hoc.txt"], ["tab", "summary"]]]], repr(out[0]))
    check("キャプチャは画像を別タブで開く", out[1] == [[
        "shot-202609081610@勉強会-161622.png",
        f"/api/screenshot?file=shot-202609081610%40{enc}-161622.png", "_blank", []]], repr(out[1]))
    check("翻訳は元の transcript へ、表示中なら選び直さない",
          out[2][0] == ["transcript-20261020-en.txt", "#transcript-20261020.txt", "", []], repr(out[2]))
    check("analysis / advice は AI タブを出す",
          [o[3] for o in out[2][1:]] == [[["sel", f"transcript-202609081610@勉強会.txt"], ["tab", "ai"]]] * 2,
          repr(out[2]))
    check("語の途中や transcript の無いファイル名はリンクにしない",
          out[3] == [["summary-20990101.md", None]], repr(out[3]))


if __name__ == "__main__":
    main()
    sys.exit(0 if all(results) else 1)
