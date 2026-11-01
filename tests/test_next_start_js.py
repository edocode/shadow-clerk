"""/next の会議開始モーダルと会議の終了を node で検証する

- AI アシスタントのチェックの初期値: 会議の analyze が true / false ならそれ、null なら auto_analyze
- 説明文は 3 通り（試作 updStartCfg の文言）
- 開始の本文: 常に /api/meeting {name, analyze: チェックの値}（名前が空なら daemon が予定の名前を付ける）
- 言語を変えられなければ始めない。押した時点で会議中なら言語も変えず始めない。終了に失敗したら終了のトーストを出さない
- 進行中の予定があれば名前を入れる。終了は確認なしで end_meeting

実行: uv run python tests/test_next_start_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_next_js_core import _NEXT_JS_CORE
from shadow_clerk._daemon_dashboard_next_js_extract import _NEXT_JS_EXTRACT
from shadow_clerk._daemon_dashboard_next_js_list import _NEXT_JS_LIST
from shadow_clerk._daemon_dashboard_next_js_start import _NEXT_JS_START
from shadow_clerk._daemon_dashboard_next_js_transcript import _NEXT_JS_TRANSCRIPT
from shadow_clerk.i18n import STRINGS

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_PRE = "const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";\n" + r"""
const mkEl=()=>({textContent:'',innerHTML:'',className:'',title:'',style:{},dataset:{},value:'',checked:false,disabled:false,
  children:[],options:[],
  classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
    toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
  handlers:{},addEventListener(t,f){(this.handlers[t]=this.handlers[t]||[]).push(f);},setAttribute(){},getAttribute(){return null;},
  appendChild(c){this.children.push(c);},querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},
  focus(){},select(){},remove(){}});
const els={};
const document={getElementById:id=>els[id]||(els[id]=mkEl()),createElement:mkEl,querySelectorAll:()=>[],querySelector:()=>null,
  addEventListener(){},body:mkEl(),documentElement:mkEl()};
const localStorage={getItem(){return null;},setItem(){}};
const location={hash:'',pathname:'/next',search:''};
const history={replaceState(){}};
const window={addEventListener(){},innerWidth:1000,innerHeight:700};
const timers=[];
const setTimeout=f=>{timers.push(f);return timers.length;};
const clearTimeout=()=>{};
const setInterval=()=>0;
const posts=[],gets=[];
const NOW=Date.now();
const iso=ms=>new Date(ms).toISOString();
const MOCK={status:{running:true,session:null,language:'ja'},auto:true,rules:{},events:[],
  meetingResp:{status:'ok',meeting:'週次定例',transcript:'/d/transcript-202610311000@週次定例.txt',in_meeting:true}};
const fetch=async (url,opt)=>{
  const ok=v=>({json:async()=>JSON.parse(JSON.stringify(v))});
  if(opt&&opt.method==='POST'){
    const b=JSON.parse(opt.body);posts.push([url,b]);
    if(url==='/api/meeting')return ok(MOCK.meetingResp);
    if(url==='/api/command'&&MOCK.failCmd)return ok({status:'error'});
    return ok({status:'ok'});
  }
  gets.push(url);
  if(url.startsWith('/api/status'))return ok(MOCK.status);
  if(url.startsWith('/api/config'))return ok({auto_analyze:MOCK.auto});
  if(url.startsWith('/api/gcal-events'))return ok({enabled:true,events:MOCK.events});
  if(url.startsWith('/api/meeting-settings')){
    const name=decodeURIComponent(url.split('meeting=')[1]||'');
    return ok({status:'ok',path:'/x',meetings:[{name,matched:'(defaults)',shared:false,analyze:null,publish:true,
      workdir:'',publish_to:'artifact',notion_url:'',publish_advice:false,...(MOCK.rules[name]||{})}]});
  }
  if(url.startsWith('/api/files'))return ok({files:[],active:'',file_info:{}});
  return ok({lines:[]});
};
class EventSource{constructor(){this.h={};}addEventListener(t,f){(this.h[t]=this.h[t]||[]).push(f);}close(){}}
const tick=()=>new Promise(r=>setImmediate(r));
const settle=async()=>{for(let i=0;i<10;i++)await tick();};
const click=id=>(els[id].handlers.click||[]).forEach(f=>f({preventDefault(){},stopPropagation(){}}));
const typeName=async v=>{els.nxStName.value=v;(els.nxStName.handlers.input||[]).forEach(f=>f({}));
  timers.splice(0).forEach(f=>f());await settle();};
