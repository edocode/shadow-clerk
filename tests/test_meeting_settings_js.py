"""現行（/）の会議ごとの設定モーダルが analyze: null（未指定）を正しく扱うかを node で検証する

GET /api/meeting-settings は会議ごとの analyze が未指定なら null を返す。現行モーダルはそれを
「しない」と描かず、1 件選んだときも「変更しない」から始めて analyze を送らない。

実行: uv run python tests/test_meeting_settings_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_js_meeting_settings import _JS_TEMPLATE_MEETING_SETTINGS
from shadow_clerk.i18n import STRINGS

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_MEETINGS = [
    {"name": "週次定例", "matched": "(defaults)", "shared": False, "analyze": None, "publish": True,
     "workdir": "", "publish_to": "artifact", "notion_url": "", "publish_advice": False},
    {"name": "雑談", "matched": "^雑談$", "shared": False, "analyze": False, "publish": True,
     "workdir": "", "publish_to": "artifact", "notion_url": "", "publish_advice": False},
]

_JS = ("const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";\nconst MEETINGS="
       + json.dumps(_MEETINGS, ensure_ascii=False) + ";\n") + r"""
const mkEl=()=>({textContent:'',innerHTML:'',value:'',checked:false,disabled:false,style:{},className:'',
  classList:{add(){},remove(){}},appendChild(c){this.children.push(c);},children:[],
  querySelector(){return {onchange:null,onclick:null};}});
const els={};
const document={getElementById:id=>els[id]||(els[id]=mkEl()),createElement:mkEl};
const esc=s=>String(s),escAttr=esc;
const meetingGroups={'週次定例':[1,2],'雑談':[1]};
const posts=[];
const fetch=async(url,opt)=>({json:async()=>{
  if(opt&&opt.method==='POST'){posts.push(JSON.parse(opt.body));return {status:'ok'};}
  return {status:'ok',path:'/x/meeting.yaml',meetings:MEETINGS};
}});
const setTimeout=()=>0;
""" + _JS_TEMPLATE_MEETING_SETTINGS + r"""
(async()=>{
  await openMeetingSettings();
  const out={badges:els.msBody.children.map(tr=>tr.innerHTML)};
  _msSel=new Set(['週次定例']);msFillEdit();
  out.nullValue=els.msAnalyze.value;
  els.msPublish.value='0';
  await msApply();
  _msSel=new Set(['雑談']);msFillEdit();
  out.offValue=els.msAnalyze.value;
  out.posts=posts;
  console.log(JSON.stringify(out));
})();
"""


def main() -> int:
    proc = subprocess.run(["node", "-e", _JS], capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        print(proc.stderr)
        check("node が動く", False)
        return 1
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    ja = STRINGS["ja"]
    check("未指定の会議のバッジは「既定」", ja.get("ms.analyze_default", "\0") in out["badges"][0]
          and ja["ms.analyze_off"] not in out["badges"][0].split("ms-badge")[1], out["badges"][0])
    check("オフの会議のバッジは「しない」のまま", ja["ms.analyze_off"] in out["badges"][1], out["badges"][1])
    check("1 件選んでも未指定は「変更しない」から始める", out["nullValue"] == "", repr(out["nullValue"]))
    check("オフの会議は「しない」", out["offValue"] == "0", repr(out["offValue"]))
    check("ほかの項目だけ変えても analyze は送らない（null を送らない）",
          out["posts"] == [{"meetings": ["週次定例"], "set": {"publish": False, "publish_advice": False, "workdir": "", "publish_to": "artifact"}}],
          repr(out["posts"]))
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
