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
  'dash.speakers_none':'NONE','dash.speakers_active':'ACTIVE','dash.speakers_translating':'TRANSLATING','dash.speakers_enrollment_off':'OFF',
  'dash.group_label':'グループ','dash.person_enroll':'個人','dash.summary_regen_after_naming':'再生成する？',
  'dash.summary_started':'STARTED','dash.relabel_count':'{count} 行','speaker.mic':'自分',
  'dash.voiceprints_empty':'EMPTY','dash.delete':'削除','dash.voiceprint_delete_confirm':'{name} を消す？'};
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function escAttr(s){return esc(s).replace(/"/g,'&quot;');}
function el(){return {children:[],_h:'',textContent:'',value:'',disabled:false,dataset:{},
  get innerHTML(){return this._h;},set innerHTML(v){this._h=v;this.children=[];},
  classList:{open:false,add(){this.open=true;},remove(){this.open=false;}},
  appendChild(c){this.children.push(c);},setAttribute(k,v){this[k]=v;}};}
const els={spkRows:el(),spkInfo:el(),spkSuggest:el(),spkSaveBtn:el(),vpRows:el(),speakerModal:el(),
  rlName:el(),rlGroup:el(),rlPerson:el(),rlInfo:el(),rlSaveBtn:el(),relabelModal:el(),grpSuggest:el(),rlSuggest:el()};
let inputs=[],groupInputs=[],personInputs=[];
const document={getElementById:id=>els[id],createElement:()=>el(),
  querySelectorAll:q=>q==='#spkRows input[data-label]'?inputs:q==='#spkRows input[data-group-for]'?groupInputs
    :q==='#spkRows input[data-person-for]'?personInputs:[]};
let spkGroups={names:{},persons:{},groups:{},self_group:''};
let curFile='transcript-202610091000.txt',activeFile='';
const posted=[],toasts=[],loaded=[];
let speakersResp,vpResp={status:'ok',people:[{name:'太郎',count:3}]};
let failNext=false;const alerts=[];
async function fetch(url,opt){
  if(failNext){failNext=false;throw new Error('down');}
  if(opt){posted.push({url,body:JSON.parse(opt.body)});
    return {json:async()=>({status:'ok',message:'2 行に名前を付けました',has_summary:true})};}
  return {json:async()=>url.startsWith('/api/speaker-groups')?groupsResp
    :url.startsWith('/api/speakers')?speakersResp:vpResp};}
function showToast(m){toasts.push(m);}
function loadT(f){loaded.push('T:'+f);}function loadR(f){loaded.push('R:'+f);}
function alert(m){alerts.push(m);}function confirm(){return true;}
let selected=[];function getSelectedLines(){return selected;}function deselectAll(){selected=[];}
let groupsResp={status:'ok',names:{'太郎':'acme'},persons:{'太郎':true,'花子':false},groups:{acme:'#e57373','自社':'#64b5f6'},self_group:'自社'};
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
  inputs=[{dataset:{label:'相手A',named:'0'},value:' 太郎 '},{dataset:{label:'相手B',named:'0'},value:''},
          {dataset:{label:'次郎',named:'1'},value:''}];
  groupInputs=[{dataset:{groupFor:'相手A',orig:'',touched:'1'},value:'acme'},{dataset:{groupFor:'次郎',orig:'',touched:'1'},value:'自社'}];
  personInputs=[{dataset:{personFor:'相手A',orig:'1',touched:'1'},checked:true},{dataset:{personFor:'次郎',orig:'1'},checked:true}];
  out.mapping=speakerMapping();
  groupInputs=[{dataset:{groupFor:'相手A',orig:''},value:'acme'}];
  personInputs=[{dataset:{personFor:'相手A',orig:'1'},checked:true}];
  inputs=[{dataset:{label:'相手A',named:'0'},value:'太郎'}];
  out.untouchedMapping=speakerMapping();
  const nm={dataset:{label:'相手A',named:'0'},value:'花子'},gi={dataset:{groupFor:'相手A',orig:''},value:''},
    pi={dataset:{personFor:'相手A',orig:'1'},checked:true};
  inputs=[nm];groupInputs=[gi];personInputs=[pi];out.typing=[];
  for(const v of ['花子','太郎','acme','新人']){nm.value=v;onSpkNameInput(nm);out.typing.push([pi.checked,gi.value]);}
  pi.dataset.touched='1';gi.dataset.touched='1';gi.value='x';pi.checked=false;nm.value='太郎';onSpkNameInput(nm);
  out.typingTouched=[pi.checked,gi.value];
  groupInputs=[];personInputs=[];
  inputs=[{dataset:{label:'相手A',named:'0'},value:' 太郎 '},{dataset:{label:'相手B',named:'0'},value:''},
          {dataset:{label:'次郎',named:'1'},value:''}];
  speakersResp={status:'ok',labels:[{label:'太郎',count:2,example:'<i>x</i>',samples:1,named:true},
    {label:'相手A',count:1,example:'y',samples:0,named:false}],suggestions:[],active:false,enrollment:true};
  await openSpeakerModal();
  out.namedHtml=els.spkRows.children[0].innerHTML;out.unnamedHtml=els.spkRows.children[1].innerHTML;
  inputs=[{dataset:{label:'太郎',named:'1'},value:''},{dataset:{label:'相手A',named:'0'},value:''}];
  out.unchangedMapping=speakerMapping();
  inputs=[{dataset:{label:'太郎',named:'1'},value:' 次郎 '},{dataset:{label:'相手A',named:'0'},value:'三郎'}];
  out.changedMapping=speakerMapping();
  inputs=[{dataset:{label:'相手A',named:'0'},value:' 太郎 '},{dataset:{label:'相手B',named:'0'},value:''}];
  await saveSpeakers();
  out.posted=posted[0];out.toasts=toasts;out.loaded=loaded;
  speakersResp={status:'ok',labels:[{label:'相手A',count:1,example:'x',samples:0}],
    suggestions:[],active:true,enrollment:true};
  await openSpeakerModal();
  out.activeInfo=els.spkInfo.textContent;out.activeDisabled=els.spkSaveBtn.disabled;
  speakersResp={status:'ok',labels:[{label:'相手A',count:1,example:'x',samples:0}],
    suggestions:[],active:false,translating:true,enrollment:true};
  await openSpeakerModal();
  out.trInfo=els.spkInfo.textContent;out.trDisabled=els.spkSaveBtn.disabled;
  speakersResp={status:'ok',labels:[{label:'相手A',count:1,example:'x',samples:0}],
    suggestions:[],active:true,translating:true,enrollment:true};
  await openSpeakerModal();
  out.bothInfo=els.spkInfo.textContent;out.bothDisabled=els.spkSaveBtn.disabled;
  await deleteVoiceprint('太郎');
  out.deletePosted=posted[posted.length-1];
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
  curFile='transcript-202610091000.txt';
  await loadSpeakerGroups();
  out.selfColor=spColor('自分','自分');out.taroColor=spColor('太郎','自分');out.unknown=spColor('相手A','自分');
  posted.length=0;
  selected=[{dataset:{raw:'[2026-10-09 10:00:05] [相手A] 二行目'}},{dataset:{raw:'[2026-10-09 10:00:06] [自分] 自分'}}];
  await openRelabelModal();
  out.rlOpen=[els.rlPerson.checked,els.rlGroup.dataset.touched||''];
  els.rlName.value='太郎';onRlNameInput();out.rlTaro=[els.rlPerson.checked,els.rlGroup.value];
  els.rlName.value='花子';onRlNameInput();out.rlHanako=[els.rlPerson.checked,els.rlGroup.value];
  els.rlName.value='新人';onRlNameInput();out.rlNew=[els.rlPerson.checked,els.rlGroup.value];
  els.rlName.value='太郎';onRlNameInput();
  await saveRelabel();
  out.relabelUntouched=posted[0];posted.length=0;
  selected=[{dataset:{raw:'[2026-10-09 10:00:05] [相手A] 二行目'}}];
  await openRelabelModal();
  els.rlName.value=' acme ';els.rlGroup.value='acme';els.rlGroup.dataset.touched='1';
  els.rlPerson.checked=false;els.rlPerson.dataset.touched='1';
  await saveRelabel();
  out.relabelPosted=posted[0];out.regenPosted=posted[1];
  out.regenSaved=posted.length;
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
check("付け済みの行の名前欄は空で、現在の名前は placeholder とラベル欄に出す",
      'data-named="1" placeholder="太郎">' in out["namedHtml"] and '<span class="spk-label">太郎</span>' in out["namedHtml"]
      and "&lt;i&gt;" in out["namedHtml"], out["namedHtml"])
check("未命名の行の名前欄は空", 'data-named="0">' in out["unnamedHtml"], out["unnamedHtml"])
check("空のままの付け済みの行は送らない", out["unchangedMapping"] == {}, repr(out["unchangedMapping"]))
check("変更した付け済みの行は送る", out["changedMapping"] == {
      "太郎": {"name": "次郎"}, "相手A": {"name": "三郎"}},
      repr(out["changedMapping"]))
check("モーダルを開く", out["open"] and out["saveDisabled"] is False and out["vp"] == 1)
check("空欄は送らず前後空白を落とし、グループと個人区分も送る",
      out["mapping"] == {"相手A": {"name": "太郎", "group": "acme", "person": True},
                         "次郎": {"name": "次郎", "group": "自社"}}, repr(out["mapping"]))
check("assign に file と mapping を送る", out["posted"] == {"url": "/api/speakers/assign",
      "body": {"file": "transcript-202610091000.txt", "mapping": {"相手A": {"name": "太郎"}}}},
      repr(out["posted"]))
check("保存後にトーストと再読み込み", out["toasts"][:2] == ["2 行に名前を付けました", "STARTED"]
      and out["loaded"][:2] == ["T:transcript-202610091000.txt", "R:transcript-202610091000.txt"],
      repr((out["toasts"], out["loaded"])))
check("翻訳中は保存できない", out["trInfo"] == "TRANSLATING" and out["trDisabled"] is True)
check("録音中は保存できない", out["activeInfo"] == "ACTIVE" and out["activeDisabled"] is True)
check("録音中かつ翻訳中は保存できない", out["bothInfo"] == "ACTIVE" and out["bothDisabled"] is True)
check("声紋の削除を送る", out["deletePosted"] == {"url": "/api/voiceprints/delete", "body": {"name": "太郎"}},
      repr(out["deletePosted"]))
check("modal 取得失敗は alert", out["openErr"] == ["Error: down"], repr(out["openErr"]))
check("保存失敗は alert", out["saveErr"] == ["Error: down"], repr(out["saveErr"]))
check("削除失敗は alert", out["delErr"] == ["Error: down"], repr(out["delErr"]))
check("声紋一覧の失敗は本文に出す", out["vpErr"] == "Error: down", repr(out["vpErr"]))
check("ファイル未選択でもモーダルを開く", out["emptyOpen"] is True and out["emptyInfo"] == "NONE"
      and out["emptyDisabled"] is True and out["emptyVp"] == 1, repr((out["emptyOpen"], out["emptyInfo"], out["emptyDisabled"], out["emptyVp"])))
check("自分は self_group の色", out["selfColor"] == "#64b5f6", repr(out["selfColor"]))
check("名前のグループ色", out["taroColor"] == "#e57373" and out["unknown"] == "", repr((out["taroColor"], out["unknown"])))
check("行の付け替えは相手側の行だけ送る", out["relabelPosted"] == {"url": "/api/speakers/assign-lines", "body": {
      "file": "transcript-202610091000.txt", "lines": [{"ts": "2026-10-09 10:00:05", "label": "相手A"}],
      "name": "acme", "group": "acme", "person": False}}, repr(out["relabelPosted"]))
check("名前だけ変えたら group/person は送らない", out["untouchedMapping"] == {"相手A": {"name": "太郎"}}, repr(out["untouchedMapping"]))
check("名前の入力で個人チェックとグループ表示が追従する", out["typing"] == [[False, ""], [True, "acme"], [False, ""], [True, ""]]
      and out["typingTouched"] == [False, "x"], repr((out["typing"], out["typingTouched"])))
check("付け替え: 開いた時は個人・未編集", out["rlOpen"] == [True, ""], repr(out["rlOpen"]))
check("付け替え: 名前に追従", out["rlTaro"] == [True, "acme"] and out["rlHanako"] == [False, ""] and out["rlNew"] == [True, ""],
      repr((out["rlTaro"], out["rlHanako"], out["rlNew"])))
check("付け替え: 触っていなければ group/person は送らない", out["relabelUntouched"]["body"] == {
      "file": "transcript-202610091000.txt", "lines": [{"ts": "2026-10-09 10:00:05", "label": "相手A"}], "name": "太郎"},
      repr(out["relabelUntouched"]))
check("保存後に議事録の再生成を確認して頼む", out["regenPosted"] == {"url": "/api/summary",
      "body": {"file": "transcript-202610091000.txt"}}, repr(out["regenPosted"]))
sys.exit(0 if all(results) else 1)
