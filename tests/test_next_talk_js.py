"""/next の「Claude と会話」（開始モーダル・ヘッダのボタン・会議中の帯）を node で検証する

- 開始はモードを選ぶまで押せない。モード＝「自由に話す」か /api/talk-presets のモードで、select で選ぶ。「自由に話す」は消せない
- モードを選ぶと議題・ペルソナ・届け先・モデル・作業フォルダ・用語集・早めに返すが入る。「自由に話す」は開いたときの値に戻す
- 開始は現行の startTalk / talkPost をそのまま使う: 先にモデルを保存し、POST /api/talk-mode の本文は現行と同じ。
  届け先が使えない環境では route を送らない（tests/test_talk_route_js.py / test_talk_model_js.py と同じ項目）
- 声の届け先: 自分にだけ / 会議アプリにも。使えない環境では会議アプリを選べない。↻ は選んでいた先を保つ。
  覚えた先のアプリがいま音を出していなければ選ばない（/next だけ。現行はそのまま）
- モードの保存（POST /api/talk-presets）・削除（POST /api/talk-presets/delete）
- 会議中はヘッダのボタンが「Claude と会話を終了」、中央に帯。終了は POST /api/talk-mode {on:false}

実行: uv run python tests/test_next_talk_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_next_js import _NEXT_JS
from shadow_clerk.i18n import STRINGS

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


# 要素は id ごとに作る。select は innerHTML で選択肢が消え、value は選択肢に無ければ ''（本物の select と同じ）
_PRE = "const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";const PATH_HINTS={};\n" + r"""
function mkEl(id){
  const el={id:id||'',textContent:'',className:'',title:'',_v:'',checked:false,disabled:false,hidden:false,_h:'',
    style:{setProperty(){}},dataset:{},children:[],parentNode:null,scrollTop:0,scrollHeight:400,clientHeight:200,clientWidth:800,
    classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
      toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
    handlers:{},addEventListener(t,f){(this.handlers[t]=this.handlers[t]||[]).push(f);},setAttribute(){},getAttribute(){return null;},
    get innerHTML(){return this._h;},set innerHTML(v){this._h=v;this.children=[];},
    get options(){return this.children;},
    get value(){return this.isSel&&!this.children.some(o=>o.value===this._v)?'':this._v;},set value(v){this._v=String(v);},
    appendChild(c){this.children.push(c);c.parentNode=this;return c;},insertAdjacentHTML(p,h){this._h+=h;},
    querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},contains(){return false;},
    focus(){},select(){},remove(){},getBoundingClientRect(){return {left:0,top:0,right:800,bottom:40,width:800,height:200};}};
  return el;
}
const SELECTS=new Set(['talkRoute','talkModel','talkPersonaSel','talkPresetSel','voiceSpeaker','nxTalkMeetingExisting']);
const els={};
const document={getElementById:id=>els[id]||(els[id]=Object.assign(mkEl(id),{isSel:SELECTS.has(id)})),
  createElement:()=>mkEl(),querySelectorAll:()=>[],querySelector:()=>null,addEventListener(){},
  body:mkEl(),documentElement:mkEl(),visibilityState:'visible',createTreeWalker:()=>({nextNode:()=>null})};
const NodeFilter={SHOW_TEXT:4};
const localStorage={getItem(){return null;},setItem(){}};
const location={hash:'',pathname:'/next',search:''};
const history={replaceState(){}};
const window={addEventListener(){},innerWidth:1200,innerHeight:800,getSelection:()=>''};
const navigator={userActivation:{hasBeenActive:true},sendBeacon(){return true;},clipboard:{writeText:async()=>{}}};
const speechSynthesis={getVoices:()=>[],speak(){},cancel(){},addEventListener(){}};
class SpeechSynthesisUtterance{constructor(t){this.text=t;}}
const getComputedStyle=()=>({paddingLeft:'8px'});
const confirm=()=>true;
const setTimeout=()=>0;const clearTimeout=()=>{};const setInterval=()=>0;
class EventSource{constructor(){this.h={};}addEventListener(t,f){(this.h[t]=this.h[t]||[]).push(f);}close(){}}
const posts=[];
const TALK={active:false,engine:'console',topic:'',persona:'',route:{app:'',connected:false},error:''};
const MOCK={route:{available:true,targets:[{app:'Zoom',label:'Zoom'},{app:'Chromium',label:'Chromium'}]},
  cfg:{talk_personas:{'聞き上手':'よく聞く','やさしい先生':'ほめる'},talk_default_persona:'聞き上手',talk_workdir:'~/work',
    talk_model:'sonnet',talk_route_app:''},
  presets:[{name:'週次定例の準備',fields:{topic:'宿題の整理',persona:'やさしい先生',route:'Zoom',model:'opus',workdir:'/w/acme',
    glossary:false,early_reply:false}},{name:'英語の練習',fields:{topic:'カフェで注文',skill:'clerk-practice'}}],talkFail:false,meetingFail:false,session:null};
