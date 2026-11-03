"""/next の「その他 ▾」メニュー・起動時のモーダル・音声コマンドの応答を node で検証する

- 各項目が現行の関数を呼ぶ: 📖 openGlossary / 📅 openGcal / ⚡ openCustomCmds / ⚙ openCfg / ❓ openHelp
- 📅 は /api/status の gcal_enabled が無いと出さない（現行の #btnGcal と同じ判定）
- ⌨ は ptt_on / ptt_off（SSE ptt で状態を揃える）
- 🗣 は話す言語を set_language / unset_language で変え、認識モデルを /api/status・SSE asr_status から出す
- 起動時はようこそを優先し、表示しない場合はスキル更新を確認する
- 音声コマンドの応答（SSE response）はトースト。短いものは「もう一度」で出し直せ、長いものは下ドロワーの「応答」タブに全文
  （くわしく表示にするが、その切り替えは覚えない）
- 以前のダッシュボード（/legacy）への項目は くわしく のときだけ
- 流用するモジュールの alert はトーストになる

実行: uv run python tests/test_next_more_js.py
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


_PRE = "const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";const PATH_HINTS={};\n" + r"""
function mkEl(id){
  const el={id:id||'',_t:'',get textContent(){return this._t;},set textContent(v){this._t=String(v);this.children=[];},innerHTML:'',className:'',title:'',value:'',checked:false,disabled:false,hidden:false,
    style:{props:{},setProperty(k,v){this.props[k]=v;}},dataset:{},children:[],parentNode:null,
    scrollTop:0,scrollHeight:400,clientHeight:200,clientWidth:800,
    classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
      toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
    handlers:{},addEventListener(t,f){(this.handlers[t]=this.handlers[t]||[]).push(f);},setAttribute(){},getAttribute(){return null;},
    appendChild(c){this.children.push(c);c.parentNode=this;return c;},insertAdjacentHTML(p,h){this.innerHTML+=h;},
    querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},contains(){return false;},
    focus(){},blur(){},select(){},remove(){},getBoundingClientRect(){return {left:0,top:0,right:800,bottom:40,width:800,height:200};}};
  return el;
}
const els={};
const document={getElementById:id=>els[id]||(els[id]=mkEl(id)),
  createElement:()=>mkEl(),querySelectorAll:()=>[],querySelector:()=>null,addEventListener(){},
  body:mkEl(),documentElement:mkEl(),visibilityState:'visible',createTreeWalker:()=>({nextNode:()=>null})};
const NodeFilter={SHOW_TEXT:4};
const store={};
const localStorage={getItem(k){return k in store?store[k]:null;},setItem(k,v){store[k]=String(v);}};
const location={hash:'',pathname:'/next',search:''};
const history={replaceState(){}};
const window={addEventListener(){},innerWidth:1200,innerHeight:800,getSelection:()=>''};
const navigator={userActivation:{hasBeenActive:true},sendBeacon(){return true;},clipboard:{writeText:async()=>{}}};
const speechSynthesis={getVoices:()=>[],speak(){},cancel(){},addEventListener(){}};
class SpeechSynthesisUtterance{constructor(t){this.text=t;}}
const getComputedStyle=()=>({paddingLeft:'8px'});
const confirm=()=>true;
const setTimeout=()=>0;const clearTimeout=()=>{};const setInterval=()=>0;
const sources=[];
class EventSource{constructor(){this.h={};sources.push(this);}addEventListener(t,f){(this.h[t]=this.h[t]||[]).push(f);}close(){}}
const fire=(t,d)=>(sources[sources.length-1].h[t]||[]).forEach(f=>f({data:JSON.stringify(d)}));
const posts=[],gets=[];
const STATUS={running:true,session:null,language:'ja',ptt:false,gcal_enabled:false,asr_backend:'reazonspeech-k2',
  asr_model_id:'reazonspeech-k2-ja',console_running:false,talk_console_running:false};
