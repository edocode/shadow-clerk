"""talk 開始モーダルの「声を届ける先」の JS を node で検証する

実行: uv run python tests/test_talk_route_js.py
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

from shadow_clerk._daemon_dashboard_js_talk import _JS_TEMPLATE_TALK  # noqa: E402

HARNESS = r"""
const I18N={'dash.talk_route_none':'NONE','dash.talk_route_unavailable':'UNAVAIL'};
let ROUTE,posted=[];
const els={};
function mkEl(){return {children:[],value:'',disabled:false,textContent:'',classList:{add(){},remove(){}},
  appendChild(c){this.children.push(c);},set innerHTML(v){this.children=[];}};}
const document={getElementById:id=>els[id]=els[id]||mkEl(),createElement:()=>({value:'',textContent:''})};
function resetSel(){els.talkRoute=mkEl();els.talkRouteNote=mkEl();}
async function fetch(url,opt){
  if(url==='/api/talk-route-targets')return {json:async()=>ROUTE};
  if(url==='/api/config')return {json:async()=>({talk_route_app:'Zoom'})};
  posted.push(JSON.parse(opt.body));return {json:async()=>({status:'ok'})};
}
function closeTalk(){}
""" + _JS_TEMPLATE_TALK + r"""
(async()=>{
  const out={};
  // sel.value は選択肢に無い値だと本物の select では '' になるので、スタブでも options から確かめる
  const pick=()=>{const s=els.talkRoute;return {value:s.value,disabled:s.disabled,opts:s.children.map(o=>o.value)};};
  ROUTE={available:false,targets:[]};resetSel();await fillRouteSel();out.unavailable=pick();
  els.talkRoute.value='Zoom';els.talkTopic={value:''};els.talkPersonaSel={value:''};els.talkWorkdir={value:''};
  await startTalk();out.sentWhenDisabled=posted[0].route;
  ROUTE={available:true,targets:[{app:'Chromium',label:'C'}]};resetSel();await fillRouteSel();out.available=pick();
  console.log(JSON.stringify(out));
})();
"""

r = subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    check("node で実行できる", False, r.stderr[-500:])
    sys.exit(1)
out = json.loads(r.stdout.strip().splitlines()[-1])
u, a = out["unavailable"], out["available"]
check("使えない環境では覚えたアプリを足さず空にする", u["value"] == "" and u["disabled"] and u["opts"] == [""], repr(u))
check("使えない環境の開始は route を送らない", out["sentWhenDisabled"] is None, repr(out))
check("使える環境では一覧に無い覚えたアプリも選ぶ",
      a["value"] == "Zoom" and not a["disabled"] and a["opts"] == ["", "Chromium", "Zoom"], repr(a))
sys.exit(0 if all(results) else 1)