const fetch=async (url,opt)=>{
  const ok=v=>({json:async()=>JSON.parse(JSON.stringify(v))});
  if(opt&&opt.method==='POST'){
    const b=JSON.parse(opt.body);posts.push([url,b]);
    if(url==='/api/talk-mode'){
      if(b.on&&MOCK.talkFail)return ok({status:'error',message:'VOICEVOX に接続できません'});
      Object.assign(TALK,{active:!!b.on,topic:b.on?b.topic:'',persona:b.on?b.persona:'',route:{app:b.on&&b.route||'',connected:!!(b.on&&b.route)}});
      return ok({status:'ok',talk:TALK});
    }
    if(url==='/api/meeting')return ok(MOCK.meetingFail?{status:'error',message:'Meeting failed'}:{status:'ok'});
    if(url==='/api/talk-presets')MOCK.presets.push({name:b.name,fields:b.fields});
    if(url==='/api/talk-presets/delete')MOCK.presets=MOCK.presets.filter(p=>p.name!==b.name);
    return ok({status:'ok'});
  }
  if(url.startsWith('/api/status'))return ok({running:true,session:MOCK.session,console_running:false,talk_console_running:TALK.active,talk:TALK});
  if(url.startsWith('/api/config'))return ok(MOCK.cfg);
  if(url.startsWith('/api/talk-route-targets'))return ok(MOCK.route);
  if(url.startsWith('/api/talk-presets'))return ok({presets:MOCK.presets});
  if(url.startsWith('/api/skill-status'))return ok({bundled:'1.0.0',targets:[]});
  if(url.startsWith('/api/files'))return ok({files:['transcript-20261031.txt'],active:'transcript-20261031.txt',file_info:{}});
  return ok({lines:[]});
};
const tick=()=>new Promise(r=>setImmediate(r));
const settle=async()=>{for(let i=0;i<12;i++)await tick();};
const click=id=>(els[id].handlers.click||[]).forEach(f=>f({preventDefault(){},stopPropagation(){},target:els[id]}));
const change=(id,v)=>{if(v!==undefined)els[id].value=v;(els[id].handlers.change||[]).forEach(f=>f({target:els[id]}));};
"""

_BODY = r"""
(async()=>{
const out={};
await settle();
const view=()=>({open:els.talkModal.classList.contains('open'),ok:!els.nxTalkOk.disabled,topic:els.talkTopic.value,
  persona:els.talkPersonaSel.value,route:els.talkRoute.value,model:els.talkModel.value,workdir:els.talkWorkdir.value,
  glossary:els.talkGlossary.checked,early:els.talkEarlyReply.checked,
  app:els.nxTalkRouteApp.classList.contains('act'),appOff:els.nxTalkRouteApp.classList.contains('disabled'),
  modes:els.nxTalkModeSel.innerHTML,mode:els.nxTalkModeSel.value,delHidden:els.nxTalkModeDel.hidden,
  desc:els.nxTalkModeDesc.textContent,skill:els.talkSkill.value});
const talkPosts=()=>posts.filter(p=>p[0]==='/api/talk-mode'||p[0]==='/api/config').map(p=>p[0]==='/api/config'
  ?['config',p[1].talk_model,p[1].talk_route_app]:['talk',p[1]]);

out.btn0=[els.nxTalkLabel.textContent,els.nxTalkBtn.classList.contains('on'),els.nxTalkBand.classList.contains('show')];
/* 開く: モードを選ぶまで開始できない */
click('nxTalkBtn');await settle();out.opened=view();
/* 保存したモードを select で選ぶ */
change('nxTalkModeSel','m:週次定例の準備');out.preset=view();
/* 中身が一部だけのモードは、残りを開いたときの値に戻してから入れる */
nxPickTalkMode('英語の練習');out.partial=view();
posts.length=0;await startTalk();out.skillStart=talkPosts().filter(x=>x[0]==='talk').map(x=>x[1].skill);
await talkPost({on:false});click('nxTalkBtn');await settle();nxPickTalkMode('英語の練習');
/* 自由に話す: 開いたときの値 */
nxPickTalkMode('');out.free=view();

/* 声の届け先のラジオ */
change('nxTalkRouteAppIn');out.pickApp=view().route;
change('nxTalkRouteSelfIn');out.pickSelf=view().route;
els.talkRoute.value='Chromium';change('talkRoute');out.selApp=view().app;
/* ↻: 選んでいた先を保つ */
MOCK.route={available:true,targets:[{app:'Chromium',label:'Chromium'},{app:'Teams',label:'Teams'}]};
click('nxTalkRouteReload');await settle();out.reload=[view().route,els.talkRoute.options.map(o=>o.value)];
els.talkRoute.value='';click('nxTalkRouteReload');await settle();out.reloadSelf=view().route;

/* 開始: 現行と同じ本文。先にモデルを保存、あとで届け先を覚える */
MOCK.route={available:true,targets:[{app:'Zoom',label:'Zoom'}]};click('nxTalkRouteReload');await settle();
nxPickTalkMode('週次定例の準備');
posts.length=0;click('nxTalkOk');await settle();
out.start=talkPosts();out.afterStart=[els.talkModal.classList.contains('open'),els.nxTalkLabel.textContent,
  els.nxTalkBtn.classList.contains('on'),els.nxTalkBand.classList.contains('show'),els.nxTalkBandInfo.textContent,nxState.dtab];
/* 「会話はこの記録に出ます」は記録中のファイルを見ているときだけ */
out.where=[els.nxTalkBandWhere.hidden];
nxState.cur='transcript-20261030.txt';nxRenderAll();out.where.push(els.nxTalkBandWhere.hidden);
nxState.cur=nxActive;nxRenderAll();out.where.push(els.nxTalkBandWhere.hidden);

/* 会議中にヘッダのボタンを押すと終了 */
posts.length=0;click('nxTalkBtn');await settle();
out.end=[talkPosts(),els.nxTalkLabel.textContent,els.nxTalkBand.classList.contains('show'),els.nxToast.children[0].textContent];

/* 届け先が使えない環境: 会議アプリは選べず、route を送らない */
MOCK.route={available:false,targets:[]};MOCK.cfg.talk_route_app='Zoom';
click('nxTalkBtn');await settle();
nxPickTalkMode('週次定例の準備');out.unavail=view();
change('nxTalkRouteAppIn');out.unavailPick=view().route;
posts.length=0;click('nxTalkOk');await settle();out.unavailStart=talkPosts();
click('nxTalkBtn');await settle();
MOCK.cfg.talk_route_app='';

/* 開始に失敗: モーダルは開いたまま、理由を出す、ボタンはそのまま */
MOCK.talkFail=true;MOCK.route={available:true,targets:[]};
click('nxTalkBtn');await settle();nxPickTalkMode('');
click('nxTalkOk');await settle();
out.fail=[els.talkModal.classList.contains('open'),els.talkErr.textContent,els.nxTalkLabel.textContent,!els.nxTalkOk.disabled];
MOCK.talkFail=false;

/* モードとして保存: 現行の本文で POST /api/talk-presets、保存したモードを選んだ状態に */
els.talkTopic.value='新しい議題';
click('nxTalkSave');out.saveOpen=els.talkPresetModal.classList.contains('open');
els.talkPresetNameInput.value='acme 相談';
posts.length=0;click('nxTpOk');await settle();
out.save=[posts.map(p=>[p[0],p[1]]),els.talkPresetModal.classList.contains('open'),nxTalkMode,view().modes.includes('acme 相談')];

/* モードの削除: 確認してから POST /api/talk-presets/delete。選んでいたモードなら選び直し */
nxDelTalkMode('acme 相談');out.delAsk=[els.nxCfModal.classList.contains('show'),els.nxCfText.textContent];
posts.length=0;click('nxCfOk');await settle();
out.del=[posts.map(p=>[p[0],p[1]]),nxTalkMode,view().modes.includes('acme 相談'),view().ok,view().topic];
/* 覚えた届け先のアプリがいま音を出していなければ選ばない（自分にだけ）。出していれば選ぶ */
closeTalk();MOCK.route={available:true,targets:[{app:'Zoom',label:'Zoom'}]};MOCK.cfg.talk_route_app='Teams';
click('nxTalkBtn');await settle();out.stale=[view().route,view().app];closeTalk();
MOCK.cfg.talk_route_app='Zoom';click('nxTalkBtn');await settle();out.playing=[view().route,view().app];closeTalk();
MOCK.cfg.talk_route_app='';

await nxEndTalk();await nxOpenTalk();nxPickTalkMode('');
out.meetingOff=[nxTalkMeeting,els.nxTalkMeetingFields.hidden];
nxFiles=[{name:'transcript-202610311200@weekly.txt',meeting:'週次定例',dt:'202610311200'}];
nxFillTalkMeetings();
out.meetingOptions=els.nxTalkMeetingExisting.options.map(o=>o.textContent);
click('nxTalkMeeting');out.meetingOn=[nxTalkMeeting,els.nxTalkMeetingFields.hidden];
change('nxTalkMeetingExisting','週次定例');out.meetingSelected=els.nxTalkMeetingName.value;
click('nxTalkSave');els.talkPresetNameInput.value='会議付き';
posts.length=0;click('nxTpOk');await settle();
out.meetingSaved=posts.find(p=>p[0]==='/api/talk-presets')[1].fields;
nxPickTalkMode('英語の練習');
out.meetingLegacy=[nxTalkMeeting,els.nxTalkMeetingName.value,els.nxTalkMeetingFields.hidden,els.nxTalkMeetingExisting.value];
nxPickTalkMode('会議付き');
out.meetingRestored=[nxTalkMeeting,els.nxTalkMeetingName.value,els.nxTalkMeetingFields.hidden,els.nxTalkMeetingExisting.value];
nxPickTalkMode('');out.meetingFree=[nxTalkMeeting,els.nxTalkMeetingName.value];
nxPickTalkMode('会議付き');click('nxTalkMeeting');
click('nxTalkSave');els.talkPresetNameInput.value='会議なし';click('nxTpOk');await settle();
nxPickTalkMode('会議付き');nxPickTalkMode('会議なし');
out.meetingDisabled=[nxTalkMeeting,els.nxTalkMeetingName.value,els.nxTalkMeetingFields.hidden];
nxPickTalkMode('会議付き');closeTalk();await nxOpenTalk();nxPickTalkMode('会議付き');
out.meetingReopened=[nxTalkMeeting,els.nxTalkMeetingName.value];
posts.length=0;await nxStartTalk();
out.meetingStart=posts.filter(p=>p[0]==='/api/meeting'||p[0]==='/api/talk-mode');
await nxEndTalk();await nxOpenTalk();nxPickTalkMode('');click('nxTalkMeeting');
posts.length=0;await nxStartTalk();out.meetingBlank=[posts.length,els.talkErr.textContent,nxTalkBusy];
els.nxTalkMeetingName.value='相談';MOCK.meetingFail=true;
posts.length=0;await nxStartTalk();out.meetingFail=[posts.filter(p=>p[0]==='/api/talk-mode').length,els.talkErr.textContent];
MOCK.meetingFail=false;MOCK.session='active.txt';
posts.length=0;await nxStartTalk();out.meetingActive=[posts.length,els.talkErr.textContent];
MOCK.session=null;
await nxOpenTalk();nxPickTalkMode('英語の練習');nxState.rtab='sum';nxState.right=false;
await nxStartTalk();out.practiceTab=[nxState.rtab,nxState.right];
await nxEndTalk();await nxOpenTalk();nxPickTalkMode('');nxState.rtab='sum';nxState.right=false;
await nxStartTalk();out.plainTab=[nxState.rtab,nxState.right];
console.log(JSON.stringify(out));
})().catch(e=>console.log(JSON.stringify({bodyErr:String(e&&e.stack||e)})));
"""

r = subprocess.run(["node", "-e", "eval(require('fs').readFileSync(0,'utf8'))"], input=_PRE + _NEXT_JS + _BODY,
                   capture_output=True, text=True, timeout=60)
if r.returncode != 0 or not r.stdout.strip():
    check("node で実行できる", False, (r.stderr or r.stdout)[-800:])
    sys.exit(1)
out = json.loads(r.stdout.strip().splitlines()[-1])
if "bodyErr" in out:
    check("node で実行できる", False, out["bodyErr"][-800:])
    sys.exit(1)
ja = STRINGS["ja"]

check("会議中でなければヘッダは「Claude と会話」、帯は出さない", out["btn0"] == [ja["nx.talk_btn"], False, False], repr(out["btn0"]))
o = out["opened"]
check("開くと #talkModal が開き、モードを選ぶまで開始できない", o["open"] and not o["ok"], repr(o))
check("開いたときの値は現行と同じ（議題は空・既定のペルソナ・作業フォルダ・モデル・用語集オン）",
      [o["topic"], o["persona"], o["workdir"], o["model"], o["glossary"], o["early"], o["route"]]
      == ["", "聞き上手", "~/work", "sonnet", True, True, ""], repr(o))
check("モードは select で、まだ選んでいない・自由に話す・削除ボタンなし",
      o["mode"] == "" and ja["nx.talk_mode_pick"] in o["modes"] and o["delHidden"] and o["desc"] == "", repr(o))
check("モードの一覧は「自由に話す」と保存したモード",
      ja["nx.talk_free"] in o["modes"] and "週次定例の準備" in o["modes"] and "英語の練習" in o["modes"], o["modes"][:200])
p = out["preset"]
check("モードを選ぶと開始でき、削除ボタンと議題の説明が出る",
      p["ok"] and p["mode"] == "m:週次定例の準備" and not p["delHidden"] and p["desc"] == "宿題の整理", repr(p))
check("モードの議題・ペルソナ・届け先・モデル・作業フォルダ・用語集・早めに返すが入る",
      [p["topic"], p["persona"], p["route"], p["model"], p["workdir"], p["glossary"], p["early"], p["app"]]
      == ["宿題の整理", "やさしい先生", "Zoom", "opus", "/w/acme", False, False, True], repr(p))
p = out["partial"]
check("中身が一部のモードは、残りを開いたときの値にしてから入れる",
      [p["topic"], p["persona"], p["route"], p["model"], p["workdir"], p["glossary"]]
      == ["カフェで注文", "聞き上手", "", "sonnet", "~/work", True], repr(p))
f = out["free"]
check("「自由に話す」は開いたときの値に戻し、開始できる",
      [f["topic"], f["persona"], f["model"], f["workdir"], f["ok"]] == ["", "聞き上手", "sonnet", "~/work", True], repr(f))
check("「自由に話す」は消せない", f["delHidden"] and f["mode"] == "m:", repr(f))
check("モードの skill が入り、開始で送る。「自由に話す」は skill なし",
      out["partial"]["skill"] == "clerk-practice" and out["skillStart"] == ["clerk-practice"] and f["skill"] == "",
      repr([out["partial"]["skill"], out["skillStart"], f["skill"]]))
check("会議アプリにも → 先頭のアプリ、自分にだけ → 届け先なし",
      out["pickApp"] == "Zoom" and out["pickSelf"] == "", repr([out["pickApp"], out["pickSelf"]]))
check("一覧からアプリを選ぶと「会議アプリにも」になる", out["selApp"] is True, repr(out["selApp"]))
check("↻ はいまの音を出しているアプリを読み直し、選んでいた先を保つ",
      out["reload"] == ["Chromium", ["", "Chromium", "Teams"]], repr(out["reload"]))
check("↻ は「自分にだけ」を保つ", out["reloadSelf"] == "", repr(out["reloadSelf"]))
check("開始: 先にモデルを保存し、/api/talk-mode の本文は現行 startTalk と同じ、届け先を覚える",
      out["start"] == [["config", "opus", ""],
                       ["talk", {"on": True, "topic": "宿題の整理", "persona": "やさしい先生", "workdir": "/w/acme",
                                 "route": "Zoom", "glossary": False, "early_reply": False}],
                       ["config", "sonnet", "Zoom"]], repr(out["start"]))
a = out["afterStart"]
check("開始後: モーダルを閉じ、ヘッダは「Claude と会話を終了」、中央に会議中の帯、ドロワーは Claude と会話 の画面",
      a[0] is False and a[1] == ja["nx.talk_btn_end"] and a[2] and a[3] and a[5] == "talk", repr(a))
check("帯に議題・ペルソナ・届け先", "宿題の整理" in a[4] and "やさしい先生" in a[4] and "Zoom" in a[4], repr(a[4]))
e = out["end"]
check("会議中にヘッダのボタンを押すと {on:false} で終わり、表示を戻す",
      e[0] == [["talk", {"on": False}]] and e[1] == ja["nx.talk_btn"] and e[2] is False and e[3] == ja["nx.talk_ended"], repr(e))
u = out["unavail"]
check("使えない環境では会議アプリを選べず、モードの届け先も入らない",
      u["appOff"] and not u["app"] and u["route"] == "" and out["unavailPick"] == "", repr([u, out["unavailPick"]]))
check("使えない環境の開始は route を送らない",
      [x for x in out["unavailStart"] if x[0] == "talk"][0][1]["route"] is None, repr(out["unavailStart"]))
fl = out["fail"]
check("開始に失敗したらモーダルは開いたまま、理由を出し、ヘッダは変えない",
      fl == [True, "VOICEVOX に接続できません", ja["nx.talk_btn"], True], repr(fl))
check("「今の設定をモードとして保存」で名前の画面を開く", out["saveOpen"] is True)
s = out["save"]
check("保存は現行と同じ本文で POST /api/talk-presets、閉じて保存したモードを選ぶ",
      s[0] == [["/api/talk-presets", {"name": "acme 相談", "fields": {"topic": "新しい議題", "workdir": "~/work",
                                                                       "model": "sonnet", "persona": "聞き上手", "route": "",
                                                                       "glossary": True, "early_reply": True,
                                                                       "meeting": False, "meeting_name": "", "skill": ""}}]]
      and s[1] is False and s[2] == "acme 相談" and s[3], repr(s))
check("削除は確認を出す", out["delAsk"][0] and "acme 相談" in out["delAsk"][1], repr(out["delAsk"]))
d = out["del"]
check("削除は POST /api/talk-presets/delete、選んでいたモードなら選び直しになり開始できない",
      d[:4] == [[["/api/talk-presets/delete", {"name": "acme 相談"}]], None, False, False], repr(d))
check("選んでいたモードを消したら、入力は開いたときの値に戻る", d[4] == "", repr(d))
check("帯の「会話はこの記録に出ます」は記録中のファイルを見ているときだけ", out["where"] == [False, True, False],
      repr(out["where"]))
check("覚えた届け先のアプリが音を出していなければ「自分にだけ」", out["stale"] == ["", False], repr(out["stale"]))
check("覚えた届け先のアプリが音を出していれば選ぶ", out["playing"] == ["Zoom", True], repr(out["playing"]))
check("会議化は既定オフ、オンで入力を表示", out['meetingOff']==[False,True] and out['meetingOn']==[True,False])
check("既存会議を選ぶと名前を入力", '週次定例' in out['meetingOptions'] and out['meetingSelected']=='週次定例')
check("モードに会議のオンと会議名を保存", out['meetingSaved']['meeting'] is True
      and out['meetingSaved']['meeting_name']=='週次定例', repr(out['meetingSaved']))
check("古いモードは会議設定を初期化", out['meetingLegacy']==[False,'',True,''], repr(out['meetingLegacy']))
check("モードから会議のオン・名前・既存会議の選択を復元", out['meetingRestored']==[True,'週次定例',False,'週次定例'], repr(out['meetingRestored']))
check("自由に話すで会議設定を初期化", out['meetingFree']==[False,''], repr(out['meetingFree']))
check("オフの会議設定と名前も復元", out['meetingDisabled']==[False,'週次定例',True], repr(out['meetingDisabled']))
check("開き直して保存モードを選ぶと会議設定を復元", out['meetingReopened']==[True,'週次定例'], repr(out['meetingReopened']))
check("語学の練習は AI のタブを開き、ほかのモードは右ペインを変えない",
      out['practiceTab']==['ai',True] and out['plainTab']==['sum',False], repr((out['practiceTab'],out['plainTab'])))
check("会議の開始後に会話を開始",[p[0] for p in out['meetingStart']]==['/api/meeting','/api/talk-mode']
      and out['meetingStart'][0][1]=={'action':'start','name':'週次定例'}, repr(out['meetingStart']))
check("会議名未入力では開始せず再操作できる", out['meetingBlank']==[0,ja['nx.talk_meeting_required'],False], repr(out['meetingBlank']))
check("会議開始失敗時は会話を開始しない", out['meetingFail']==[0,'Meeting failed'], repr(out['meetingFail']))
check("すでに会議中なら別の会議を作らない", out['meetingActive']==[0,ja['nx.talk_meeting_active']], repr(out['meetingActive']))
sys.exit(0 if all(results) else 1)
