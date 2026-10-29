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
from shadow_clerk._daemon_dashboard_js_voiceprints import _JS_TEMPLATE_VOICEPRINTS  # noqa: E402

HARNESS = r"""
const I18N={'dash.speakers_count':'発話 {count} 件','dash.speakers_samples':'声紋 {count} 件',
  'dash.speakers_none':'NONE','dash.speakers_active':'ACTIVE','dash.speakers_daily_active':'DAILY','dash.speakers_translating':'TRANSLATING','dash.speakers_enrollment_off':'OFF',
  'dash.group_label':'グループ','dash.person_enroll':'個人','dash.summary_regen_after_naming':'再生成する？',
  'dash.summary_started':'STARTED','speaker.mic':'自分',
  'dash.voiceprints_empty':'EMPTY','dash.delete':'削除','dash.voiceprint_delete_confirm':'{name} を消す？',
  'dash.naming_history_title':'HISTORY','dash.naming_undo':'UNDO','dash.naming_undone_mark':'UNDONE',
  'dash.naming_undo_confirm':'{label} → {name} を取り消す？','dash.vp_show':'DETAILS',
  'dash.naming_history_error':'HISTERR','dash.speakers_tentative':'TENTATIVE','dash.speakers_auto_confirm':'CONFIRM {count}',
  'dash.speakers_tentative_accept':'ACCEPT {name}','dash.relabel_scope_one':'ONE','dash.relabel_scope_two':'TWO',
  'dash.relabel_scope_lines':'MANY','dash.relabel_target_lines':'LINES {count}','dash.relabel_target_range':'RANGE {count}',
  'dash.relabel_target_label':'LABEL {labels} {count}','dash.speakers_provisional_info':'PROVINFO',
  'dash.relabel_provisional_hint':'PROVHINT'};
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function escAttr(s){return esc(s).replace(/"/g,'&quot;');}
function el(){return {children:[],_h:'',textContent:'',value:'',disabled:false,dataset:{},
  get innerHTML(){return this._h;},set innerHTML(v){this._h=v;this.children=[];},
  classList:{open:false,add(){this.open=true;},remove(){this.open=false;}},
  appendChild(c){this.children.push(c);},setAttribute(k,v){this[k]=v;}};}
function mk(tag){return Object.assign(el(),{tagName:String(tag).toUpperCase()});}
const els={spkRows:el(),spkInfo:el(),spkSuggest:el(),spkSaveBtn:el(),vpRows:el(),speakerModal:el(),
  rlName:el(),rlGroup:el(),rlPerson:el(),rlInfo:el(),rlSaveBtn:el(),relabelModal:el(),grpSuggest:el(),rlSuggest:el(),
  spkHistory:el(),rlScopeLines:el(),rlScopeRange:el(),rlScopeLabel:el(),rlScopeRangeOpt:el(),rlScopeLabelOpt:el(),
  rlScopeLinesText:el(),rlTarget:el()};
let tpLines=[];
let inputs=[],groupInputs=[],personInputs=[],confirmInputs=[],acceptInputs=[];
const document={getElementById:id=>els[id],createElement:mk,
  querySelectorAll:q=>q==='#spkRows input[data-label]'?inputs:q==='#spkRows input[data-group-for]'?groupInputs
    :q==='#spkRows input[data-person-for]'?personInputs:q==='#spkRows input[data-confirm-for]'?confirmInputs
    :q==='#spkRows input[data-accept-for]'?acceptInputs:q==='#tp .ln[data-ts]'?tpLines:[]};
let spkGroups={names:{},persons:{},groups:{},self_group:''};
let curFile='transcript-202610091000.txt',activeFile='';
const posted=[],toasts=[],loaded=[];
let speakersResp,vpResp={status:'ok',people:[{name:'太郎',count:3}]};
let failNext=false;const alerts=[],postResp=[];
async function fetch(url,opt){
  if(failNext){failNext=false;throw new Error('down');}
  if(opt){posted.push({url,body:JSON.parse(opt.body)});const q=postResp.shift();
    return {json:async()=>(q||{status:'ok',message:'2 行に名前を付けました',has_summary:true})};}
  return {json:async()=>url.startsWith('/api/speaker-groups')?groupsResp
    :url.startsWith('/api/speakers')?speakersResp:vpResp};}
function showToast(m){toasts.push(m);}
function loadT(f){loaded.push('T:'+f);}function loadR(f){loaded.push('R:'+f);}
function alert(m){alerts.push(m);}const confirms=[];function confirm(m){confirms.push(m);return true;}
let selected=[];function getSelectedLines(){return selected;}function deselectAll(){selected=[];}
let groupsResp={status:'ok',names:{'太郎':'acme'},persons:{'太郎':true,'花子':false},groups:{acme:'#e57373','自社':'#64b5f6'},self_group:'自社'};
""" + _JS_TEMPLATE_SPEAKERS + _JS_TEMPLATE_VOICEPRINTS + r"""
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
  personInputs=[{dataset:{personFor:'相手A',orig:'1',touched:'1'},checked:true},{dataset:{personFor:'次郎',orig:'0'},checked:false}];
  out.mapping=speakerMapping();
  groupInputs=[{dataset:{groupFor:'相手A',orig:'',touched:'1'},value:'acme'}];
  personInputs=[{dataset:{personFor:'相手A',orig:'0',touched:'1'},checked:false}];
  inputs=[{dataset:{label:'相手A',named:'0'},value:'太郎'}];
  out.uncheckedGroup=speakerMapping();
  personInputs=[{dataset:{personFor:'相手A',orig:'1',touched:'1'},checked:true}];
  out.recheckedNoGroup=speakerMapping();
  inputs=[{dataset:{label:'相手A',named:'0'},value:' 太郎 '},{dataset:{label:'相手B',named:'0'},value:''},
          {dataset:{label:'次郎',named:'1'},value:''}];
  groupInputs=[{dataset:{groupFor:'相手A',orig:''},value:'acme'}];
  personInputs=[{dataset:{personFor:'相手A',orig:'1'},checked:true}];
  inputs=[{dataset:{label:'相手A',named:'0'},value:'太郎'}];
  out.untouchedMapping=speakerMapping();
  const nm={dataset:{label:'相手A',named:'0'},value:'花子'},gi={dataset:{groupFor:'相手A',orig:''},value:''},
    pi={dataset:{personFor:'相手A',orig:'1'},checked:true};
  inputs=[nm];groupInputs=[gi];personInputs=[pi];out.typing=[];
  for(const v of ['花子','太郎','acme','新人']){nm.value=v;onSpkNameInput(nm);out.typing.push([pi.checked,gi.value,gi.hidden]);}
  pi.dataset.touched='1';gi.dataset.touched='1';gi.value='x';pi.checked=false;nm.value='太郎';onSpkNameInput(nm);
  out.typingTouched=[pi.checked,gi.value,gi.hidden];
  pi.checked=true;onSpkPersonChange(pi);out.toggleHidden=[gi.hidden,pi.dataset.touched];
  pi.checked=false;onSpkPersonChange(pi);out.toggleShown=gi.hidden;
  groupInputs=[];personInputs=[];
  inputs=[{dataset:{label:'相手A',named:'0'},value:' 太郎 '},{dataset:{label:'相手B',named:'0'},value:''},
          {dataset:{label:'次郎',named:'1'},value:''}];
  speakersResp={status:'ok',labels:[{label:'太郎',count:2,example:'<i>x</i>',samples:1,named:true},
    {label:'相手A',count:1,example:'y',samples:0,named:false}],suggestions:[],active:false,enrollment:true};
  await openSpeakerModal();
  speakersResp={status:'ok',labels:[{label:'先方営業',count:1,example:'z',samples:0,person:false,group:'acme'}],
    suggestions:[],active:false,enrollment:true};
  await openSpeakerModal();out.hiddenRowHtml=els.spkRows.children[0].innerHTML;
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
  out.posted=posted[0];out.toasts=toasts.slice();out.loaded=loaded.slice();
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
  out.tentColor=spColor('太郎?','自分');out.unkTent=spColor('相手?','自分');
  out.notTent=[spColor('自分?','自分'),spColor('相手A?','自分'),spColor('Claude?','自分'),spColor('?','自分')];
  out.selfColor=spColor('自分','自分');out.taroColor=spColor('太郎','自分');out.unknown=spColor('相手A','自分');
  posted.length=0;
  selected=[{dataset:{raw:'[2026-10-09 10:00:05] [相手A] 二行目'}},{dataset:{raw:'[2026-10-09 10:00:06] [自分] 自分'}}];
  await openRelabelModal();
  out.rlOpen=[els.rlPerson.checked,els.rlGroup.dataset.touched||'',els.rlGroup.hidden];
  els.rlName.value='太郎';onRlNameInput();out.rlTaro=[els.rlPerson.checked,els.rlGroup.value,els.rlGroup.hidden];
  els.rlName.value='花子';onRlNameInput();out.rlHanako=[els.rlPerson.checked,els.rlGroup.value,els.rlGroup.hidden];
  els.rlName.value='新人';onRlNameInput();out.rlNew=[els.rlPerson.checked,els.rlGroup.value,els.rlGroup.hidden];
  els.rlName.value='太郎';onRlNameInput();
  await saveRelabel();
  out.relabelUntouched=posted[0];posted.length=0;
  selected=[{dataset:{raw:'[2026-10-09 10:00:05] [相手A] 二行目'}}];
  await openRelabelModal();
  els.rlName.value=' acme ';els.rlGroup.value='acme';els.rlGroup.dataset.touched='1';
  els.rlPerson.checked=false;onRlPersonChange();out.rlToggle=[els.rlGroup.hidden,els.rlPerson.dataset.touched];
  await saveRelabel();
  out.relabelPosted=posted[0];out.regenPosted=posted[1];
  posted.length=0;els.rlPerson.checked=true;onRlPersonChange();out.rlToggleBack=els.rlGroup.hidden;
  await saveRelabel();out.relabelRechecked=posted[0];posted.length=0;posted.push(0,out.regenPosted);
  out.regenSaved=posted.length;
  posted.length=0;
  groupsResp={status:'ok',names:{'太郎':'acme'},persons:{'太郎':true,'花子':false,'三郎':true},groups:{acme:'#e57373'},self_group:''};
  vpResp={status:'ok',people:[{name:'太郎',count:3},{name:'次郎',count:1}]};
  await loadVoiceprints();
  const rows=els.vpRows.children;
  out.people=rows.map(r=>[r.children[0].textContent,r.children.length,r.children[1]?r.children[1].value:null]);
  out.grpSuggest=els.grpSuggest.children.map(o=>o.value);
  const g0=rows[1].children[1];g0.value=' globex ';await g0.onchange();
  out.vpSet=posted[0];
  groupsResp={status:'error',message:'broken'};alerts.length=0;
  await loadVoiceprints();
  out.peopleErr=els.vpRows.children.map(r=>[r.children[0].textContent,r.children.length]);out.peopleErrAlerts=alerts.slice();
  vpResp={status:'ok',people:[]};
  groupsResp={status:'ok',names:{},persons:{'花子':false},groups:{},self_group:''};
  await loadVoiceprints();out.peopleNone=[els.vpRows.children.length,els.vpRows.textContent];
  selected=[{dataset:{raw:'[2026-10-09 10:00:07] [相手?] うん'}},{dataset:{raw:'[2026-10-09 10:00:08] [Claude] はい'}}];
  await openRelabelModal();out.rlUnknown=_rlItems;
  posted.length=0;toasts.length=0;loaded.length=0;confirms.length=0;
  speakersResp={status:'ok',labels:[{label:'相手A',count:1,example:'x',samples:0}],suggestions:[],active:false,enrollment:true,
    history:[{id:'h2',at:'2026-10-09 11:00:00',label:'相手B',name:'太郎',person:true,lines:3,added:2,undone:false},
             {id:'h1',at:'2026-10-09 10:59:00',label:'相手A',name:'acme',person:false,lines:1,added:0,undone:true}]};
  await openSpeakerModal();
  const hrows=els.spkHistory.children.filter(r=>(r.className||'').includes('spk-row'));
  const txt=r=>r.children.map(c=>c.textContent).join('|');
  out.hist=hrows.map(r=>[txt(r),r.children.filter(c=>c.tagName==='BUTTON').length]);
  out.histTitle=els.spkHistory.children[0].textContent;
  speakersResp={status:'ok',labels:[],suggestions:[],active:false,enrollment:true,history:[]};
  await hrows[0].children.find(c=>c.tagName==='BUTTON').onclick();
  out.undoPosted=posted.slice();out.undoToasts=toasts.slice();out.undoLoaded=loaded.slice();out.undoConfirms=confirms.slice();
  out.histAfter=els.spkHistory.children.length;
  speakersResp={status:'ok',labels:[],suggestions:[],active:false,enrollment:true,history:[],history_error:true};
  await openSpeakerModal();
  out.histErr=els.spkHistory.children.map(c=>c.textContent);
  speakersResp={status:'ok',labels:[{label:'太郎?',count:2,example:'x',samples:2,named:true,tentative:true,suggested:'太郎',auto:2},
    {label:'次郎',count:3,example:'y',samples:3,named:true,tentative:false,suggested:'',auto:2},
    {label:'三郎',count:1,example:'z',samples:1,named:true,tentative:false,suggested:'',auto:0}],
    suggestions:[],active:false,enrollment:true,history:[]};
  await openSpeakerModal();out.autoRows=els.spkRows.children.map(r=>r.innerHTML);
  speakersResp.enrollment=false;await openSpeakerModal();out.autoRowsOff=els.spkRows.children.map(r=>r.innerHTML);
  groupInputs=[];personInputs=[];
  inputs=[{dataset:{label:'太郎?',named:'1',suggested:'太郎'},value:''},{dataset:{label:'次郎',named:'1'},value:''},{dataset:{label:'三郎',named:'1'},value:''}];
  acceptInputs=[{dataset:{acceptFor:'太郎?'},checked:true}];
  confirmInputs=[{dataset:{confirmFor:'次郎'},checked:true}];
  out.confirmMapping=speakerMapping();
  confirmInputs=[{dataset:{confirmFor:'次郎'},checked:false}];
  out.unconfirmedMapping=speakerMapping();
  inputs=[{dataset:{label:'次郎',named:'1'},value:'四郎'}];confirmInputs=[{dataset:{confirmFor:'次郎'},checked:true}];
  out.renamedConfirm=speakerMapping();
  confirmInputs=[];
  inputs=[{dataset:{label:'太郎?',named:'1',suggested:'太郎'},value:''},{dataset:{label:'相手A',named:'0'},value:'次郎'}];
  personInputs=[{dataset:{personFor:'太郎?',orig:'1',touched:'1'},checked:true}];
  acceptInputs=[{dataset:{acceptFor:'太郎?'},checked:false}];
  out.tentUntouched=speakerMapping();
  personInputs=[];acceptInputs[0].checked=true;out.tentAccepted=speakerMapping();
  acceptInputs[0].checked=false;inputs[0].value=' 花子 ';out.tentTyped=speakerMapping();
  acceptInputs[0].checked=true;out.tentTypedAccepted=speakerMapping();
  const ln=(s,label)=>({dataset:{ts:'2026-10-09 10:00:0'+s,raw:'[2026-10-09 10:00:0'+s+'] ['+label+'] x'}});
  tpLines=[ln(1,'相手A'),ln(2,'相手B'),ln(3,'自分'),ln(4,'相手?'),ln(5,'相手A'),ln(6,'Claude'),ln(7,'相手B')];
  const scopeView=()=>[els.rlScopeLinesText.textContent,!!els.rlScopeRangeOpt.hidden,!!els.rlScopeLabelOpt.hidden,
    !!els.rlScopeLines.checked,els.rlTarget.textContent];
  const pickScope=k=>{for(const s of ['Lines','Range','Label'])els['rlScope'+s].checked=s===k;updateRlTarget();return els.rlTarget.textContent;};
  const F='transcript-202610091000.txt';
  selected=[tpLines[0]];await openRelabelModal();out.sc1=scopeView();out.sc1Label=pickScope('Label');
  selected=[tpLines[1],tpLines[4]];await openRelabelModal();out.sc2=scopeView();
  out.sc2Range=pickScope('Range');out.sc2Label=pickScope('Label');out.sc2Back=pickScope('Lines');
  pickScope('Range');posted.length=0;els.rlName.value='bob';await saveRelabel();out.rangePosted=posted[0];
  selected=[tpLines[1],tpLines[4]];await openRelabelModal();pickScope('Label');posted.length=0;toasts.length=0;
  els.rlName.value='acme';els.rlGroup.value='acme';els.rlGroup.dataset.touched='1';els.rlPerson.checked=false;onRlPersonChange();
  await saveRelabel();out.labelPosted=posted.slice(0,2);
  selected=[tpLines[0],tpLines[3],tpLines[6]];await openRelabelModal();out.sc3=scopeView();out.sc3Label=pickScope('Label');
  posted.length=0;toasts.length=0;els.rlName.value='bob';await saveRelabel();
  out.looseOk=[posted.slice(0,2),toasts.slice()];
  selected=[tpLines[0],tpLines[3]];await openRelabelModal();pickScope('Label');
  posted.length=0;toasts.length=0;alerts.length=0;postResp.push({status:'ok',message:'FIRST'},{status:'error',message:'NG'});
  els.rlName.value='bob';await saveRelabel();out.looseNg=[posted.length,toasts.slice(),alerts.slice(),els.relabelModal.classList.open];
  selected=[tpLines[2],tpLines[4]];await openRelabelModal();out.selfRange=pickScope('Range');
  out.selfLabel=pickScope('Label');posted.length=0;toasts.length=0;els.rlName.value='bob';await saveRelabel();
  out.selfLabelPosted=posted.slice(0,2).map(p=>p.body.lines);
  selected=[tpLines[3]];await openRelabelModal();out.scUnk=scopeView();out.rlInfoPlain=els.rlInfo.textContent;
  selected=[tpLines[1],tpLines[1]];await openRelabelModal();out.scSame=scopeView();
  // 録音中の会議: モーダルに仮登録を入れ直し、空欄にしたラベルは "" で送って取り消す
  inputs=[{dataset:{label:'相手A',named:'0'},value:''},{dataset:{label:'相手B',named:'0'},value:''}];
  groupInputs=[{dataset:{groupFor:'相手A',orig:''},value:''}];personInputs=[{dataset:{personFor:'相手A',orig:'1'},checked:true}];
  speakersResp={status:'ok',labels:[{label:'相手A',count:1,example:'x',samples:0},{label:'相手B',count:1,example:'y',samples:0}],
    suggestions:[],active:true,translating:true,enrollment:true,
    provisional:{labels:{'相手A':'acme'},lines:{},raw_labels:{'相手A':{name:'acme',group:'acme',person:false}}}};
  await openSpeakerModal();
  out.provFilled=[inputs[0].value,groupInputs[0].value,personInputs[0].checked,els.spkSaveBtn.disabled,els.spkInfo.textContent];
  inputs[0].value='';posted.length=0;loaded.length=0;postResp.push({status:'ok',provisional:true,message:'PROV'});
  await saveSpeakers();
  out.provCleared=[posted[0],loaded.slice()];
  selected=[{dataset:{raw:'[2026-10-09 10:00:01] [相手A] x'}}];
  await openRelabelModal();
  out.rlProv=[els.rlInfo.textContent,els.rlSaveBtn.disabled];
  els.rlName.value='';posted.length=0;postResp.push({status:'ok',provisional:true,message:'PROV'});
  await saveRelabel();
  out.rlProvCancel=posted[0];
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
      out["mapping"] == {"相手A": {"name": "太郎", "person": True},
                         "次郎": {"name": "次郎", "group": "自社"}}, repr(out["mapping"]))
check("個人のチェックを外してグループを入れたら person:false と group を送る",
      out["uncheckedGroup"] == {"相手A": {"name": "太郎", "group": "acme", "person": False}}, repr(out["uncheckedGroup"]))
check("チェックを入れ直したら group は送らない",
      out["recheckedNoGroup"] == {"相手A": {"name": "太郎", "person": True}}, repr(out["recheckedNoGroup"]))
check("assign に file と mapping を送る", out["posted"] == {"url": "/api/speakers/assign",
      "body": {"file": "transcript-202610091000.txt", "mapping": {"相手A": {"name": "太郎"}}}},
      repr(out["posted"]))
check("保存後にトーストと再読み込み", out["toasts"][:2] == ["2 行に名前を付けました", "STARTED"]
      and out["loaded"][:2] == ["T:transcript-202610091000.txt", "R:transcript-202610091000.txt"],
      repr((out["toasts"], out["loaded"])))
check("翻訳中は保存できない", out["trInfo"] == "TRANSLATING" and out["trDisabled"] is True)
check("録音中の日次ファイルは保存できない（日次ファイル用の文言）", out["activeInfo"] == "DAILY" and out["activeDisabled"] is True)
check("録音中かつ翻訳中は保存できない", out["bothInfo"] == "DAILY" and out["bothDisabled"] is True)
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
check("名前の入力で個人チェックとグループ表示が追従する", out["typing"] == [[False, "", False], [True, "acme", True], [False, "", False], [True, "", True]]
      and out["typingTouched"] == [False, "x", False], repr((out["typing"], out["typingTouched"])))
check("チェックの切り替えでグループ欄が出入りする", out["toggleHidden"] == [True, "1"] and out["toggleShown"] is False,
      repr((out["toggleHidden"], out["toggleShown"])))
check("行の描画: 個人の行はグループ欄を隠し、個人でない行は出す",
      'data-group-for="相手A"' in out["rowHtml"] and ' hidden' in out["rowHtml"].split('data-group-for')[1].split('>')[0]
      and ' hidden' not in out["hiddenRowHtml"].split('data-group-for')[1].split('>')[0], repr((out["rowHtml"], out["hiddenRowHtml"])))
check("付け替え: 開いた時は個人・未編集・グループ欄は隠す", out["rlOpen"] == [True, "", True], repr(out["rlOpen"]))
check("付け替え: 名前に追従", out["rlTaro"] == [True, "acme", True] and out["rlHanako"] == [False, "", False] and out["rlNew"] == [True, "", True],
      repr((out["rlTaro"], out["rlHanako"], out["rlNew"])))
check("付け替え: 触っていなければ group/person は送らない", out["relabelUntouched"]["body"] == {
      "file": "transcript-202610091000.txt", "lines": [{"ts": "2026-10-09 10:00:05", "label": "相手A"},
                                                       {"ts": "2026-10-09 10:00:06", "label": "自分"}], "name": "太郎"},
      repr(out["relabelUntouched"]))
check("付け替え: チェックの切り替えでグループ欄が出入りし、入れ直したら group は送らない",
      out["rlToggle"] == [False, "1"] and out["rlToggleBack"] is True and "group" not in out["relabelRechecked"]["body"]
      and out["relabelRechecked"]["body"]["person"] is True, repr((out["rlToggle"], out["rlToggleBack"], out["relabelRechecked"])))
check("保存後に議事録の再生成を確認して頼む", out["regenPosted"] == {"url": "/api/summary",
      "body": {"file": "transcript-202610091000.txt"}}, repr(out["regenPosted"]))
check("登録済みの人: 名簿の個人（声紋0件も）と声紋のある人を名前順に出し、個人でないラベルは出さない",
      out["people"] == [["三郎 (0)", 5, ""], ["太郎 (3)", 5, "acme"], ["次郎 (1)", 5, ""]]
      and out["grpSuggest"] == ["acme"], repr((out["people"], out["grpSuggest"])))
check("登録済みの人: グループ欄の変更で speaker-groups/set を送る",
      out["vpSet"] == {"url": "/api/speaker-groups/set", "body": {"name": "太郎", "group": "globex"}}, repr(out["vpSet"]))
check("名簿を読めなくても声紋のある人は出し、グループ欄なし・alert なし",
      out["peopleErr"] == [["太郎 (3)", 4], ["次郎 (1)", 4]] and out["peopleErrAlerts"] == [], repr((out["peopleErr"], out["peopleErrAlerts"])))
check("付け替え: 不明な話者（相手?）の行も対象にし、Claude の行は除く",
      out["rlUnknown"] == [{"ts": "2026-10-09 10:00:07", "label": "相手?"}], repr(out["rlUnknown"]))
check("履歴: 見出しと行を出し、未取り消しの行にだけ取り消すボタン",
      out["histTitle"] == "HISTORY" and [b for _, b in out["hist"]] == [1, 0]
      and "2026-10-09 11:00:00" in out["hist"][0][0] and "相手B → 太郎" in out["hist"][0][0]
      and "発話 3 件" in out["hist"][0][0] and "声紋 2 件" in out["hist"][0][0]
      and "UNDONE" in out["hist"][1][0] and "相手A → acme" in out["hist"][1][0], repr(out["hist"]))
check("履歴: 取り消すは確認して file と id を送り、トースト・再読み込み・議事録の再生成",
      out["undoConfirms"][0] == "相手B → 太郎 を取り消す？"
      and out["undoPosted"][0] == {"url": "/api/speakers/undo", "body": {"file": "transcript-202610091000.txt", "id": "h2"}}
      and out["undoPosted"][1]["url"] == "/api/summary" and out["undoToasts"][0] == "2 行に名前を付けました"
      and out["undoLoaded"] == ["T:transcript-202610091000.txt", "R:transcript-202610091000.txt"],
      repr((out["undoConfirms"], out["undoPosted"], out["undoToasts"], out["undoLoaded"])))
check("履歴: 取り消し後はモーダルを開き直して最新の履歴（空なら何も出さない）", out["histAfter"] == 0, repr(out["histAfter"]))
check("履歴: 読めないときは空ではなくエラーを出す", out["histErr"] == ["HISTERR"], repr(out["histErr"]))
check("test_tentative_placeholder: 名前?の行は名前を placeholder に出し（値は空）、未確定と出し、確認チェックは出さない",
      'data-label="太郎?"' in out["autoRows"][0] and 'placeholder="太郎"' in out["autoRows"][0]
      and 'data-suggested="太郎"' in out["autoRows"][0] and 'value="太郎"' not in out["autoRows"][0]
      and "TENTATIVE" in out["autoRows"][0] and "data-confirm-for" not in out["autoRows"][0]
      and "TENTATIVE" not in out["autoRows"][1], repr(out["autoRows"]))
check("test_tentative_accept_checkbox: 名前?の行に未チェックの「名前として確定」、ほかの行には出さない",
      'data-accept-for="太郎?"' in out["autoRows"][0] and "ACCEPT 太郎" in out["autoRows"][0]
      and ' checked' not in out["autoRows"][0].split('data-accept-for')[1].split('>')[0]
      and all("data-accept-for" not in h for h in out["autoRows"][1:]), repr(out["autoRows"]))
check("test_tentative_sent_only_when_accepted: 触らずに保存したら名前?の行は送らず、チェックで送り、入力した名前はそのまま送る",
      out["tentUntouched"] == {"相手A": {"name": "次郎"}}
      and out["tentAccepted"] == {"太郎?": {"name": "太郎"}, "相手A": {"name": "次郎"}}
      and out["tentTyped"] == {"太郎?": {"name": "花子"}, "相手A": {"name": "次郎"}}
      and out["tentTypedAccepted"] == out["tentTyped"],
      repr((out["tentUntouched"], out["tentAccepted"], out["tentTyped"], out["tentTypedAccepted"])))
check("test_auto_confirm_checkbox_posts_confirm: 自動識別のある名前付け済みの行に確認チェック",
      'data-confirm-for="次郎"' in out["autoRows"][1] and "CONFIRM 2" in out["autoRows"][1]
      and ' checked' not in out["autoRows"][1].split('data-confirm-for')[1].split('>')[0]
      and "data-confirm-for" not in out["autoRows"][2]
      and all("data-confirm-for" not in h for h in out["autoRowsOff"]), repr((out["autoRows"], out["autoRowsOff"])))
check("test_auto_confirm_checkbox_posts_confirm: チェックしたら confirm を送り、外したら送らない",
      out["confirmMapping"] == {"太郎?": {"name": "太郎"}, "次郎": {"name": "次郎", "confirm": True}}
      and out["unconfirmedMapping"] == {"太郎?": {"name": "太郎"}}
      and out["renamedConfirm"] == {"次郎": {"name": "四郎"}},
      repr((out["confirmMapping"], out["unconfirmedMapping"], out["renamedConfirm"])))
check("test_color_for_tentative_uses_name: 名前?は名前のグループ色、相手?は色なし",
      out["tentColor"] == "#e57373" and out["unkTent"] == "", repr((out["tentColor"], out["unkTent"])))
check("test_color_mirrors_server_tentative_rule: 自分?・相手A?・Claude?・? は名前?として扱わない",
      out["notTent"] == ["", "", "", ""], repr(out["notTent"]))
check("対象: 1 行なら「この行だけ」（既定）と「この話者の行を全部」、件数を出す",
      out["sc1"] == ["ONE", True, False, True, "LINES 1"] and out["sc1Label"] == "LABEL 相手A 2", repr((out["sc1"], out["sc1Label"])))
check("対象: 2 行なら「この 2 行だけ」「2 行の間を全部」「この話者の行を全部」、切り替えで件数が変わる",
      out["sc2"] == ["TWO", False, False, True, "LINES 2"] and out["sc2Range"] == "RANGE 3"
      and out["sc2Label"] == "LABEL 相手B / 相手A 4" and out["sc2Back"] == "LINES 2",
      repr((out["sc2"], out["sc2Range"], out["sc2Label"], out["sc2Back"])))
check("自分の行: 端が自分なら範囲に自分の行も数え、この話者の行を全部では 1 行ずつ送る",
      out["selfRange"] == "RANGE 3" and out["selfLabel"].startswith("LABEL 相手A ")
      and [{"ts": "2026-10-09 10:00:03", "label": "自分"}] in out["selfLabelPosted"],
      repr((out["selfRange"], out["selfLabel"], out["selfLabelPosted"])))
check("範囲: 2 行の間を全部は assign-lines に scope range で 2 行を送る", out["rangePosted"] == {
      "url": "/api/speakers/assign-lines", "body": {"file": "transcript-202610091000.txt", "name": "bob", "scope": "range",
      "lines": [{"ts": "2026-10-09 10:00:02", "label": "相手B"}, {"ts": "2026-10-09 10:00:05", "label": "相手A"}]}},
      repr(out["rangePosted"]))
check("対象: この話者の行を全部は assign にラベルごとの mapping（group/person 付き）を送る", out["labelPosted"] == [{
      "url": "/api/speakers/assign", "body": {"file": "transcript-202610091000.txt", "mapping": {
          "相手B": {"name": "acme", "group": "acme", "person": False},
          "相手A": {"name": "acme", "group": "acme", "person": False}}}},
      {"url": "/api/summary", "body": {"file": "transcript-202610091000.txt"}}], repr(out["labelPosted"]))
check("対象: 3 行以上なら「選んだ行だけ」とこの話者の行を全部。相手? の行は件数に 1 行ずつ足す",
      out["sc3"] == ["MANY", True, False, True, "LINES 3"] and out["sc3Label"] == "LABEL 相手A / 相手B 5",
      repr((out["sc3"], out["sc3Label"])))
check("対象: 相手? の選択行は assign のあと assign-lines で行単位に送り、両方のメッセージを出す", out["looseOk"] == [[
      {"url": "/api/speakers/assign", "body": {"file": "transcript-202610091000.txt",
                                                "mapping": {"相手A": {"name": "bob"}, "相手B": {"name": "bob"}}}},
      {"url": "/api/speakers/assign-lines", "body": {"file": "transcript-202610091000.txt", "name": "bob",
                                                      "lines": [{"ts": "2026-10-09 10:00:04", "label": "相手?"}]}}],
      ["2 行に名前を付けました 2 行に名前を付けました", "STARTED"]], repr(out["looseOk"]))
check("対象: 2 回目が失敗したら 1 回目の結果をトーストし、失敗を alert する",
      out["looseNg"] == [2, ["FIRST"], ["NG"], False], repr(out["looseNg"]))
check("対象: 相手? だけを選んだらこの話者の行を全部は出さない", out["scUnk"] == ["ONE", True, True, True, "LINES 1"],
      repr(out["scUnk"]))
check("範囲: 同じ行（時刻とラベル）が 2 つでは 2 行の間を全部は出さない", out["scSame"][1] is True, repr(out["scSame"]))
check("対象: rlInfo は件数を繰り返さず、録音中・翻訳中の警告だけ出す", out["rlInfoPlain"] == "", repr(out["rlInfoPlain"]))
check("誰もいなければ空表示", out["peopleNone"] == [0, "EMPTY"], repr(out["peopleNone"]))
check("仮登録: 録音中の会議ではモーダルに仮登録を入れ直し、翻訳中でも保存できる",
      out["provFilled"] == ["acme", "acme", False, False, "PROVINFO"], repr(out["provFilled"]))
check("仮登録: 空欄にしたラベルは \"\" で送り、transcript は読み直さない", out["provCleared"] == [
      {"url": "/api/speakers/assign", "body": {"file": "transcript-202610091000.txt", "mapping": {"相手A": ""}}}, []],
      repr(out["provCleared"]))
check("仮登録: 行の付け替えも保存でき、案内を出す", out["rlProv"] == ["PROVHINT", False], repr(out["rlProv"]))
check("仮登録: 名前を空欄にして保存すると、選んだ行の取り消しを送る", out["rlProvCancel"] == {
      "url": "/api/speakers/assign-lines", "body": {"file": "transcript-202610091000.txt", "name": "",
                                                     "lines": [{"ts": "2026-10-09 10:00:01", "label": "相手A"}]}},
      repr(out["rlProvCancel"]))
sys.exit(0 if all(results) else 1)
