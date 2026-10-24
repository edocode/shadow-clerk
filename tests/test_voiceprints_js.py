"""登録済みの人の「声紋の中身」（塊の表示・消す・移す・戻す）の JS を node で検証する

実行: uv run python tests/test_voiceprints_js.py
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
const I18N={'dash.speakers_samples':'声紋 {count} 件','dash.voiceprints_empty':'EMPTY','dash.delete':'削除',
  'dash.group_label':'グループ','dash.vp_show':'DETAILS','dash.vp_kind_main':'MAIN','dash.vp_kind_different':'DIFF',
  'dash.vp_kind_different_hint':'HINT','dash.vp_kind_outlier':'OUT','dash.vp_delete':'DEL','dash.vp_move':'MOVE',
  'dash.vp_move_apply':'APPLY','dash.vp_restore':'RESTORE','dash.vp_delete_confirm':'{name} の {count} 件を消す？'};
function esc(s){return String(s);}function escAttr(s){return String(s);}
function el(tag){return {tagName:String(tag||'').toUpperCase(),children:[],_h:'',textContent:'',value:'',dataset:{},
  get innerHTML(){return this._h;},set innerHTML(v){this._h=v;this.children=[];this.textContent='';},
  classList:{add(){},remove(){}},appendChild(c){this.children.push(c);},setAttribute(k,v){this[k]=v;}};}
const els={vpRows:el(),grpSuggest:el(),spkSuggest:el()};
const document={getElementById:id=>els[id],createElement:el,querySelectorAll:()=>[]};
let spkGroups={names:{},persons:{},groups:{},self_group:''};
let curFile='',activeFile='';
const posted=[],toasts=[],loaded=[],confirms=[],fetched=[];let failNext=false,postResp={status:'ok',message:'DONE'};
const KEYS_D=[['transcript-202610211000.txt','2026-10-21 10:00:05'],['transcript-202610211000.txt','2026-10-21 10:01:00']];
const KEYS_O=[['transcript-202610141000.txt','2026-10-14 10:00:09']];
const clustersResp={status:'ok',name:'太郎',clusters:[
  {kind:'main',count:12,similarity:1,keys:[['transcript-202610091000.txt','2026-10-09 10:00:00']],
   sources:[{file:'transcript-202610091000.txt',count:12,labels:[]}],example:'来週までに見積もりを'},
  {kind:'different',count:2,similarity:0.3,keys:KEYS_D,
   sources:[{file:'transcript-202610211000.txt',count:2,labels:['相手B']}],example:'<b>その件は</b>'},
  {kind:'outlier',count:1,similarity:0.1,keys:KEYS_O,sources:[{file:'transcript-202610141000.txt',count:1,labels:[]}],example:'はは'}]};
async function fetch(url,opt){
  if(failNext){failNext=false;throw new Error('down');}
  if(opt){posted.push({url,body:JSON.parse(opt.body)});return {json:async()=>postResp};}
  fetched.push(url);
  return {json:async()=>url.startsWith('/api/voiceprints/clusters')?clustersResp
    :url.startsWith('/api/speaker-groups')?{status:'ok',names:{},persons:{},groups:{},self_group:''}
    :{status:'ok',people:[{name:'太郎',count:15}]}};}
function showToast(m){toasts.push(m);}
function loadT(f){loaded.push('T:'+f);}function loadR(f){loaded.push('R:'+f);}
const alerts=[];function alert(m){alerts.push(m);}function confirm(m){confirms.push(m);return true;}
function getSelectedLines(){return [];}function deselectAll(){}
""" + _JS_TEMPLATE_SPEAKERS + _JS_TEMPLATE_VOICEPRINTS + r"""
function all(n,acc=[]){acc.push(n);for(const c of n.children||[])all(c,acc);return acc;}
const buttons=n=>all(n).filter(c=>c.tagName==='BUTTON');
const person=()=>els.vpRows.children[0];
const box=()=>all(person()).find(c=>(c.className||'').includes('vp-clusters'));
const rows=()=>box().children;
(async()=>{
  const out={};_spkFile='transcript-202610211000.txt';
  await loadVoiceprints();
  out.closed=box().children.length;
  await buttons(person()).find(b=>b.textContent==='DETAILS').onclick();
  out.fetchedClusters=fetched.filter(u=>u.startsWith('/api/voiceprints/clusters'));
  out.rows=rows().map(r=>({text:all(r).map(c=>c.textContent).join('|'),buttons:buttons(r).map(b=>b.textContent),
    hint:all(r).some(c=>(c.className||'').includes('vp-hint')),
    move:all(r).filter(c=>(c.className||'').includes('vp-move'))[0]?.hidden}));
  const diff=rows()[1],outl=rows()[2];
  await buttons(diff).find(b=>b.textContent==='DEL').onclick();
  out.deletePosted=posted[0];out.confirms=confirms.slice();out.toasts=toasts.slice();
  out.reopened=rows().length;
  posted.length=0;toasts.length=0;
  const d2=rows()[1];
  buttons(d2).find(b=>b.textContent==='MOVE').onclick();
  const form=all(d2).find(c=>(c.className||'').includes('vp-move'));
  const inp=all(form).find(c=>c.tagName==='INPUT');
  out.moveShown=[form.hidden,inp.list||inp.getAttribute?.('list')||inp['list']];
  inp.value='';await buttons(form).find(b=>b.textContent==='APPLY').onclick();
  out.emptyMove=posted.length;
  inp.value=' 花子 ';await buttons(form).find(b=>b.textContent==='APPLY').onclick();
  out.movePosted=posted[0];out.moveLoaded=loaded.slice();out.moveToasts=toasts.slice();
  posted.length=0;toasts.length=0;
  postResp={status:'ok',restored:1};
  await buttons(rows()[2]).find(b=>b.textContent==='RESTORE').onclick();
  out.restorePosted=posted[0];out.restoreToasts=toasts.slice();
  postResp={status:'error',message:'BAD'};
  await buttons(rows()[2]).find(b=>b.textContent==='RESTORE').onclick();
  out.errAlerts=alerts.slice();
  await buttons(person()).find(b=>b.textContent==='DETAILS').onclick();
  out.toggledClosed=box().children.length;
  failNext=true;await buttons(person()).find(b=>b.textContent==='DETAILS').onclick();
  out.loadErr=box().textContent;
  console.log(JSON.stringify(out));
})();
"""

r = subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    check("node で実行できる", False, r.stderr[-800:])
    sys.exit(1)
out = json.loads(r.stdout.strip().splitlines()[-1])
rows = out["rows"]
check("初めは塊を出さない", out["closed"] == 0, repr(out["closed"]))
check("声紋の中身を開くと名前で塊を取りに行く",
      out["fetchedClusters"] == ["/api/voiceprints/clusters?name=" + "%E5%A4%AA%E9%83%8E"], repr(out["fetchedClusters"]))
check("test_clusters_render_kinds_and_actions: 種類ごとの表示と操作",
      len(rows) == 3
      and rows[0]["buttons"] == [] and "MAIN" in rows[0]["text"] and not rows[0]["hint"]
      and rows[1]["buttons"] == ["DEL", "MOVE", "APPLY"] and "DIFF" in rows[1]["text"] and rows[1]["hint"]
      and rows[1]["move"] is True
      and rows[2]["buttons"] == ["RESTORE"] and "OUT" in rows[2]["text"] and not rows[2]["hint"], repr(rows))
check("塊の行に件数・会議ファイルと元のラベル・発言例を出す",
      "声紋 2 件" in rows[1]["text"] and "transcript-202610211000.txt (相手B)" in rows[1]["text"]
      and "<b>その件は</b>" in rows[1]["text"], repr(rows[1]))
check("消すは確認して name と keys を送り、トーストして開き直す",
      out["confirms"] == ["太郎 の 2 件を消す？"]
      and out["deletePosted"] == {"url": "/api/voiceprints/delete-samples", "body": {"name": "太郎", "keys": [
          ["transcript-202610211000.txt", "2026-10-21 10:00:05"], ["transcript-202610211000.txt", "2026-10-21 10:01:00"]]}}
      and out["toasts"] == ["DONE"] and out["reopened"] == 3, repr((out["confirms"], out["deletePosted"], out["toasts"], out["reopened"])))
check("別の人へ移す…で spkSuggest 付きの入力欄を出し、空なら送らない",
      out["moveShown"] == [False, "spkSuggest"] and out["emptyMove"] == 0, repr((out["moveShown"], out["emptyMove"])))
check("test_move_posts_keys_and_target: 移すは name・keys・to を送り、文字起こしを読み直す",
      out["movePosted"] == {"url": "/api/voiceprints/move", "body": {"name": "太郎", "keys": [
          ["transcript-202610211000.txt", "2026-10-21 10:00:05"], ["transcript-202610211000.txt", "2026-10-21 10:01:00"]],
          "to": "花子"}}
      and out["moveLoaded"] == ["T:transcript-202610211000.txt", "R:transcript-202610211000.txt"]
      and out["moveToasts"] == ["DONE"], repr((out["movePosted"], out["moveLoaded"], out["moveToasts"])))
check("戻すは name と keys を送る（message が無ければトーストしない）",
      out["restorePosted"] == {"url": "/api/voiceprints/restore", "body": {"name": "太郎", "keys": [
          ["transcript-202610141000.txt", "2026-10-14 10:00:09"]]}} and out["restoreToasts"] == [],
      repr((out["restorePosted"], out["restoreToasts"])))
check("失敗は alert", out["errAlerts"] == ["BAD"], repr(out["errAlerts"]))
check("もう一度押すと閉じる", out["toggledClosed"] == 0, repr(out["toggledClosed"]))
check("塊の取得失敗は本文に出す", out["loadErr"] == "Error: down", repr(out["loadErr"]))
sys.exit(0 if all(results) else 1)
