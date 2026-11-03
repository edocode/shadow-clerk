"""/next 右ペイン（議事録・AI のアドバイス）・表示の切り替え・下ドロワーを node で検証する

実行: uv run python tests/test_next_right_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_next_css import _NEXT_CSS
from shadow_clerk._daemon_dashboard_next_js_core import _NEXT_JS_CORE
from shadow_clerk._daemon_dashboard_next_js_list import _NEXT_JS_LIST
from shadow_clerk._daemon_dashboard_next_js_right import _NEXT_JS_RIGHT
from shadow_clerk._daemon_dashboard_next_js_transcript import _NEXT_JS_TRANSCRIPT
from shadow_clerk._daemon_dashboard_next_js_view import _NEXT_JS_VIEW
from shadow_clerk.i18n import STRINGS

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_DAILY = "transcript-20261031.txt"
_MTG = "transcript-202610301712@週次定例.txt"
_FILES = {
    "files": [_DAILY, _MTG, "transcript-20261020.txt", "transcript-202610201529@ad-hoc.txt", "transcript-202609081610@勉強会.txt"],
    "active": _DAILY,
    "file_info": {
        _DAILY: {"label": "2026-10-31", "dt": "20261031", "meeting_group": None},
        _MTG: {"label": "2026-10-30 17:12 @週次定例", "dt": "202610301712", "meeting_group": "週次定例", "has_summary": True},
        "transcript-20261020.txt": {"label": "2026-10-20", "dt": "20261020", "meeting_group": None},
        "transcript-202610201529@ad-hoc.txt": {"label": "x", "dt": "202610201529", "meeting_group": "ad-hoc"},
        "transcript-202609081610@勉強会.txt": {"label": "y", "dt": "202609081610", "meeting_group": "勉強会"},
    },
}
# test_file_links_js.py と同じ入力
_TEXTS = [
    "本体は `summary-202610201529@ad-hoc.md` |",
    "画面キャプチャ: shot-202609081610@勉強会-161622.png | タイトル",
    "対象: transcript-20261020-en.txt（翻訳）と analysis-202609081610@勉強会.md、advice-202609081610@勉強会.md。",
    "my-transcript-20261020.txt / summary-20990101.md",
]

_PRE = ("const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";\nconst FILES=" + json.dumps(_FILES, ensure_ascii=False)
        + ";\nconst TEXTS=" + json.dumps(_TEXTS, ensure_ascii=False) + ";\n") + r"""
const mkEl=()=>({textContent:'',innerHTML:'',className:'',title:'',style:{},dataset:{},value:'',disabled:false,children:[],
  scrollTop:0,scrollHeight:1000,clientHeight:200,
  classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
    toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
  handlers:{},addEventListener(t,f){(this.handlers[t]=this.handlers[t]||[]).push(f);},setAttribute(){},getAttribute(){return null;},
  appendChild(c){this.children.push(c);},insertAdjacentHTML(p,h){this.innerHTML+=h;},
  querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},focus(){},select(){},remove(){},
  getBoundingClientRect(){return {left:900,bottom:40};}});
const els={};
const docHandlers={};
const document={getElementById:id=>els[id]||(els[id]=mkEl()),createElement:mkEl,querySelectorAll:()=>[],querySelector:()=>null,
  addEventListener(t,f){(docHandlers[t]=docHandlers[t]||[]).push(f);},body:mkEl(),
  documentElement:mkEl(),
  createTreeWalker:()=>({nextNode:()=>null})};
