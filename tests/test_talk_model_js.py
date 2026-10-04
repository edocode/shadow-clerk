"""talk 開始モーダルのモデル選択の JS を node で検証する

実行: uv run python tests/test_talk_model_js.py
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
const I18N={'dash.talk_model_default':'DEFAULT'};
let CFG,log=[];
const els={};
function mkEl(){return {children:[],value:'',disabled:false,textContent:'',classList:{add(){},remove(){}},
  appendChild(c){this.children.push(c);},set innerHTML(v){this.children=[];}};}
const document={getElementById:id=>els[id]=els[id]||mkEl(),createElement:()=>({value:'',textContent:''})};
async function fetch(url,opt){
  if(url==='/api/config'&&!opt)return {json:async()=>JSON.parse(JSON.stringify(CFG))};
  if(url==='/api/config'){log.push(['config',JSON.parse(opt.body).talk_model]);return {json:async()=>({})};}
  log.push(['talk']);return {json:async()=>({status:'ok'})};
}
function closeTalk(){}
""" + _JS_TEMPLATE_TALK + r"""
(async()=>{
  const out={};
  const pick=()=>{const s=els.talkModel;return {value:s.value,opts:s.children.map(o=>o.value)};};
  CFG={talk_model:'sonnet'};els.talkModel=mkEl();await fillModelSel();out.known=pick();
  CFG={talk_model:'claude-x-1'};els.talkModel=mkEl();await fillModelSel();out.custom=pick();
  CFG={talk_model:''};els.talkModel=mkEl();await fillModelSel();out.empty=pick();
  CFG={talk_model:'sonnet'};els.talkModel.value='haiku';
  els.talkTopic={value:''};els.talkPersonaSel={value:''};els.talkWorkdir={value:''};
  await startTalk();out.log=log;
  console.log(JSON.stringify(out));
})();
"""

r = subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    check("node で実行できる", False, r.stderr[-500:])
    sys.exit(1)
out = json.loads(r.stdout.strip().splitlines()[-1])
base = ["", "opus", "sonnet", "haiku"]
check("現在のモデルを選んでおく", out["known"] == {"value": "sonnet", "opts": base}, repr(out["known"]))
check("独自のモデル ID も選択肢に足して失わない", out["custom"] == {"value": "claude-x-1", "opts": base + ["claude-x-1"]},
      repr(out["custom"]))
check("空なら既定を選ぶ", out["empty"] == {"value": "", "opts": base}, repr(out["empty"]))
check("開始前に選んだモデルを保存する", out["log"][:2] == [["config", "haiku"], ["talk"]], repr(out["log"]))
sys.exit(0 if all(results) else 1)
