"""/next ダッシュボードの配信と、新 JS・i18n の規約

実行: uv run pytest -q tests/test_next_dashboard.py
"""
from __future__ import annotations

import io
import json
import re
import shutil
import subprocess

import pytest

from shadow_clerk._daemon_dashboard_handler import DashboardHandler
from shadow_clerk._daemon_dashboard_next_html import _NEXT_HTML_TEMPLATE
from shadow_clerk._daemon_dashboard_next_js import _NEXT_JS, _NEXT_JS_MODULES, _NEXT_JS_REUSED
from shadow_clerk._daemon_dashboard_next_js_shims import _NEXT_JS_SHIMS
from shadow_clerk.i18n import STRINGS


class _Get(DashboardHandler):
    def __init__(self, path: str) -> None:
        self.path = path
        self.client_address = ("127.0.0.1", 1)
        self.headers: dict = {}
        self.wfile = io.BytesIO()
        self.status = 0
        self.sent_headers: dict[str, str] = {}

    def send_response(self, code: int, message: str | None = None) -> None:
        self.status = code

    def send_header(self, keyword: str, value: str) -> None:
        self.sent_headers[keyword] = value

    def end_headers(self) -> None:
        pass

    def send_error(self, code: int, *_: object) -> None:
        self.status = code


def _get(path: str) -> tuple[_Get, str]:
    h = _Get(path)
    h.do_GET()
    return h, h.wfile.getvalue().decode("utf-8")


def test_root_serves_next() -> None:
    h, body = _get("/")
    assert h.status == 200 and h.sent_headers["Content-Type"].startswith("text/html")
    assert "{{i18n:" not in body and "const I18N=" in body
    assert 'id="nxMainHead"' in body and 'id="fsel"' not in body


def test_next_redirects_to_root() -> None:
    h, body = _get("/next")
    assert h.status == 302 and h.sent_headers["Location"] == "/" and body == ""


def test_legacy_serves_legacy() -> None:
    h, body = _get("/legacy")
    assert h.status == 200 and 'id="fsel"' in body


def test_next_i18n_keys_exist() -> None:
    src = _NEXT_HTML_TEMPLATE + _NEXT_JS
    keys = set(re.findall(r"\{\{i18n:(nx\.[^}]+)\}\}", src)) | set(re.findall(r"I18N\['(nx\.[^']+)'\]", src))
    assert keys
    for lang in ("ja", "en"):
        assert keys <= set(STRINGS[lang]), sorted(keys - set(STRINGS[lang]))


def _top_names(js: str) -> list[str]:
    return [a or b for a, b in re.findall(r"^(?:async\s+)?function\s+(\w+)|^(?:const|let|var)\s+(\w+)", js, re.M)]


def test_next_js_identifiers_prefixed() -> None:
    flat = _top_names(_NEXT_JS_MODULES)
    assert flat
    assert [n for n in flat if not n.startswith("nx")] == []


