"""削除・切り出しモーダルの JS を node で検証する

- 一括削除: プレビューと実際に消す行が一致すること
- 切り出しの成功: alert で画面を止めず、トーストで知らせること

実行: uv run python tests/test_modals_js.py
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

from shadow_clerk._daemon_dashboard_js_modals import _JS_TEMPLATE_MODALS  # noqa: E402

HARNESS = r"""
const I18N={};
const ln=(ts,checked)=>({dataset:{ts,raw:'['+ts+'] x'},checked,textContent:ts});
const LINES=[ln('10:00',true),ln('10:01',false),ln('10:02',false),ln('10:03',true)];
let mode='range',posted=null;
function box(){return {children:[],style:{},classList:{add(){},remove(){}},
  appendChild(c){this.children.push(c);},set innerHTML(v){this.children=[];}};}
const els={bulkDelTranscript:box(),bulkDelTranslation:box(),bulkDelRangeOpt:box(),bulkDelModal:box(),
  extractModal:box(),splitAllMin:{value:'1'},tf:{textContent:'t.txt'}};
const body=box(),alerts=[];
const document={body,
  getElementById:id=>els[id]||{querySelectorAll:()=>[]},
  createElement:()=>({textContent:'',remove(){}}),
  querySelector:q=>q.includes(':checked')?{value:mode}:{checked:false},
  querySelectorAll:q=>q.startsWith('#tp .ln[data-ts]')?LINES:[]};
function getSelectedLines(){return LINES.filter(l=>l.checked);}
function deselectAll(){}
async function fetch(url,opt){posted=JSON.parse(opt.body);
  return {json:async()=>(url.includes('split-by-silence')?{status:'ok',message:'2 件作りました'}:{status:'error'})};}
function alert(m){alerts.push(m);}
function loadFiles(){}function loadT(){}function loadR(){}let curFile='t.txt';
""" + _JS_TEMPLATE_MODALS + r"""
(async()=>{
  const out={};
  const shown=()=>els.bulkDelTranscript.children.map(c=>c.textContent);
  openBulkDelModal();out.rangePreview=shown();
  await doBulkDel();out.rangeDeleted=posted.lines;
  mode='selected';renderBulkDelPreview();out.selPreview=shown();
  await doBulkDel();out.selDeleted=posted.lines;
  alerts.length=0;mode='splitAll';await doExtractMeeting();
  out.extractAlerts=alerts.slice();out.toasts=body.children.map(c=>c.textContent);
  console.log(JSON.stringify(out));
})();
"""

r = subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    check("node で実行できる", False, r.stderr[-500:])
    sys.exit(1)
out = json.loads(r.stdout.strip().splitlines()[-1])
check("範囲指定のプレビューは間の行も含む", out["rangePreview"] == ["[10:00] x", "[10:01] x", "[10:02] x", "[10:03] x"],
      repr(out["rangePreview"]))
check("範囲指定で消す行はプレビューと同じ", out["rangeDeleted"] == out["rangePreview"], repr(out["rangeDeleted"]))
check("選んだ行だけに切り替えるとプレビューも変わる", out["selPreview"] == ["[10:00] x", "[10:03] x"], repr(out["selPreview"]))
check("選んだ行だけで消す行はプレビューと同じ", out["selDeleted"] == out["selPreview"], repr(out["selDeleted"]))
check("切り出しの成功は alert で止めない", out["extractAlerts"] == [], repr(out["extractAlerts"]))
check("切り出しの成功はトーストで知らせる", out["toasts"] == ["2 件作りました"], repr(out["toasts"]))
sys.exit(0 if all(results) else 1)
