"""名前付けモーダルの JS を node で検証する

実行: uv run python tests/test_speakers_js.py
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

HARNESS = r"""
const I18N={'dash.speakers_count':'発話 {count} 件','dash.speakers_samples':'声紋 {count} 件',
  'dash.speakers_none':'NONE','dash.speakers_active':'ACTIVE','dash.speakers_enrollment_off':'OFF',
  'dash.voiceprints_empty':'EMPTY','dash.delete':'削除','dash.voiceprint_delete_confirm':'{name} を消す？'};
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function escAttr(s){return esc(s).replace(/"/g,'&quot;');}
function el(){return {children:[],_h:'',textContent:'',value:'',disabled:false,dataset:{},
  get innerHTML(){return this._h;},set innerHTML(v){this._h=v;this.children=[];},
  classList:{open:false,add(){this.open=true;},remove(){this.open=false;}},
  appendChild(c){this.children.push(c);}};}
const els={spkRows:el(),spkInfo:el(),spkSuggest:el(),spkSaveBtn:el(),vpRows:el(),speakerModal:el()};
let inputs=[];
const document={getElementById:id=>els[id],createElement:()=>el(),
  querySelectorAll:q=>q==='#spkRows input[data-label]'?inputs:[]};
let curFile='transcript-202610091000.txt',activeFile='';
const posted=[],toasts=[],loaded=[];
let speakersResp,vpResp={status:'ok',people:[{name:'太郎',count:3}]};
let failNext=false;const alerts=[];
async function fetch(url,opt){
  if(failNext){failNext=false;throw new Error('down');}
  if(opt){posted.push({url,body:JSON.parse(opt.body)});
    return {json:async()=>({status:'ok',message:'2 行に名前を付けました'})};}
  return {json:async()=>url.startsWith('/api/speakers')?speakersResp:vpResp};}
function showToast(m){toasts.push(m);}
function loadT(f){loaded.push('T:'+f);}function loadR(f){loaded.push('R:'+f);}
function alert(m){alerts.push(m);}function confirm(){return true;}
""" + _JS_TEMPLATE_SPEAKERS + r"""
(async()=>{
  const out={};
  speakersResp={status:'ok',labels:[{label:'相手A',count:2,example:'<b>やあ</b>',samples:2}],
    suggestions:['次郎','太郎'],active:false,enrollment:true};
  await openSpeakerModal();
  out.rowHtml=els.spkRows.children[0].innerHTML;
  out.suggest=els.spkSuggest.children.map(o=>o.value);
  out.open=els.speakerModal.classList.open===true;
  out.saveDisabled=els.spkSaveBtn.disabled;
  out.vp=els.vpRows.children.length;
  inputs=[{dataset:{label:'相手A'},value:' 太郎 '},{dataset:{label:'相手B'},value:''}];
  out.mapping=speakerMapping();
  await saveSpeakers();
  out.posted=posted[0];out.toasts=toasts;out.loaded=loaded;
  speakersResp={status:'ok',labels:[{label:'相手A',count:1,example:'x',samples:0}],
    suggestions:[],active:true,enrollment:true};
  await openSpeakerModal();
  out.activeInfo=els.spkInfo.textContent;out.activeDisabled=els.spkSaveBtn.disabled;
  await deleteVoiceprint('太郎');
  out.deletePosted=posted[1];
  alerts.length=0;
  failNext=true;await openSpeakerModal();out.openErr=alerts.slice();alerts.length=0;
  inputs=[{dataset:{label:'相手A'},value:'太郎'}];
  failNext=true;await saveSpeakers();out.saveErr=alerts.slice();alerts.length=0;
  failNext=true;await deleteVoiceprint('太郎');out.delErr=alerts.slice();alerts.length=0;
  failNext=true;await loadVoiceprints();out.vpErr=els.vpRows.textContent;
  curFile='';activeFile='';els.speakerModal.classList.open=false;els.spkSaveBtn.disabled=false;
  await openSpeakerModal();
  out.emptyOpen=els.speakerModal.classList.open;out.emptyInfo=els.spkInfo.textContent;
  out.emptyDisabled=els.spkSaveBtn.disabled;out.emptyVp=els.vpRows.children.length;
  console.log(JSON.stringify(out));
})();
"""

r = subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    check("node で実行できる", False, r.stderr[-500:])
    sys.exit(1)
out = json.loads(r.stdout.strip().splitlines()[-1])
check("例文は HTML エスケープする", "&lt;b&gt;" in out["rowHtml"] and "<b>" not in out["rowHtml"], out["rowHtml"])
check("ラベルと件数を出す", "相手A" in out["rowHtml"] and "発話 2 件" in out["rowHtml"], out["rowHtml"])
check("候補は参加者→登録済みの順", out["suggest"] == ["次郎", "太郎"], repr(out["suggest"]))
check("モーダルを開く", out["open"] and out["saveDisabled"] is False and out["vp"] == 1)
check("空欄は送らず前後空白を落とす", out["mapping"] == {"相手A": "太郎"}, repr(out["mapping"]))
check("assign に file と mapping を送る", out["posted"] == {"url": "/api/speakers/assign",
      "body": {"file": "transcript-202610091000.txt", "mapping": {"相手A": "太郎"}}}, repr(out["posted"]))
check("保存後にトーストと再読み込み", out["toasts"] == ["2 行に名前を付けました"]
      and out["loaded"] == ["T:transcript-202610091000.txt", "R:transcript-202610091000.txt"],
      repr((out["toasts"], out["loaded"])))
check("録音中は保存できない", out["activeInfo"] == "ACTIVE" and out["activeDisabled"] is True)
check("声紋の削除を送る", out["deletePosted"] == {"url": "/api/voiceprints/delete", "body": {"name": "太郎"}},
      repr(out["deletePosted"]))
check("modal 取得失敗は alert", out["openErr"] == ["Error: down"], repr(out["openErr"]))
check("保存失敗は alert", out["saveErr"] == ["Error: down"], repr(out["saveErr"]))
check("削除失敗は alert", out["delErr"] == ["Error: down"], repr(out["delErr"]))
check("声紋一覧の失敗は本文に出す", out["vpErr"] == "Error: down", repr(out["vpErr"]))
check("ファイル未選択でもモーダルを開く", out["emptyOpen"] is True and out["emptyInfo"] == "NONE"
      and out["emptyDisabled"] is True and out["emptyVp"] == 1, repr((out["emptyOpen"], out["emptyInfo"], out["emptyDisabled"], out["emptyVp"])))
sys.exit(0 if all(results) else 1)