const fetch=async (url,opt)=>{
  const ok=v=>({json:async()=>JSON.parse(JSON.stringify(v)),text:async()=>''});
  if(opt&&opt.method==='POST'){posts.push([url,JSON.parse(opt.body)]);return ok({status:'ok'});}
  gets.push(url);
  if(url.startsWith('/api/status'))return ok(STATUS);
  if(url.startsWith('/api/files'))return ok({files:[],file_info:{}});
  if(url.startsWith('/api/skill-status'))return ok({bundled:'1.0.0',targets:[]});
  if(url.startsWith('/api/config'))return ok({welcome_dismissed:false});
  return ok({lines:[]});
};
const tick=()=>new Promise(r=>setImmediate(r));
const settle=async()=>{for(let i=0;i<12;i++)await tick();};
const click=id=>(els[id].handlers.click||[]).forEach(f=>f({preventDefault(){},stopPropagation(){},target:els[id]}));
const change=(id,v)=>{els[id].value=v;(els[id].handlers.change||[]).forEach(f=>f({target:els[id]}));};
"""

_BODY = r"""
(async()=>{
const out={};
await settle();
out.boot=[gets.filter(u=>u.startsWith('/api/skill-status')).length,els.welcomeModal.classList.contains('open')];
/* 各項目は現行の関数を呼ぶ（クリックした時点の名前を引く） */
const called=[];
openGlossary=()=>called.push('glossary');openGcal=()=>called.push('gcal');openCustomCmds=()=>called.push('cmds');
openCfg=async()=>called.push('cfg');openHelp=()=>called.push('help');nxOpenMeetingSettings=()=>called.push('mtgcfg');
['nxMiGlossary','nxMiGcal','nxMiCmds','nxMiMtgCfg','nxMiCfg','nxMiHelp'].forEach(click);
out.called=[...called];
/* 📅 は gcal が連携しているときだけ */
out.gcalOff=els.nxMiGcal.hidden;
STATUS.gcal_enabled=true;await nxFetchStatus();out.gcalOn=els.nxMiGcal.hidden;
/* ⌨ 押して話す */
posts.length=0;click('nxMiPtt');await settle();out.ptt1=[posts.map(p=>p[1].command),els.nxMiPttSt.textContent];
fire('ptt',{active:false});out.pttSse=els.nxMiPttSt.textContent;
posts.length=0;click('nxMiPtt');await settle();out.ptt2=posts.map(p=>p[1].command);
/* 🗣 話す言語 / 認識モデル */
out.langSub=els.nxMiLangSub.textContent;
click('nxMiLang');out.langOpen=[els.nxLgModal.classList.contains('show'),els.nxLgSel.value,els.nxLgModel.textContent];
posts.length=0;change('nxLgSel','en');await settle();
change('nxLgSel','auto');await settle();
out.langCmds=posts.map(p=>p[1].command);
fire('asr_status',{asr_backend:'whisper',asr_model_id:'small'});
out.asr=[els.nxLgModel.textContent,els.nxMiLangSub.textContent];
/* ヘッダの言語: auto / ja / en … を選ぶと、すぐ切り替える */
out.quickOpts=els.nxLangQuick.innerHTML;out.quickVal=els.nxLangQuick.value;
posts.length=0;change('nxLangQuick','en');await settle();
out.quick=[posts.map(p=>p[1].command),els.nxLangQuick.value];
change('nxLangQuick','auto');await settle();
// スキルや音声コマンドが言語を変えても、asr_status で追う
fire('asr_status',{asr_backend:'whisper',asr_model_id:'small',language:'en'});
out.quickSse=[els.nxLangQuick.value,els.nxMiLangSub.textContent];
called.length=0;click('nxLgCfg');await settle();out.lgCfg=[called,els.nxLgModal.classList.contains('show')];
/* 応答: 短いものはトーストだけ、長いものは「応答」タブに全文 */
fire('response',{content:'了解しました'});
out.short=[els.nxToast.children[0].textContent,els.nxToast.children.length,els.nxToast.children[1]&&els.nxToast.children[1].textContent];
/* かんたんでも短い応答をもう一度見られる */
els.nxToast.classList.remove('show');
(els.nxToast.children[1]?els.nxToast.children[1].handlers.click:[]).forEach(f=>f());
out.again=[els.nxToast.classList.contains('show'),els.nxToast.children[0].textContent];
const long='議事録の要点です。\n'+'あ'.repeat(200);
fire('response',{content:long});
out.long=[els.nxToast.children[0].textContent.length<long.length,els.nxToast.children.length,els.nxRespView.textContent===long];
els.nxToast.children[1].handlers.click.forEach(f=>f());
out.respTab=[nxState.dtab,nxState.bottom,document.body.classList.contains('adv'),store.nxAdv==='1'];
/* 流用するモジュールの alert はトーストになる */
alert('取得できませんでした');out.alert=els.nxToast.children[0].textContent;
console.log(JSON.stringify(out));
})().catch(e=>console.log(JSON.stringify({bodyErr:String(e&&e.stack||e)})));
"""

r = subprocess.run(["node", "-e", "eval(require('fs').readFileSync(0,'utf8'))"], input=_PRE + _NEXT_JS + _BODY,
                   capture_output=True, text=True, timeout=60)
lines = r.stdout.strip().splitlines()
try:
    out = json.loads(lines[-1])
except (IndexError, ValueError):
    out = {}
check("node で実行できる", r.returncode == 0 and "bodyErr" not in out and bool(out), (r.stderr + r.stdout)[-800:])
if not all(results):
    sys.exit(1)
ja = STRINGS["ja"]
check("起動時はようこそを優先して開く",
      out["boot"][0] == 1 and out["boot"][1] is True, repr(out["boot"]))
check("各項目が現行の関数を呼ぶ", out["called"] == ["glossary", "gcal", "cmds", "mtgcfg", "cfg", "help"], repr(out["called"]))
check("📅 は gcal が連携していないと出さない", out["gcalOff"] is True and out["gcalOn"] is False,
      repr([out["gcalOff"], out["gcalOn"]]))
check("ヘッダの言語: auto と LANG_OPTS を並べ、いまの言語を選んでおく",
      out["quickOpts"].startswith('<option value="auto">auto</option><option value="ja">ja</option><option value="en">en</option>')
      and out["quickVal"] in ("auto", "ja"), repr((out["quickOpts"], out["quickVal"])))
check("ヘッダの言語: 選ぶと set_language を送る", out["quick"] == [["set_language en"], "en"], repr(out["quick"]))
check("ヘッダの言語: ほかから変えられても asr_status で追う",
      out["quickSse"][0] == "en" and out["quickSse"][1].startswith(ja["nx.st_lang_en"]), repr(out["quickSse"]))
check("⌨: ptt_on を送り、オンと出す", out["ptt1"] == [["ptt_on"], ja["nx.mi_on"]], repr(out["ptt1"]))
check("⌨: SSE ptt で状態を揃え、次は ptt_on", out["pttSse"] == ja["nx.mi_off"] and out["ptt2"] == ["ptt_on"],
      repr([out["pttSse"], out["ptt2"]]))
check("🗣: メニューに話す言語と認識モデル", out["langSub"] == ja["nx.st_lang_ja"] + " · reazonspeech-k2", repr(out["langSub"]))
check("🗣: 開くといまの言語とモデル", out["langOpen"] == [True, "ja", "reazonspeech-k2"], repr(out["langOpen"]))
check("🗣: 言語は set_language / unset_language", out["langCmds"] == ["set_language en", "unset_language"],
      repr(out["langCmds"]))
check("🗣: SSE asr_status でモデルの表示を揃える",
      out["asr"] == ["Whisper: small", ja["nx.st_lang_auto"] + " · Whisper: small"], repr(out["asr"]))
check("🗣: 「設定を開く」で閉じて現行の設定を開く", out["lgCfg"] == [["cfg"], False], repr(out["lgCfg"]))
check("応答: 短いものはトーストに全文と「もう一度」", out["short"] == ["💬 了解しました", 2, ja.get("nx.resp_again")],
      repr(out["short"]))
check("応答: 「もう一度」で同じトーストを出し直す", out["again"] == [True, "💬 了解しました"], repr(out["again"]))
check("応答: 長いものはトーストに頭だけ・「全文を見る」、応答タブに全文", out["long"] == [True, 2, True], repr(out["long"]))
check("応答: 「全文を見る」で下ドロワーの応答タブを開く（くわしく表示にするが、覚えない）",
      out["respTab"] == ["resp", True, True, False], repr(out["respTab"]))
from shadow_clerk._daemon_dashboard_next_html import _NEXT_HTML_TEMPLATE  # noqa: E402
check("その他に くわしく だけの「以前のダッシュボード」（/legacy へのリンク）",
      '<a class="mi adv-only" id="nxMiLegacy" href="/legacy">' in _NEXT_HTML_TEMPLATE
      and "{{i18n:nx.mi_legacy}}" in _NEXT_HTML_TEMPLATE and all("nx.mi_legacy" in STRINGS[lg] for lg in ("ja", "en")))
check("alert はトーストになる", out["alert"] == "取得できませんでした", repr(out["alert"]))
sys.exit(0 if all(results) else 1)