const NodeFilter={SHOW_TEXT:4};
const store={nxFontStep:'2'};
const localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=v;}};
const location={hash:'',pathname:'/next',search:''};
const history={replaceState(a,b,u){location.hash=u.startsWith('#')?u:'';}};
const window={h:{},addEventListener(t,f){this.h[t]=f;},removeEventListener(t){delete this.h[t];},innerWidth:1000,innerHeight:700};
const navigator={clipboard:{writeText:async()=>{}}};
const setTimeout=()=>0;
const clearTimeout=()=>{};
const setInterval=()=>0;
const posts=[];
const MOCK={status:{running:true,session:null,console_running:false,console_transcript:null},summary:{}};
const fetch=async (url,opt)=>{
  const ok=v=>({json:async()=>JSON.parse(JSON.stringify(v))});
  if(opt&&opt.method==='POST'){posts.push([url,JSON.parse(opt.body)]);
    return ok(url==='/api/summary'&&MOCK.sumFail?{status:'error',message:'作れません'}:{status:'ok'});}
  if(url.startsWith('/api/status'))return ok(MOCK.status);
  if(url.startsWith('/api/files'))return ok(FILES);
  if(url.startsWith('/api/summary'))return ok(MOCK.summary[decodeURIComponent(url.split('file=')[1]||'')]||{file:'',content:'',html:''});
  if(url.startsWith('/api/attendees'))return ok({attendees:['alice','bob']});
  if(url.startsWith('/api/advice'))return ok({file:'',html:''});
  if(url.startsWith('/api/analysis'))return ok({file:'',html:''});
  if(url.startsWith('/api/logs'))return ok({lines:['INFO ok','WARNING low','ERROR bad']});
  return ok({lines:[]});
};
class EventSource{constructor(){this.h={};}addEventListener(t,f){(this.h[t]=this.h[t]||[]).push(f);}close(){}}
/* 流用する現行のコンソール・読み上げ（このテストでは読み込まない）の代わり */
let _consoleRole='assistant',logTab='logs';
const roleSwitches=[];
function selectConsoleRole(r){_consoleRole=r;logTab='console';roleSwitches.push(r);}
function scheduleConsoleCols(){}
function scrollConsoleBottom(){}
function decorateSay(){}
const tick=()=>new Promise(r=>setImmediate(r));
const settle=async()=>{for(let i=0;i<8;i++)await tick();};
const sse=(type,d)=>(nxEs.h[type]||[]).forEach(f=>f({data:JSON.stringify(d)}));
const ev=(attr,val,extra)=>({target:{closest:sel=>sel.includes('data-'+attr)?{dataset:{[attr.replace(/-(\w)/g,(m,c)=>c.toUpperCase())]:val}}:null},
  stopPropagation(){},preventDefault(){},...(extra||{})});