"""

_BODY = r"""
(async()=>{
const out={};
nxInit();nxEs.onopen&&nxEs.onopen();await settle();
const reset=()=>{posts.length=0;MOCK.status.session=null;nxState.session=null;};
const open=async()=>{click('nxMeetingBtn');await settle();};
const view=()=>({checked:els.nxStAssist.checked,hint:els.nxStAssistHint.textContent,cfg:els.nxStCfg.textContent,
  name:els.nxStName.value,cal:els.nxStCal.textContent,lang:els.nxStLang.value,shown:els.nxStModal.classList.contains('show')});

/* 初期値: (auto_analyze, 会議の analyze) */
out.init={};
MOCK.rules={'週次定例':{analyze:true},'雑談':{analyze:false,publish:false},'acme':{publish_to:'notion',publish_advice:true,workdir:'/w'}};
for(const [auto,name] of [[true,'other'],[false,'other'],[false,'週次定例'],[true,'雑談'],[true,'acme']]){
  MOCK.auto=auto;await open();await typeName(name);out.init[auto+'/'+name]=view();
  nxModal('nxStModal',false);
}

/* 進行中の予定を名前に入れる（summary の無い予定は飛ばす） */
MOCK.auto=true;
MOCK.events=[{start:iso(NOW-3600e3),end:iso(NOW+3600e3)},{summary:'設計レビュー',start:iso(NOW-600e3),end:iso(NOW+600e3)}];
await open();out.cal=view();nxModal('nxStModal',false);
MOCK.events=[];
await open();out.nocal=view();nxModal('nxStModal',false);

/* 開始: 初期値どおり（オン） */
reset();await open();await typeName('週次定例');click('nxStOk');await settle();out.startOn=posts.slice();out.afterStart=view();
/* 開始: オンを外す → analyze:false */
reset();await open();await typeName('週次定例');els.nxStAssist.checked=false;click('nxStOk');await settle();out.startOff=posts.slice();
/* 開始: オフの会議でチェックを入れる → analyze:true（この回だけ） */
reset();await open();await typeName('雑談');els.nxStAssist.checked=true;click('nxStOk');await settle();out.startForce=posts.slice();
/* 開始: オフの会議でそのまま */
reset();await open();await typeName('雑談');click('nxStOk');await settle();out.startKeepOff=posts.slice();
/* 開始: 名前が空でも /api/meeting、言語を英語に */
reset();await open();await typeName('');els.nxStLang.value='en';click('nxStOk');await settle();out.startEmpty=posts.slice();
/* auto_analyze オフ・ルールなしでそのまま */
reset();MOCK.auto=false;await open();await typeName('');click('nxStOk');await settle();out.startAutoOffKeep=posts.slice();
/* 名前が空でオフからチェック（auto_analyze オフ）、言語を自動に */
reset();MOCK.auto=false;await open();await typeName('');els.nxStAssist.checked=true;els.nxStLang.value='auto';
click('nxStOk');await settle();out.startEmptyForce=posts.slice();
/* 言語の切り替えに失敗したら始めない */
reset();MOCK.auto=true;await open();await typeName('週次定例');els.nxStLang.value='en';MOCK.failCmd=true;
click('nxStOk');await settle();MOCK.failCmd=false;out.langFail=posts.slice();
/* ほかで会議が始まっていたら、言語を変えず会議も始めない */
reset();MOCK.auto=true;await open();await typeName('週次定例');els.nxStLang.value='en';
MOCK.status.session='/d/transcript-202610311000@別の会議.txt';
click('nxStOk');await settle();
out.alreadyIn={posts:posts.slice(),toast:els.nxToast.children.slice(-1).map(c=>c.textContent)};
/* キャンセル */
reset();await open();click('nxStCancel');await settle();out.cancel={posts:posts.slice(),shown:els.nxStModal.classList.contains('show')};

/* 終了: 確認なしで end_meeting とトースト */
reset();MOCK.status.session='/d/transcript-202610311000@週次定例.txt';await nxFetchStatus();
click('nxMeetingBtn');await settle();
out.end={posts:posts.slice(),toast:els.nxToast.children.slice(-1).map(c=>c.textContent),shown:els.nxStModal.classList.contains('show')};
/* 終了に失敗したら終了のトーストは出さない */
reset();MOCK.status.session='/d/transcript-202610311000@週次定例.txt';await nxFetchStatus();MOCK.failCmd=true;
click('nxMeetingBtn');await settle();MOCK.failCmd=false;
out.endFail=els.nxToast.children.slice(-1).map(c=>c.textContent);
console.log(JSON.stringify(out));
})().catch(e=>{console.error(e&&e.stack||e);process.exit(1);});
"""


def main() -> int:
    js = _PRE + _NEXT_JS_CORE + _NEXT_JS_LIST + _NEXT_JS_TRANSCRIPT + _NEXT_JS_EXTRACT + _NEXT_JS_START + _BODY
    proc = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        print(proc.stderr)
        check("node が動く", False)
        return 1
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    ja = STRINGS["ja"]
    init = out["init"]
    check("analyze 未指定・auto_analyze オン → チェックあり", init["true/other"]["checked"] is True, repr(init["true/other"]))
    check("analyze 未指定・auto_analyze オフ → チェックなし", init["false/other"]["checked"] is False)
    check("analyze オン → auto_analyze オフでもチェックあり", init["false/週次定例"]["checked"] is True)
    check("analyze オフ → auto_analyze オンでもチェックなし", init["true/雑談"]["checked"] is False)
    check("説明: ふだん", init["true/other"]["hint"] == ja["nx.st_hint_on"] == init["false/週次定例"]["hint"], repr(init["true/other"]))
    check("説明: auto_analyze オフ", init["false/other"]["hint"] == ja["nx.st_hint_auto_off"], init["false/other"]["hint"])
    check("説明: 会議でオフ", init["true/雑談"]["hint"] == ja["nx.st_hint_off"], init["true/雑談"]["hint"])
    check("説明文の文言（試作 updStartCfg）",
          ja["nx.st_hint_on"] == "決まったこと・宿題・確認が必要な点を「AI のアドバイス」に書き出します"
          and ja["nx.st_hint_auto_off"] == "設定で「会議開始時に分析」がオフです。チェックすると今回だけ起動します"
          and ja["nx.st_hint_off"] == "この会議は会議ごとの設定で「分析しない」です。チェックすると今回だけ起動します")
    check("この会議の設定: 既定のまま", ja["nx.st_cfg_none"] in init["true/other"]["cfg"], init["true/other"]["cfg"])
    check("この会議の設定: 分析しない・公開しない", ja["nx.st_chip_no_analyze"] in init["true/雑談"]["cfg"]
          and ja["nx.st_chip_no_publish"] in init["true/雑談"]["cfg"], init["true/雑談"]["cfg"])
    check("この会議の設定: 公開先・Advice・作業フォルダ", all(s in init["true/acme"]["cfg"] for s in
          (ja["nx.st_chip_notion"], ja["nx.st_chip_advice"], "/w")), init["true/acme"]["cfg"])
    check("進行中の予定（summary あり）を名前に入れる", out["cal"]["name"] == "設計レビュー"
          and out["cal"]["cal"] == "📅 カレンダーの予定から入力しました", repr(out["cal"]))
    check("予定が無ければ空", out["nocal"]["name"] == "" and out["nocal"]["cal"] == "", repr(out["nocal"]))
    check("話す言語は現在の言語から", out["cal"]["lang"] == "ja", repr(out["cal"]["lang"]))
    check("チェックありの初期値のままなら analyze を送らない（設定に従う）",
          out["startOn"] == [["/api/meeting", {"action": "start", "name": "週次定例"}]], repr(out["startOn"]))
    check("開始したらモーダルを閉じる", out["afterStart"]["shown"] is False)
    check("チェックを外したら analyze: false",
          out["startOff"] == [["/api/meeting", {"action": "start", "name": "週次定例", "analyze": False}]], repr(out["startOff"]))
    check("オフから入れたら analyze: true（この回だけ）",
          out["startForce"] == [["/api/meeting", {"action": "start", "name": "雑談", "analyze": True}]], repr(out["startForce"]))
    check("チェックなしの初期値のままなら analyze を送らない",
          out["startKeepOff"] == [["/api/meeting", {"action": "start", "name": "雑談"}]], repr(out["startKeepOff"]))
    check("名前が空でも /api/meeting、言語を変えたら先に set_language",
          out["startEmpty"] == [["/api/command", {"command": "set_language en"}],
                                ["/api/meeting", {"action": "start", "name": ""}]], repr(out["startEmpty"]))
    check("auto_analyze オフ・ルールなしでチェックなしのままなら analyze を送らない（後で手で起動しても監視できる）",
          out["startAutoOffKeep"] == [["/api/meeting", {"action": "start", "name": ""}]], repr(out["startAutoOffKeep"]))
    check("名前が空でオフから入れたら analyze: true、自動は unset_language",
          out["startEmptyForce"] == [["/api/command", {"command": "unset_language"}],
                                     ["/api/meeting", {"action": "start", "name": "", "analyze": True}]],
          repr(out["startEmptyForce"]))
    check("言語の切り替えに失敗したら始めない",
          out["langFail"] == [["/api/command", {"command": "set_language en"}]], repr(out["langFail"]))
    check("ほかで会議が始まっていたら言語を変えず会議も始めない（トーストで知らせる）",
          out["alreadyIn"] == {"posts": [], "toast": [ja.get("nx.st_already")]}, repr(out["alreadyIn"]))
    check("キャンセルは何も送らない", out["cancel"] == {"posts": [], "shown": False}, repr(out["cancel"]))
    check("終了は確認なしで end_meeting",
          out["end"]["posts"] == [["/api/command", {"command": "end_meeting"}]] and out["end"]["shown"] is False, repr(out["end"]))
    check("終了のトースト", out["end"]["toast"] == ["会議を終了しました。この後の会話は『今日のメモ』に残ります"], repr(out["end"]["toast"]))
    check("終了に失敗したら終了のトーストを出さない", out["endFail"] == [ja["nx.cmd_failed"]], repr(out["endFail"]))
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