def test_no_name_collision() -> None:
    """shim 以外の nx* ・shim ・流用する現行モジュール（Claude と会議・設定・用語集などのモーダルを含む）のトップレベル名が重ならない。順は 新モジュール → shim → 流用 → 起動"""
    mods, shims, reused = (set(_top_names(js)) for js in (_NEXT_JS_MODULES, _NEXT_JS_SHIMS, _NEXT_JS_REUSED))
    assert shims and reused
    assert {"togTalk", "startTalk", "talkPost", "openPersonas", "openVoice", "doSaveTalkPreset"} <= reused
    assert {"openCfg", "saveCfg", "loadAudioDevices", "maybeShowWelcome", "maybeShowSkillUpdate", "openGlossary",
            "saveGlossary", "openCustomCmds", "saveCustomCmds", "openHelp", "openGcal"} <= reused
    assert {"openSpeakerModal", "saveSpeakers", "undoNaming", "loadVoiceprints", "deleteVoiceprint", "toggleVoiceprintClusters",
            "enrollSelfVoice", "exportVoiceprints", "importVoiceprints"} <= reused
    assert mods & reused == set() and shims & reused == set() and mods & shims == set()
    assert [n for n in shims if n.startswith("nx")] == []
    assert _NEXT_JS == _NEXT_JS_MODULES + _NEXT_JS_SHIMS + _NEXT_JS_REUSED + "nxInit();\n"


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い")
def test_next_js_parses() -> None:
    r = subprocess.run(["node", "-e", "new Function(require('fs').readFileSync(0,'utf8'))"],
                       input=_NEXT_JS, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


# /next の HTML にある id だけを持つ DOM。流用モジュールが無い要素を取りに行くと、読み込み時に TypeError で止まる
_DOM = r"""
const IDS=new Set(HTML_IDS);
const els={};
const posts=[];
const timers=[];
function mkEl(id){
  /* 本物の DOM と同じく、textContent を入れると子は消える */
  const el={id:id||'',_t:'',get textContent(){return this._t;},set textContent(v){this._t=String(v);this.children=[];},innerHTML:'',className:'',title:'',value:'',disabled:false,hidden:false,
    style:{setProperty(){}},dataset:{},children:[],parentNode:null,previousSibling:null,
    scrollTop:0,scrollHeight:400,clientHeight:200,clientWidth:800,offsetTop:0,handlers:{},
    classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
      toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
    addEventListener(t,f){(this.handlers[t]=this.handlers[t]||[]).push(f);},setAttribute(){},getAttribute(){return null;},
    appendChild(c){if(c.parentNode)c.parentNode.children=c.parentNode.children.filter(x=>x!==c);this.children.push(c);c.parentNode=this;return c;},
    insertBefore(c){return this.appendChild(c);},
    contains(x){for(let n=x;n;n=n.parentNode)if(n===this)return true;return false;},
    remove(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(x=>x!==this);this.parentNode=null;},
    insertAdjacentHTML(p,h){this.innerHTML+=h;},querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},
    focus(){},select(){},getBoundingClientRect(){return {left:0,top:0,right:800,bottom:40,width:800,height:200};}};
  return el;
}
const document={getElementById:id=>IDS.has(id)?(els[id]=els[id]||mkEl(id)):null,
  createElement:t=>Object.assign(mkEl(),{tagName:String(t||'').toUpperCase()}),createTextNode:t=>Object.assign(mkEl(),{textContent:t}),
  querySelectorAll:()=>[],querySelector:()=>null,handlers:{},addEventListener(t,f){(this.handlers[t]=this.handlers[t]||[]).push(f);},
  body:mkEl(),documentElement:mkEl(),visibilityState:'visible',
  createTreeWalker:()=>({nextNode:()=>null})};
const NodeFilter={SHOW_TEXT:4};
const localStorage={getItem(){return null;},setItem(){}};
const location={hash:'',pathname:'/next',search:''};
const history={replaceState(){}};
const window={addEventListener(){},innerWidth:1200,innerHeight:800,getSelection:()=>''};
const navigator={userActivation:{hasBeenActive:true},sendBeacon(){return true;},clipboard:{writeText:async()=>{}}};
const speechSynthesis={getVoices:()=>[{lang:'en-US'}],speak(){},cancel(){},addEventListener(){}};
class SpeechSynthesisUtterance{constructor(t){this.text=t;}}
const getComputedStyle=()=>({paddingLeft:'8px'});
let confirms=0;const confirm=()=>{confirms++;return true;};
const setTimeout=(fn,ms)=>{timers.push(fn);return timers.length;};
const clearTimeout=()=>{};const setInterval=()=>0;
const sources=[];
class EventSource{constructor(u){this.u=u;this.h={};sources.push(this);}addEventListener(t,f){(this.h[t]=this.h[t]||[]).push(f);}close(){}}
const fire=(t,d)=>sources[sources.length-1].h[t].forEach(f=>f({data:JSON.stringify(d)}));
const STATUS={running:true,session:null,console_running:true,console_transcript:null,talk_console_running:false};
/* ROUTES は前方一致する URL の応答（値か (url, body) => 値）。テストが足す */
const ROUTES={};
const fetch=async (url,opt)=>{
  const body=opt&&opt.method==='POST'?JSON.parse(opt.body):undefined;
  if(body)posts.push([url,body]);
  const rk=Object.keys(ROUTES).find(k=>url.startsWith(k)),rv=rk&&ROUTES[rk];
  const v=rk?(typeof rv==='function'?rv(url,body):rv):url.startsWith('/api/status')?STATUS:url.startsWith('/api/files')?{files:[],file_info:{}}
    :url.startsWith('/api/skill-status')?{bundled:'1.0.0',targets:[]}:{};
  return {json:async()=>JSON.parse(JSON.stringify(v))};
};
const tick=()=>new Promise(r=>Promise.resolve().then(()=>Promise.resolve().then(r)));
"""

_RESOLVE_BODY = r"""
(async()=>{
await tick();
const out={refErrors:[]};
const EV=Object.assign(mkEl(),{data:'{}',key:'a',target:mkEl(),preventDefault(){},stopPropagation(){},
  clipboardData:{getData:()=>'x'}});
/* 関数ごとに 1 回呼ぶだけなので、途中で TypeError になった関数はその先の名前を確かめていない。
   呼び出し先の名前は test_reused_calls_defined が静的にも見る */
for(const n of REUSED_NAMES){
  let f;
  try{f=eval(n);}catch(e){out.refErrors.push(n+': '+e.message);continue;}
  if(typeof f!=='function')continue;
  try{await f(EV,EV,EV);}catch(e){if(e instanceof ReferenceError)out.refErrors.push(n+': '+e.message);}
}
/* 端末は 1 つ。表示「AI アシスタントの画面」では中央、ドロワーでは選んだ役割の置き場所へ移す */
const row=document.getElementById('consoleRow');
nxSetView('CON');
out.con=[row.parentNode&&row.parentNode.id,_consoleRole,logTab,nxEl('nxMain').classList.contains('aiview'),nxState.bottom];
nxSetView('T');nxState.bottom=true;nxState.dtab='talk';nxRenderAll();
out.talk=[row.parentNode&&row.parentNode.id,_consoleRole];
nxState.dtab='ai';nxRenderAll();
out.ai=[row.parentNode&&row.parentNode.id,_consoleRole];
/* SSE は shim の es から現行の onConsoleEvent に届く */
fire('console',{role:'assistant',running:true,rows:{'0':[['hello','default']]},cursor:[0,5]});
out.consoleRows=Object.keys(_consoleRows).length;
/* 入力は現行のキー処理で /api/console/input へ（役割つき） */
posts.length=0;
document.getElementById('consoleInput').handlers.keydown.forEach(f=>f({key:'a',preventDefault(){}}));
document.getElementById('consoleInput').handlers.keydown.forEach(f=>f({key:'Enter',preventDefault(){}}));
await tick();await tick();
out.input=posts.filter(p=>p[0]==='/api/console/input').map(p=>p[1]);
/* 読み上げの印は AI のアドバイスのタブを描いたときだけ付ける */
const said=[];decorateSay=r=>said.push(r.id);
nxRtHtml='x';nxState.rtab='sum';nxRenderRight();
nxRtHtml='x';nxState.rtab='ai';nxRenderRight();
out.said=said;
/* 🔊 の言語: タグの無い ASCII の文は、いま聞き取っている言語（/api/status の language） */
STATUS.language='fr';await nxFetchStatus();
out.sayLang=sayLang('I see a cheap ship.',undefined);
/* CON のあいだ、ドロワーの Claude と会議 のタブは端末を出せないと知らせる */
nxSetView('CON');
out.talkNote=nxEl('nxDrawerNoteTalk').textContent;
/* Claude と会議: 流用する現行の togTalk が /next の #talkModal を開く。ペルソナ編集・声の設定は現行のモーダルの断片 */
document.getElementById('talkModal').classList.remove('open');
await nxOpenTalk();
out.talkOpen=[document.getElementById('talkModal').classList.contains('open'),nxEl('nxTalkOk').disabled];
await openPersonas();await openVoice();
out.talkSub=['personaModal','voiceModal'].map(id=>document.getElementById(id).classList.contains('open'));
/* その他 ▾ の現行モーダル: 流用する現行の関数が /next の HTML にある現行のモーダルの断片を開く */
const MODALS=['cfgModal','glossaryModal','customCmdModal','helpModal','gcalModal','welcomeModal'];
MODALS.forEach(id=>document.getElementById(id).classList.remove('open'));
await openCfg();await openGlossary();await openCustomCmds();openHelp();await openGcal();
await maybeShowWelcome();
out.legacyModals=MODALS.map(id=>document.getElementById(id).classList.contains('open'));
console.log(JSON.stringify(out));
})().catch(e=>console.log(JSON.stringify({bodyErr:String(e&&e.stack||e)})));
"""


def _run_next(body: str) -> dict:
    """/next の HTML の id だけを持つ DOM で _NEXT_JS を読み込み、body を走らせて最後の行の JSON を返す"""
    ids = re.findall(r'id=\\?"([^"\\]+)\\?"', _NEXT_HTML_TEMPLATE)
    pre = ("const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";const PATH_HINTS={};"
           + "const HTML_IDS=" + json.dumps(ids, ensure_ascii=False) + ";"
           + "const REUSED_NAMES=" + json.dumps(_top_names(_NEXT_JS_REUSED)) + ";\n" + _DOM)
    script = ("const src=require('fs').readFileSync(0,'utf8');"
              "try{new Function(src)();}catch(e){console.log(JSON.stringify({loadErr:String(e&&e.stack||e)}));}")
    r = subprocess.run(["node", "-e", script], input=pre + _NEXT_JS + body, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert "loadErr" not in out and "bodyErr" not in out, out
    return out


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い")
def test_welcome_takes_priority_over_skill_updates() -> None:
    out = _run_next(r"""
(async()=>{
  ROUTES['/api/skill-status']={bundled:'2.0.0',targets:[{name:'acme',state:'outdated',path:'/tmp/acme'}]};
  await tick();await tick();await tick();await tick();
  console.log(JSON.stringify({
    welcome:document.getElementById('welcomeModal').classList.contains('open'),
    update:document.getElementById('skillUpdateModal').classList.contains('open')}));
})().catch(e=>console.log(JSON.stringify({bodyErr:String(e)})));
""")
    assert out == {"welcome": True, "update": False}


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い")
def test_welcome_without_skill_service() -> None:
    out = _run_next(r"""
(async()=>{
  await tick();await tick();
  ROUTES['/api/skill-status']=()=>{throw new Error('unavailable');};
  await maybeShowWelcome();
  const html=document.getElementById('welcomeBody').innerHTML;
  const out={open:document.getElementById('welcomeModal').classList.contains('open'),html};
  closeWelcome();
  ROUTES['/api/config']={welcome_dismissed:true};
  await maybeShowWelcome();
  out.dismissed=!document.getElementById('welcomeModal').classList.contains('open');
  console.log(JSON.stringify(out));
})().catch(e=>console.log(JSON.stringify({bodyErr:String(e)})));
""")
    assert out["open"] and out["dismissed"]
    assert out["html"].count('class="wc-feature"') == 4
    assert '<details class="wc-setup">' in out["html"]
    assert '<details class="wc-setup" open' not in out["html"]
    assert "undefined" not in out["html"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い")
def test_reused_modules_resolve() -> None:
    """/next の HTML の要素だけで _NEXT_JS 全体が読み込め、流用モジュールの関数を呼んでも未定義の名前が出ない"""
    out = _run_next(_RESOLVE_BODY)
    assert out["refErrors"] == []
    assert 'id="nxConsoleAi"><div id="consoleRow">' in _NEXT_HTML_TEMPLATE
    assert out["con"] == ["nxConsoleMain", "assistant", "console", True, False]
    assert out["talk"] == ["nxConsoleTalk", "talk"]
    assert out["ai"] == ["nxConsoleAi", "assistant"]
    assert out["consoleRows"] >= 1
    assert out["input"] == [{"role": "assistant", "data": "a"}, {"role": "assistant", "data": "\r"}]
    assert out["said"] == ["nxRightBody"]
    assert out["sayLang"] == "fr"
    assert out["talkNote"] == STRINGS["ja"]["nx.d_talk_con"]
    assert out["talkOpen"] == [True, True]
    assert out["talkSub"] == [True, True]
    assert out["legacyModals"] == [True] * 6


_JS_GLOBALS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "new", "fetch", "alert", "confirm",
               "setTimeout", "clearTimeout", "setInterval", "getComputedStyle", "parseInt", "parseFloat", "String", "Number",
               "Boolean", "Object", "JSON", "Math", "Promise", "Set", "RegExp", "Date", "Array", "ResizeObserver",
               "SpeechSynthesisUtterance", "await", "of", "async", "isNaN"}


def test_reused_calls_defined() -> None:
    """流用モジュールが呼ぶ名前は、_NEXT_JS のトップレベル・その関数の引数やローカル・ブラウザの組み込みのどれか"""
    code = re.sub(r"/\*.*?\*/", "", _NEXT_JS_REUSED, flags=re.S)
    code = re.sub(r"(?m)//.*$", "", code)
    code = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"", "''", code)
    called = set(re.findall(r"(?<![.\w$])([A-Za-z_$][\w$]*)\s*\(", code))
    local = set(re.findall(r"function\s+(\w+)|(?:const|let|var)\s+(\w+)|(\w+)\s*=>", code))
    params = {n for ps in re.findall(r"function\s*\w*\s*\(([^)]*)\)", code) for n in re.findall(r"\w+", ps)}
    defined = set(_top_names(_NEXT_JS)) | {n for t in local for n in t if n} | params | _JS_GLOBALS
    assert called - defined == set()


def test_console_dark_in_light_theme() -> None:
    """端末は pyte の暗い地向けの色のまま。ライトでも --con-bg / --con-fg を上書きせず、共有の端末 CSS の後ろで当てる"""
    from shadow_clerk._daemon_dashboard_css import _CSS_CONSOLE
    from shadow_clerk._daemon_dashboard_next_css import _LIGHT, _NEXT_CSS
    assert "--con-" not in _LIGHT
    rule = "#consolec, .aicon { background:var(--con-bg); color:var(--con-fg); }"
    assert _NEXT_CSS.index(rule) > _NEXT_CSS.index(_CSS_CONSOLE)


_SPEAKERS_BODY = r"""
(async()=>{
await tick();
const out={},F='transcript-20261031.txt',click=el=>el.handlers.click.forEach(f=>f({}));
const toastBtns=()=>nxEl('nxToast').children.filter(c=>c.tagName==='BUTTON');
const toastText=()=>(nxEl('nxToast').children.find(c=>c.tagName==='SPAN')||{}).textContent;
const cf=()=>[nxEl('nxCfModal').classList.contains('show'),nxEl('nxCfTitle').textContent];
const wait=async()=>{for(let i=0;i<6;i++)await tick();};
let undoOk=true;
ROUTES['/api/speakers?']={status:'ok',labels:[{label:'相手B',count:3,samples:0,example:'x',named:false}],suggestions:[],groups:[],history:[]};
ROUTES['/api/speakers/assign']={status:'ok',message:'3 行に名前を付けました',has_summary:true,history_ids:['b1','b2']};
ROUTES['/api/speakers/undo']=()=>undoOk?{status:'ok',message:'取り消しました',has_summary:false}:{status:'error',message:'取り消せません'};
ROUTES['/api/voiceprints/']={status:'ok'};
ROUTES['/api/voiceprints']={status:'ok',people:[]};
ROUTES['/api/speaker-groups']={status:'ok',names:{},persons:{},groups:{},self_group:''};
ROUTES['/api/summary']={status:'ok'};
ROUTES['/api/files']={files:[F],file_info:{}};
await wait();
nxState.cur=F;await nxLoadFiles();nxRenderAll();await tick();
/* 中央の見出しの 👥 が現行の話者モーダルを開く（開いているファイルで） */
click(nxEl('nxSpeakersBtn'));await wait();
const modal=document.getElementById('speakerModal');
out.open=modal.classList.contains('open');
out.spkFile=_spkFile;
/* 保存: 議事録があれば先に作り直すかを確認モーダルで。「元に戻す」は答えた後のトーストに付く（confirm は使わない） */
const row={dataset:{label:'相手B',named:'0'},value:'alice'};
document.querySelectorAll=sel=>sel==='#spkRows input[data-label]'?[row]:[];
posts.length=0;
await saveSpeakers();await wait();
out.assign=posts.filter(p=>p[0]==='/api/speakers/assign').map(p=>p[1]);
out.closed=!modal.classList.contains('open');
out.regen=cf();
posts.length=0;click(nxEl('nxCfOk'));await wait();
out.summary=posts.filter(p=>p[0]==='/api/summary').map(p=>p[1]);
out.afterRegen=[toastText(),toastBtns().map(b=>b.textContent)];
posts.length=0;click(toastBtns()[0]);await wait();
out.undo=posts.filter(p=>p[0]==='/api/speakers/undo').map(p=>p[1].id);
out.undoToast=toastText();
/* 作り直さないときは、保存の文言と「元に戻す」 */
await saveSpeakers();await wait();click(nxEl('nxCfCancel'));
out.afterCancel=[toastText(),toastBtns().map(b=>b.textContent)];
/* 議事録が無ければ、すぐに「元に戻す」付きのトースト */
ROUTES['/api/speakers/assign']={status:'ok',message:'1 行',has_summary:false,history_ids:['c1']};
nxEl('nxCfModal').classList.remove('show');
await saveSpeakers();await wait();
out.noSummary=[cf()[0],toastText(),toastBtns().map(b=>b.textContent)];
/* モーダルの履歴の「取り消す」・声紋の削除・塊の「消す」も確認モーダルで */
const r={id:'b1',label:'相手B',name:'alice'};
posts.length=0;undoNaming(r);
out.undoAsk=[cf()[0],posts.length];
modal.classList.remove('open');
click(nxEl('nxCfOk'));await wait();
out.undo2=posts.filter(p=>p[0]==='/api/speakers/undo').map(p=>p[1]);
out.reopened=modal.classList.contains('open');
/* 取り消しに失敗したら、モーダルを開き直さない */
undoOk=false;modal.classList.remove('open');
undoNaming(r);click(nxEl('nxCfOk'));await wait();
out.failReopened=modal.classList.contains('open');
out.failToast=toastText();
posts.length=0;deleteVoiceprint('alice');
out.delAsk=[...cf(),posts.length];
click(nxEl('nxCfOk'));await wait();
out.del=posts.filter(p=>p[0]==='/api/voiceprints/delete').map(p=>p[1]);
const cr=_vpClusterRow('alice',{kind:'different',count:2,keys:['k1'],sources:[],example:'e'});
const del=cr.children.find(c=>c.tagName==='BUTTON'&&c.textContent===I18N['dash.vp_delete']);
out.dsLabel=del&&del.textContent;
posts.length=0;del.onclick();
out.dsAsk=[cf()[0],posts.length];
click(nxEl('nxCfOk'));await wait();
out.ds=posts.filter(p=>p[0]==='/api/voiceprints/delete-samples').map(p=>p[1]);
out.confirms=confirms;
/* 現行のモーダル（.modal-overlay.open）の上での Escape は、行の選択を消さない */
nxSel=new Set([0]);
document.querySelector=sel=>sel.includes('.modal-overlay.open')?{}:null;
document.handlers.keydown.forEach(f=>f({key:'Escape'}));
out.selKept=nxSel.size;
console.log(JSON.stringify(out));
})().catch(e=>console.log(JSON.stringify({bodyErr:String(e&&e.stack||e)})));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node が無い")
def test_speakers_modal() -> None:
    """👥 が現行の話者モーダルを開き、名前付けの後は「元に戻す」のトーストと議事録の作り直しの確認モーダル。confirm は使わない"""
    ja = STRINGS["ja"]
    out = _run_next(_SPEAKERS_BODY)
    f, undo = "transcript-20261031.txt", ja["nx.spk_undo"]
    assert out["open"] is True and out["spkFile"] == f
    assert out["assign"] == [{"file": f, "mapping": {"相手B": {"name": "alice"}}}]
    assert out["closed"] is True
    assert out["regen"] == [True, ja["dash.summary_regen_after_naming"]]
    assert out["summary"] == [{"file": f}]
    assert out["afterRegen"] == [ja["nx.sum_started"], [undo]]
    assert out["undo"] == ["b2", "b1"] and out["undoToast"] == "取り消しました 取り消しました"
    assert out["afterCancel"] == ["3 行に名前を付けました", [undo]]
    assert out["noSummary"] == [False, "1 行", [undo]]
    assert out["undoAsk"] == [True, 0]
    assert out["undo2"] == [{"file": f, "id": "b1"}] and out["reopened"] is True
    assert out["failReopened"] is False and out["failToast"] == "取り消せません"
    assert out["delAsk"] == [True, ja["dash.voiceprint_delete_confirm"].replace("{name}", "alice"), 0]
    assert out["del"] == [{"name": "alice"}]
    assert out["dsLabel"] == ja["dash.vp_delete"]
    assert out["dsAsk"] == [True, 0] and out["ds"] == [{"name": "alice", "keys": ["k1"]}]
    assert out["confirms"] == 0
    assert out["selKept"] == 1


def test_speakers_html_shared() -> None:
    """話者モーダルの HTML は現行と同じ断片。中央の見出しに 👥"""
    from shadow_clerk._daemon_dashboard_html import _HTML_SPEAKER_MODAL, _HTML_TEMPLATE
    assert _HTML_SPEAKER_MODAL in _HTML_TEMPLATE and _HTML_SPEAKER_MODAL in _NEXT_HTML_TEMPLATE
    head = _NEXT_HTML_TEMPLATE[_NEXT_HTML_TEMPLATE.index('id="nxMainHead"'):]
    assert head.index('id="nxSpeakersBtn"') < head.index("</div>")