const click=(id,e)=>els[id].handlers.click.forEach(f=>f(e));
"""

_BODY = r"""
(async()=>{
const out={};
nxInit();nxEs.onopen&&nxEs.onopen();await settle();
await nxLoadFiles();await settle();
/* --- linkify（現行 _fileRefLink と同じリンク） --- */
nxState.cur='transcript-20261020.txt';
out.links=TEXTS.map(t=>[...t.matchAll(nxFileRefRe)].map(m=>{
  const a=nxFileRefLink(m);
  if(!a)return [m[0],null];
  const before=nxState.cur;nxState.rtab='x';
  (a.handlers.click||[]).forEach(f=>f({preventDefault(){},stopPropagation(){}}));
  const r=[m[0],a.href,a.target||'',nxState.cur,nxState.rtab];
  nxState.cur=before;return r;
}));
/* --- AI は 1 つ: 別の会議を見ているときの案内 --- */
MOCK.status={running:true,session:null,console_running:true,console_transcript:FILES.files[1]};
await nxFetchStatus();
nxState.cur=FILES.files[0];nxState.rtab='ai';nxRenderAll();await settle();
out.forOther=nxAssistantFor();
out.aiOther=els.nxRightBody.innerHTML;
nxOpenFile(FILES.files[1]);await settle();
out.aiMine=els.nxRightBody.innerHTML;
nxOpenFile(FILES.files[0]);await settle();
posts.length=0;
nxOnRightClick(ev('ra','ai-start'));await settle();
out.startPost=posts.slice();
out.switchToast=els.nxToast.children.map(c=>c.textContent).join('');
MOCK.status={running:true,session:null,console_running:false,console_transcript:null};
await nxFetchStatus();await settle();
out.forStopped=nxAssistantFor();
out.aiStopped=els.nxRightBody.innerHTML;
/* console SSE: 走っているかが変わったら取り直す */
MOCK.status={running:true,session:null,console_running:true,console_transcript:FILES.files[0]};
sse('console',{role:'assistant',running:true});await settle();
out.forAfterSse=nxAssistantFor();
/* 止める: 確認 → {role:'assistant'} */
posts.length=0;
nxOnRightClick(ev('ra','ai-stop'));
out.stopModal=els.nxCfModal.classList.contains('show');
click('nxCfOk',{});await settle();
out.stopPost=posts.slice();
/* --- 議事録: 会議中は「今までの分で作る」→ 現行と同じ POST /api/summary --- */
nxState.rtab='sum';nxRenderAll();await settle();
out.sumMemo=els.nxRightBody.innerHTML;
nxState.session='/data/'+FILES.files[0];nxRenderAll();await settle();
out.sumLive=els.nxRightBody.innerHTML;
posts.length=0;
nxOnRightClick(ev('ra','gen'));await settle();
out.genPost=posts.slice();
out.sumGen=els.nxRightBody.innerHTML;
/* 待ちの表示は、開いているファイルの議事録を名指しした alert でだけ消える */
const sumName=FILES.files[0].replace(/^transcript-/,'summary-').replace(/\.txt$/,'.md');
MOCK.summary[FILES.files[0]]={file:sumName,content:'# 済',html:'<h1>済</h1>'};
sse('alert',{message:'議事録を生成しました: summary-20261029.md'});await settle();
out.sumGenOther=els.nxRightBody.innerHTML;
sse('alert',{message:'議事録を生成しました: '+sumName});await settle();
out.sumGenMine=els.nxRightBody.innerHTML;
delete MOCK.summary[FILES.files[0]];
/* 議事録を始められなくても、付けたボタン（名前付けの「元に戻す」）は残す */
MOCK.sumFail=true;await nxGenSummary(FILES.files[0],['元に戻す',()=>{}]);MOCK.sumFail=false;
out.sumFailToast=els.nxToast.children.map(c=>c.textContent).slice(-2);
MOCK.summary[FILES.files[1]]={file:'summary-202610301712@週次定例.md',content:'# 週次定例\n- a',html:'<h1>週次定例</h1><ul><li>a</li></ul>'};
nxOpenFile(FILES.files[1]);await settle();
out.sumDone=els.nxRightBody.innerHTML;
posts.length=0;
nxOnRightClick(ev('ra','regen'));
out.regenModal=els.nxCfModal.classList.contains('show');
click('nxCfOk',{});await settle();
out.regenPost=posts.slice();
/* --- 表示の切り替え --- */
nxSetView('AI');
out.aimode=els.nxApp.classList.contains('aimode');out.aiRtab=nxState.rtab;
nxState.bottom=false;roleSwitches.length=0;
nxSetView('CON');
out.con=[els.nxMain.classList.contains('aiview'),els.nxMain.classList.contains('narrow'),nxState.bottom,nxState.rtab,
  els.nxDrawerNoteAi.textContent,roleSwitches.slice()];
out.conAimode=els.nxApp.classList.contains('aimode');
// 止まっている間は、何が出るかと起動のボタンを重ね、押すと開いている文字起こしで起動する
MOCK.status={running:true,session:null,console_running:false,console_transcript:null};
await nxFetchStatus();await settle();
out.conIdle=els.nxConsoleMain.classList.contains('idle');
posts.length=0;(els.nxConStart.handlers.click||[]).forEach(f=>f());await settle();
out.conStart=posts.slice();
MOCK.status={running:true,session:null,console_running:true,console_transcript:FILES.files[0]};
await nxFetchStatus();await settle();
out.conRunning=els.nxConsoleMain.classList.contains('idle');
MOCK.status={running:true,session:null,console_running:false,console_transcript:null};
await nxFetchStatus();await settle();
nxSetView('T');nxTogglePane('left');nxTogglePane('right');
out.noLeft=els.nxApp.classList.contains('no-left');out.noRight=els.nxApp.classList.contains('no-right');
nxTogglePane('left');nxTogglePane('right');
nxSetView('AI');nxTogglePane('right');
out.rightOffInAi=[nxState.view,nxState.right,nxViewMenuHtml().includes('ptog fixed')];
nxSetView('T');
out.rightMenuT=nxViewMenuHtml().includes('ptog fixed');
/* --- 文字の大きさ（表示メニュー）: 覚えていた大から始まり、選ぶと変えて覚える --- */
out.font0=[document.documentElement.style.zoom,els.consoleRow.style.zoom,nxViewMenuHtml().includes('class="act" data-fs="2"')];
click('nxViewMenu',{target:{closest:s=>s==='[data-fs]'?{dataset:{fs:'0'}}:null},stopPropagation(){}});
out.font1=[document.documentElement.style.zoom,els.consoleRow.style.zoom,store.nxFontStep,nxViewMenuHtml().includes('class="act" data-fs="0"')];
/* 下ドロワーの高さ: つまみのドラッグで変えて覚える（zoom 0.9 なので画面の 300px は 333px） */
els.nxDrawer.style={props:{},setProperty(k,v){this.props[k]=v;}};
els.nxDrawerBody.getBoundingClientRect=()=>({bottom:700});
els.nxDrawerGrip.handlers.mousedown[0]({preventDefault(){}});
window.h.mousemove({clientY:400});
out.drawerDrag=[els.nxDrawer.style.props['--dh'],els.nxDrawer.classList.contains('dragging')];
window.h.mouseup();
out.drawerUp=[store.nxDrawerH,els.nxDrawer.classList.contains('dragging'),!!window.h.mousemove];
/* アドバイスと分析の仕切り: 上下に積んでいれば縦、並べていれば横の割合を変えて覚える */
els.nxRightBody.style={props:{},setProperty(k,v){this.props[k]=v;}};
const aiGrid={getBoundingClientRect:()=>({top:100,height:400,left:0,width:800})},aiDir={v:'column'};
els.nxRightBody.querySelector=s=>s==='.aigrid'?aiGrid:null;
globalThis.getComputedStyle=e=>e===aiGrid?{flexDirection:aiDir.v}:{cursor:aiDir.v==='column'?'ns-resize':'ew-resize'};
const splitDrag=(x,y)=>{
  els.nxRightBody.handlers.mousedown[0]({button:0,target:{closest:s=>s==='.aisep'?{parentNode:aiGrid}:null},preventDefault(){}});
  window.h.mousemove({clientX:x,clientY:y});
  const r=[els.nxRightBody.style.props,els.nxRightBody.classList.contains('aidrag'),document.body.style.cursor];
  window.h.mouseup();
  return r.concat([els.nxRightBody.classList.contains('aidrag'),!!window.h.mousemove,document.body.style.cursor]);
};
out.splitV=JSON.parse(JSON.stringify(splitDrag(0,200)));out.splitVStore=store.nxAiSplitv;
aiDir.v='row';
out.splitH=JSON.parse(JSON.stringify(splitDrag(790,0)));out.splitHStore=store.nxAiSplith;
/* --- ショートカット（入力欄では使わない） --- */
const key=(k,code,target)=>docHandlers.keydown.forEach(f=>f({altKey:true,key:k,code,target:target||{closest:()=>null},preventDefault(){}}));
key('2','Digit2');out.alt2=nxState.view;
key('1','Digit1',{closest:s=>s.includes('input')?{}:null});out.alt1InInput=nxState.view;
key('5','Digit5');out.alt5Simple=nxState.view;
document.body.classList.add('adv');key('5','Digit5');out.alt5Adv=nxState.view;
key('[','BracketLeft');out.altBracket=nxState.left;
key('[','BracketLeft');
/* --- 動作ログ --- */
nxState.dtab='log';nxState.bottom=true;nxRenderAll();await settle();
out.logs=els.nxLogView.innerHTML;
sse('log',{line:'ERROR later'});
out.logsAfter=els.nxLogView.innerHTML;
/* --- メニューは画面内に寄せる --- */
nxPlaceViewMenu();
out.menu=[els.nxViewMenu.style.left,els.nxViewMenu.style.width];
/* --- 定期の取り直しも nxFetchStatus と同じ派生の項目を揃える（nxApplyStatus） --- */
nxState.session=null;nxState.translating=false;nxState.status={...nxState.status,console_running:true};
MOCK.status={running:true,session:'/data/'+FILES.files[0],translating:true,mute_mic:true,console_running:false,console_transcript:null};
await nxPollConsole();
out.poll=[nxState.session,nxState.translating,nxState.muteMic,nxState.status.console_running];
// 分析の追記: 一番下を見ていたら追い、途中を読んでいたら動かさない。アドバイスは追わない
nxState.rtab='ai';nxOpenFile(FILES.files[1]);await settle();
const stem=nxRt.file.replace(/^transcript-/,'').replace(/\.txt$/,'.md'),advCol=mkEl(),anaCol=mkEl(),rbQsa=els.nxRightBody.querySelectorAll;
els.nxRightBody.querySelectorAll=s=>s==='.aiscroll'?[advCol,anaCol]:[];
anaCol.scrollTop=800;nxOnGenerated('ana',{file:'analysis-'+stem,html:'<p>1</p>'});out.anaBottom=anaCol.scrollTop;
anaCol.scrollTop=300;nxOnGenerated('ana',{file:'analysis-'+stem,html:'<p>2</p>'});out.anaMiddle=anaCol.scrollTop;
advCol.scrollTop=800;nxOnGenerated('adv',{file:'advice-'+stem,html:'<p>3</p>'});out.advBottom=advCol.scrollTop;
els.nxRightBody.querySelectorAll=rbQsa;
console.log(JSON.stringify(out));
})().catch(e=>{console.error(e);process.exit(1);});
"""


def main() -> None:
    src = _PRE + _NEXT_JS_CORE + _NEXT_JS_LIST + _NEXT_JS_TRANSCRIPT + _NEXT_JS_RIGHT + _NEXT_JS_VIEW + _BODY
    r = subprocess.run(["node", "-"], input=src, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-800:])
        sys.exit(1)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    ja = STRINGS["ja"]
    enc = "%E5%8B%89%E5%BC%B7%E4%BC%9A"  # 勉強会
    links = out["links"]
    check("summary は対応する transcript を開いて議事録タブ", links[0] == [[
        "summary-202610201529@ad-hoc.md", "#transcript-202610201529%40ad-hoc.txt", "",
        "transcript-202610201529@ad-hoc.txt", "sum"]], repr(links[0]))
    check("キャプチャは /api/screenshot?file= を別タブ", links[1] == [[
        "shot-202609081610@勉強会-161622.png", f"/api/screenshot?file=shot-202609081610%40{enc}-161622.png&transcript=transcript-20261020.txt", "_blank",
        "transcript-20261020.txt", "x"]], repr(links[1]))
    check("翻訳は元の transcript へ、表示中なら開き直さない",
          links[2][0] == ["transcript-20261020-en.txt", "#transcript-20261020.txt", "", "transcript-20261020.txt", "x"],
          repr(links[2][0]))
    check("analysis / advice は AI タブ", [l[3:] for l in links[2][1:]] == [["transcript-202609081610@勉強会.txt", "ai"]] * 2,
          repr(links[2][1:]))
    check("語の途中や transcript の無いファイル名はリンクにしない", links[3] == [["summary-20990101.md", None]], repr(links[3]))

    other = ja["nx.ai_other"].replace("{name}", "2026-10-30 17:12 @週次定例")
    check("console_transcript から見ている会議が分かる", out["forOther"] == _MTG, repr(out["forOther"]))
    check("別の会議を見ているとき AI タブに案内を出す", other in out["aiOther"] and 'data-ra="ai-start"' in out["aiOther"],
          out["aiOther"][:300])
    check("分析の追記は一番下を見ているときだけ追い、アドバイスは追わない",
          [out["anaBottom"], out["anaMiddle"], out["advBottom"]] == [1000, 300, 800],
          repr((out["anaBottom"], out["anaMiddle"], out["advBottom"])))
    check("見ている会議では案内を出さず、止めるボタン",other not in out["aiMine"] and ja["nx.ai_watching"] in out["aiMine"]
          and 'data-ra="ai-stop"' in out["aiMine"], out["aiMine"][:300])
    check("切り替えは /api/console/start に {transcript}", out["startPost"] == [["/api/console/start", {"transcript": _DAILY}]],
          repr(out["startPost"]))
    check("切り替えたことを知らせる", ja["nx.ai_switched"].replace("{name}", "2026-10-30 17:12 @週次定例") in out["switchToast"],
          repr(out["switchToast"]))
    check("止まっていれば見ている会議は無い・案内も出さない",
          out["forStopped"] is None and ja["nx.ai_other_status"] not in out["aiStopped"], out["aiStopped"][:200])
    check("console SSE で状態が変わったら /api/status を取り直す", out["forAfterSse"] == _DAILY, repr(out["forAfterSse"]))
    check("止めるは確認してから {role:'assistant'}",
          out["stopModal"] and out["stopPost"] == [["/api/console/stop", {"role": "assistant"}]], repr(out["stopPost"]))

    check("会議中の議事録なしは「今までの分で作る」", ja["nx.sum_live_btn"] in out["sumLive"], out["sumLive"][:300])
    check("会議中でなければ記録中のメモでも「議事録を作る」", ja["nx.sum_make"] in out["sumMemo"] and ja["nx.sum_live_h"] not in out["sumMemo"],
          out["sumMemo"][:200])
    check("参加者を出す", "alice, bob" in out["sumLive"], out["sumLive"][:300])
    check("今までの分で作る は POST /api/summary {file}", out["genPost"] == [["/api/summary", {"file": _DAILY}]], repr(out["genPost"]))
    check("作っている間は待ちの表示", ja["nx.sum_gen_h"] in out["sumGen"], out["sumGen"][:200])
    check("ほかの議事録の alert では待ちの表示を消さない", ja["nx.sum_gen_h"] in out["sumGenOther"], out["sumGenOther"][:200])
    check("開いているファイルの議事録の alert で読み直す", ja["nx.sum_gen_h"] not in out["sumGenMine"]
          and "<h1>済</h1>" in out["sumGenMine"], out["sumGenMine"][:200])
    check("議事録を始められなくても「元に戻す」を残す", out["sumFailToast"] == ["作れません", "元に戻す"], repr(out["sumFailToast"]))
    check("議事録があればツールと本文", all(k in out["sumDone"] for k in ('data-ra="copy"', 'data-ra="reload"', 'data-ra="regen"',
          "/api/file?name=summary-202610301712%40", "<h1>週次定例</h1>")), out["sumDone"][:400])
    check("作り直しは確認してから POST /api/summary",
          out["regenModal"] and out["regenPost"] == [["/api/summary", {"file": _MTG}]], repr(out["regenPost"]))

    check("AI を大きく: .app.aimode・AI タブ", out["aimode"] and out["aiRtab"] == "ai", repr((out["aimode"], out["aiRtab"])))
    check("CON: 中央に AI アシスタントの画面（端末は assistant）・ドロワーは開かない",
          out["con"] == [True, True, False, "ai", ja["nx.d_con_center"], ["assistant"]] and not out["conAimode"], repr(out["con"]))
    check("左右を閉じると no-left / no-right", out["noLeft"] and out["noRight"])
    check("AI アシスタントの画面: 止まっていれば説明と起動ボタン、押すと開いている文字起こしで起動、動けば端末を出す",
          out["conIdle"] and out["conStart"] == [["/api/console/start", {"transcript": out["conStart"][0][1]["transcript"]}]]
          and out["conRunning"] is False, repr((out["conIdle"], out["conStart"], out["conRunning"])))
    check("AI 表示では右のパネルを切り替えず、表示も変えない（メニューでは押せない）",
          out["rightOffInAi"] == ["AI", True, True] and out["rightMenuT"] is False, repr((out["rightOffInAi"], out["rightMenuT"])))
    check("文字の大きさ: 覚えていた大から始まり、画面全体を zoom・端末は打ち消す",
          out["font0"] == ["1.2", str(1 / 1.2), True], repr(out["font0"]))
    check("下ドロワー: つまみのドラッグで高さを変え（zoom を考える）、離すと覚える",
          out["drawerDrag"] == ["333px", True] and out["drawerUp"] == ["333", False, False],
          repr((out["drawerDrag"], out["drawerUp"])))
    check("文字の大きさ: 小を選ぶと変えて覚える", out["font1"] == ["0.9", str(1 / 0.9), "0", True], repr(out["font1"]))
    check("Alt+2 で＋翻訳", out["alt2"] == "TR", repr(out["alt2"]))
    check("入力欄の中ではショートカットを使わない", out["alt1InInput"] == "TR", repr(out["alt1InInput"]))
    check("かんたん表示では Alt+5 を使わない・くわしくなら CON",
          out["alt5Simple"] == "TR" and out["alt5Adv"] == "CON", repr((out["alt5Simple"], out["alt5Adv"])))
    check("Alt+[ で左を閉じる", out["altBracket"] is False, repr(out["altBracket"]))
    check("動作ログは /api/logs を色分けして出す", 'class="ll w"' in out["logs"] and 'class="ll e"' in out["logs"]
          and "INFO ok" in out["logs"], out["logs"])
    check("SSE の log を足す", out["logsAfter"].endswith('<div class="ll e">ERROR later</div>'), out["logsAfter"][-80:])
    # 文字の大きさで小（zoom 0.9）を選んだ後なので、画面の幅を zoom で割った値で右端に寄せる
    check("メニューは画面の右端からはみ出さない（zoom を考える）",
          abs(float(out["menu"][0][:-2]) - (1000 / 0.9 - 368)) < 1e-6 and out["menu"][1] == "360px", repr(out["menu"]))
    check("定期の取り直しでも会議・翻訳・ミュートを揃える",
          out["poll"] == ["/data/" + _DAILY, True, True, False], repr(out["poll"]))

    css = _NEXT_CSS
    check("各ペインの列を明示する", ".app > main { grid-column:2; }" in css and ".app.aimode > main { grid-column:3; }" in css
          and ".app.aimode > .right { grid-column:2;" in css)
    check("アドバイスと分析は 620px 以下で上下", "@container (max-width:620px) {\n  .aigrid { flex-direction:column; }" in css)
    check("アドバイスと分析は別々にスクロールし、間に仕切りを置く",
          '<div class="aiscroll">' in out["aiMine"] and 'class="aisep"' in out["aiMine"])
    check("仕切り（上下）: ドラッグで --ais-v を変え、離すと覚えてカーソルを戻す",
          out["splitV"] == [{"--ais-v": "25.0%"}, True, "ns-resize", False, False, ""] and out["splitVStore"] == "25.0",
          repr((out["splitV"], out["splitVStore"])))
    check("仕切り（左右）: 90% で止め、--ais-h に別に覚える",
          out["splitH"] == [{"--ais-v": "25.0%", "--ais-h": "90.0%"}, True, "ew-resize", False, False, ""]
          and out["splitHStore"] == "90.0", repr((out["splitH"], out["splitHStore"])))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
