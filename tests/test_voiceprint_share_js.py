"""声紋の書き出し・取り込み（登録済みの人）の JS を node で検証する

実行: uv run python tests/test_voiceprint_share_js.py
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

from shadow_clerk._daemon_dashboard_js_speakers import _JS_TEMPLATE_SPEAKERS  # noqa: E402
from shadow_clerk._daemon_dashboard_js_voiceprints import _JS_TEMPLATE_VOICEPRINTS  # noqa: E402

HARNESS = r"""
const I18N=new Proxy({'dash.vp_import_existing':'ADD {name}','dash.vp_import_new':'NEW','dash.vp_import_from':'FROM {date}'},
  {get:(o,k)=>k in o?o[k]:k});
function el(tag){return {tagName:String(tag||'').toUpperCase(),children:[],_h:'',textContent:'',value:'',dataset:{},
  get innerHTML(){return this._h;},set innerHTML(v){this._h=v;this.children=[];this.textContent='';},
  classList:{add(){},remove(){}},appendChild(c){this.children.push(c);},setAttribute(k,v){this[k]=v;},click(){clicked.push(this.download);}};}
const els={vpRows:el(),grpSuggest:el(),spkSuggest:el(),vpNames:el(),vpPickGroup:el(),vpImport:el()};
function all(n,acc=[]){acc.push(n);for(const c of n.children||[])all(c,acc);return acc;}
const document={getElementById:id=>els[id],createElement:el,
  querySelectorAll:sel=>sel==='#vpRows input.vp-pick'?all(els.vpRows).filter(c=>c.className==='vp-pick'):[]};
const URL={createObjectURL:()=>'blob:x',revokeObjectURL(){}};class Blob{constructor(p){this.p=p;}}
let spkGroups={names:{},persons:{},groups:{},self_group:''};
const posted=[],toasts=[],alerts=[],clicked=[];let postResp={status:'ok',message:'DONE'};
async function fetch(url,opt){
  if(opt){posted.push({url,body:JSON.parse(opt.body)});return {json:async()=>postResp};}
  return {json:async()=>url.startsWith('/api/speaker-groups')
    ?{status:'ok',names:{'太郎':'acme','次郎':'globex'},persons:{'太郎':true,'次郎':true,'三郎':true},groups:{},self_group:''}
    :{status:'ok',people:[{name:'太郎',count:3},{name:'次郎',count:2}]}};}
function showToast(m){toasts.push(m);}function alert(m){alerts.push(m);}function confirm(){return true;}
function loadT(){}function loadR(){}function getSelectedLines(){return [];}function deselectAll(){}
""" + _JS_TEMPLATE_SPEAKERS + _JS_TEMPLATE_VOICEPRINTS + r"""
const picks=()=>all(els.vpRows).filter(c=>c.className==='vp-pick');
(async()=>{
  const out={};
  await loadVoiceprints();
  out.groupOpts=els.vpPickGroup.children.map(o=>o.value);
  out.disabled=picks().map(c=>[c.dataset.name,c.disabled]);
  await exportVoiceprints();out.noneAlert=alerts.slice();
  els.vpPickGroup.value='acme';vpPickGroup(els.vpPickGroup);
  out.afterGroup=picks().filter(c=>c.checked).map(c=>c.dataset.name);
  els.vpPickGroup.value='*';vpPickGroup(els.vpPickGroup);
  out.afterAll=picks().filter(c=>c.checked).map(c=>c.dataset.name);
  postResp={status:'ok',data:{format:'shadow-clerk-voiceprints'},filename:'voiceprints-2026-10-29.json',message:'EXPORTED'};
  await exportVoiceprints();
  out.exportPosted=posted.pop();out.clicked=clicked.slice();out.toasts=toasts.splice(0);
  const file={format:'shadow-clerk-voiceprints',exported_at:'2026-10-29 10:00:00',
    people:[{name:'太郎',group:'acme',samples:[{},{}]},{name:'Hanako',group:'',samples:[{}]}]};
  const input=t=>({value:'x',files:[{text:async()=>t}]});
  await readVoiceprintImport(input('not json'));out.badAlert=alerts.slice(-1);
  await readVoiceprintImport(input(JSON.stringify(file)));
  const rows=_vpImportRows;
  const state=r=>all(els.vpImport).filter(c=>c.className==='spk-meta')[1+rows.indexOf(r)*2+1].textContent;
  out.states=rows.map(state);
  rows[1].to.value='次郎';rows[1].to.oninput();out.renamed=state(rows[1]);
  rows[0].pick.checked=false;
  postResp={status:'ok',message:'IMPORTED'};
  const apply=all(els.vpImport).find(c=>c.tagName==='BUTTON'&&c.textContent==='dash.vp_import_apply');
  await apply.onclick();
  out.importPosted=posted.pop();out.importToasts=toasts.slice();out.cleared=els.vpImport.children.length;
  await readVoiceprintImport(input(JSON.stringify(file)));
  _vpImportRows[0].to.value=' ';alerts.length=0;await importVoiceprints();
  out.emptyAlert=alerts.slice();out.emptyPosted=posted.length;
  console.log(JSON.stringify(out));
})();
"""

r = subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    check("node で実行できる", False, r.stderr[-800:])
    sys.exit(1)
out = json.loads(r.stdout.strip().splitlines()[-1])
check("グループで選ぶ: 先頭は見出し、全員、グループ名", out["groupOpts"] == ["", "*", "acme", "globex"], repr(out["groupOpts"]))
check("声紋の無い人は選べない", out["disabled"] == [["三郎", True], ["太郎", False], ["次郎", False]], repr(out["disabled"]))
check("誰も選ばずに書き出すと止める", out["noneAlert"] == ["dash.vp_export_none"], repr(out["noneAlert"]))
check("グループで選ぶ・全員を選ぶ（声紋の無い人は選ばない）",
      out["afterGroup"] == ["太郎"] and out["afterAll"] == ["太郎", "次郎"], repr((out["afterGroup"], out["afterAll"])))
check("書き出しは選んだ名前を送り、ファイルを保存する",
      out["exportPosted"] == {"url": "/api/voiceprints/export", "body": {"names": ["太郎", "次郎"]}}
      and out["clicked"] == ["voiceprints-2026-10-29.json"] and out["toasts"] == ["EXPORTED"], repr(out["exportPosted"]))
check("書き出しファイルでなければ止める", out["badAlert"] == ["dash.vp_import_invalid"], repr(out["badAlert"]))
check("取り込み先の状態: 既存の人に追加・新しい人", out["states"] == ["ADD 太郎", "NEW"], repr(out["states"]))
check("名前を書き換えると状態も変わる", out["renamed"] == "ADD 次郎", repr(out["renamed"]))
check("チェックした人だけ、取り込み先の名前で送る",
      out["importPosted"]["url"] == "/api/voiceprints/import"
      and out["importPosted"]["body"]["mapping"] == {"Hanako": "次郎"}
      and out["importPosted"]["body"]["data"]["exported_at"] == "2026-10-29 10:00:00"
      and out["importToasts"] == ["IMPORTED"] and out["cleared"] == 0, repr(out["importPosted"]))
check("取り込み先が空なら送らない", out["emptyAlert"] == ["dash.vp_import_empty_name"] and out["emptyPosted"] == 0,
      repr((out["emptyAlert"], out["emptyPosted"])))
sys.exit(0 if all(results) else 1)
