"""/next 左ペイン「検索」のクエリ作り・結果のまとめ・<mark>・結果を開く動作を node で検証する

実行: uv run python tests/test_next_search_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk.i18n import STRINGS

try:
    from shadow_clerk._daemon_dashboard_next_js_search import _NEXT_JS_SEARCH
except ImportError:
    _NEXT_JS_SEARCH = ""

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_PRE = "const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";\n" + r"""
const mkEl=()=>({textContent:'',innerHTML:'',style:{},dataset:{},value:'',handlers:{},addEventListener(t,f){this.handlers[t]=f;},
  querySelector(){return null;},querySelectorAll(){return [];},closest(){return null;}});
const els={};
const document={getElementById:id=>els[id]||(els[id]=mkEl())};
const urls=[];
let apiResult={results:[]};
async function nxApi(path){urls.push(path);return apiResult;}
function nxEl(id){return document.getElementById(id);}
function nxEsc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function nxFmt(key,vars){let s=I18N[key]||'';Object.keys(vars).forEach(k=>{s=s.split('{'+k+'}').join(vars[k]);});return s;}
const nxState={view:'T',right:false,rtab:'ai',cur:''};
let nxFiles=[{name:'a',dt:'202510010000'},{name:'b',dt:'202610311950'}];
const nxRenderers=[];
const calls=[];
function nxOpenFile(n){calls.push(['open',n]);nxState.cur=n;}
function nxSetView(v){calls.push(['view',v]);nxState.view=v;}
function nxOn(){}
const tick=()=>new Promise(r=>setImmediate(r));
let timers=[];
const setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;};
const clearTimeout=()=>{};
// 行の DOM
let nxTxFile=null,nxTxLoading=false;
let nxLines=[],nxMarks=[],nxTrRows=[],nxTrMap=new Map(),nxRowsDrift=false;
function nxParseLine(raw){const m=/^\[([^\]]+)\]\s\[([^\]]+)\]\s(.*)$/.exec(raw);return m?{ts:m[1],speaker:m[2],text:m[3],raw}:null;}
function nxTrKey(l){return l.ts+'\t'+l.speaker;}
function nxAddLines(rows){rows.forEach(raw=>{const l=nxParseLine(raw);if(l)nxLines.push(l);else nxMarks.push({at:nxLines.length,text:raw});});}
function nxAddTr(rows){rows.forEach(raw=>{const l=nxParseLine(raw);nxTrRows.push(l?nxTrKey(l):null);if(!l)return;const k=nxTrKey(l);
  if(!nxTrMap.has(k))nxTrMap.set(k,[]);nxTrMap.get(k).push(l.text);});}
const lnEl=i=>({scrolled:false,cls:new Set(),scrollIntoView(o){this.scrolled=o.block;},classList:{add:c=>lnEl.last.cls.add(c),remove:c=>lnEl.last.cls.delete(c)}});
"""

_BODY = r"""
(async()=>{
const out={};
nxSq.q='  Budget ';nxSq.type='all';
out.q1=nxSearchQuery(nxSq);
Object.assign(nxSq,{q:'',type:'summary',y:'2026',m:'10',d:'5',h:'9'});
out.q2=nxSearchQuery(nxSq);
Object.assign(nxSq,{q:'',y:'',m:'',d:'',h:''});
out.q3=nxSearchQuery(nxSq);
// <mark>: 先にエスケープ、大文字小文字を無視、元の綴りを保つ
out.mark1=nxMarkHtml('Hello <b>BUDGET</b> & budget "x"','budget');
out.mark2=nxMarkHtml('a<b','<b');
out.mark3=nxMarkHtml('plain','');
out.mark5=nxMarkHtml('a & b','&');
out.mark4=nxMarkHtml('x.y (z)','.y (');
// まとめ
const R=[{file:'f1',line:3,type:'transcript',display:'D1 L3',text:'t1'},{file:'f2',line:0,type:'transcript',display:'D2',text:''},
  {file:'f1',line:5,type:'translation',display:'D1 L5',text:'t2'}];
out.groups=nxSearchGroups(R).map(g=>[g.file,g.hits.length]);
// 検索実行
apiResult={results:R};
Object.assign(nxSq,{q:'bud',type:'all'});
await nxSearchRun();
out.url=urls[0];
out.count=nxSq.results.length;
const h=nxSearchHtml();
out.hasCount=h.includes('3');
out.noCap=!h.includes(I18N['nx.sr_cap'].replace('{n}','200').slice(0,6));
out.hitRows=(h.match(/class="sr-hit"/g)||[]).length;out.fileRows=(h.match(/class="sr-file"/g)||[]).length;
// 200 件
apiResult={results:Array.from({length:200},(_,i)=>({file:'f'+i,line:1,type:'transcript',display:'d',text:'x'}))};
await nxSearchRun();
apiResult={results:Array.from({length:201},(_,i)=>({file:'f'+i,line:1,type:'transcript',display:'d',text:'x'}))};
await nxSearchRun();
const ch=nxSearchHtml();
out.cap=ch.includes(I18N['nx.sr_cap'].replace('{n}','200'))&&!ch.includes('201');
// 空の検索は API を呼ばない
urls.length=0;Object.assign(nxSq,{q:'',y:'',m:'',d:'',h:''});await nxSearchRun();
out.noCall=urls.length===0&&nxSq.results===null;
// 見つからない
apiResult={results:[]};Object.assign(nxSq,{q:'zzz'});await nxSearchRun();
out.none=nxSearchHtml().includes(I18N['nx.sr_none']);
// 結果を開く: 文字起こし 5 行目 → data-i=4 を光らせる
nxAddLines(['[t] [A] a','[t] [A] b','[t] [A] c','[t] [A] d','[t] [A] e']);
const ln=lnEl(4);lnEl.last=ln;
nxTxFile='fx';nxTxLoading=false;
nxEl('nxTranscript').querySelector=sel=>sel==='.ln[data-i="4"]'?ln:null;
calls.length=0;timers=[];
nxSearchOpen('fx',5,'transcript');
out.openCalls=calls.slice();
timers.splice(0).forEach(t=>t.fn());
out.scrolled=ln.scrolled;out.flash=ln.cls.has('flash');
nxLines=[];nxMarks=[];
// 実データ相当: 見出し・空行・同じ発言の重複。ファイル行 1..9 = H, 空, はい, はい, 見出し, はい, x, 空, はい
const RAW=['# head','','[t1] [A] はい','[t2] [A] はい','## sec','[t3] [A] はい','[t4] [B] x','','[t5] [A] はい'];
nxLines=[];nxMarks=[];nxAddLines(RAW);
const tg=(line,text,type)=>nxSrTarget(line,text,type||'transcript');
out.map={l3:tg(3),l4:tg(4),l6:tg(6),l7:tg(7),l9:tg(9)};            // 通常の行: 1 始まりの行番号→nxLines の index
out.markHit={l1:tg(1),l2:tg(2),l5:tg(5),l8:tg(8)};                  // 見出し・空行: 近い行へ動くだけ（flash なし）
out.beyond=tg(99);out.zero=tg(0);
// 翻訳: 翻訳ファイルにも見出し・空行があり、同じ時刻・話者の行は出てきた順
nxTrRows=[];nxTrMap=new Map();
nxAddTr(['# h','[t1] [A] yes','[t3] [A] ok','','[t3] [A] ok2','[t5] [A] fin']);
out.tr={a:tg(2,'[t1] [A] yes','translation'),b:tg(3,'[t3] [A] ok','translation'),c:tg(5,'[t3] [A] ok2','translation'),
  hdr:tg(1,'# h','translation'),blank:tg(4,'','translation'),mismatch:tg(2,'[t1] [A] other','translation')};
nxRowsDrift=true;out.drift=tg(3);nxRowsDrift=false;
nxLines=[];nxMarks=[];nxTrRows=[];nxTrMap=new Map();
nxAddLines(['[t9] [A] p','[t9] [A] q']);nxAddTr(['# h','[t9] [A] P','[t9] [A] Q']);
out.trDup={p:tg(2,'[t9] [A] P','translation'),q:tg(3,'[t9] [A] Q','translation'),swapped:tg(3,'[t9] [A] P','translation')};
nxLines=[];nxMarks=[];nxTrRows=[];nxTrMap=new Map();
// 行を開くとき: 見出しの結果はスクロールだけ
nxAddLines(RAW);
const ln5=lnEl(2);lnEl.last=ln5;
nxEl('nxTranscript').querySelector=sel=>sel==='.ln[data-i="2"]'?ln5:null;
timers=[];nxSearchOpen('fx',5,'transcript','## sec');timers.splice(0).forEach(t=>t.fn());
out.hdrOpen={scrolled:ln5.scrolled,flash:ln5.cls.has('flash')};
nxLines=[];nxMarks=[];
// 翻訳は +翻訳 表示（T のときだけ）
calls.length=0;nxState.view='T';nxSearchOpen('fx',2,'translation');
out.trCalls=calls.map(c=>c.join(':'));
calls.length=0;nxState.view='R';nxSearchOpen('fx',2,'translation');
out.trKeepR=calls.map(c=>c.join(':'));
// 議事録は右ペインの議事録タブ、行へは動かない
calls.length=0;timers=[];nxState.right=false;nxState.rtab='ai';
nxSearchOpen('fx',7,'summary');
out.sum={right:nxState.right,rtab:nxState.rtab,timers:timers.length};
// 日付だけ（line 0）はファイルを開くだけ
calls.length=0;timers=[];nxSearchOpen('fy',0,'transcript');
out.dateOnly={calls:calls.map(c=>c.join(':')),timers:timers.length};
// 読み込み中は待って再試行し、描画されたらスクロール
nxAddLines(['[t] [A] a','[t] [A] b']);
const ln2=lnEl(1);lnEl.last=ln2;nxTxLoading=true;
nxEl('nxTranscript').querySelector=sel=>(!nxTxLoading&&sel==='.ln[data-i="1"]')?ln2:null;
timers=[];nxSearchOpen('fz',2,'transcript');nxTxFile='fz';
timers.splice(0).forEach(t=>t.fn());
out.waitedBefore=ln2.scrolled;
nxTxLoading=false;
let guard=0;while(timers.length&&!ln2.scrolled&&guard++<5)timers.splice(0).forEach(t=>t.fn());
out.waitedAfter=ln2.scrolled;
console.log(JSON.stringify(out));
})();
"""


def main() -> None:
    if not _NEXT_JS_SEARCH:
        check("モジュールがある", False)
        sys.exit(1)
    r = subprocess.run(["node", "-e", _PRE + _NEXT_JS_SEARCH + _BODY],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-800:])
        sys.exit(1)
    o = json.loads(r.stdout.strip().splitlines()[-1])
    check("キーワードは trim して query に、type は常に付く",
          o["q1"] == "query=Budget&type=all", o["q1"])
    check("日付は year/month/day/hour に、キーワードなしでも作れる",
          o["q2"] == "year=2026&month=10&day=5&hour=9&type=summary", o["q2"])
    check("キーワードも日付も空なら null", o["q3"] is None)
    check("<mark> は先にエスケープし、大文字小文字を無視して元の綴りを囲む",
          o["mark1"] == 'Hello &lt;b&gt;<mark>BUDGET</mark>&lt;/b&gt; &amp; <mark>budget</mark> &quot;x&quot;', o["mark1"])
    check("キーワード自体の記号もエスケープ後に囲む", o["mark2"] == "a<mark>&lt;b</mark>", o["mark2"])
    check("キーワードなしは囲まない", o["mark3"] == "plain")
    check("& を含むキーワードも一度だけエスケープして囲む", o["mark5"] == "a <mark>&amp;</mark> b", o["mark5"])
    check("正規表現の記号はそのまま文字として探す", o["mark4"] == "x<mark>.y (</mark>z)", o["mark4"])
    check("結果はファイルごとにまとめる（出てきた順）", o["groups"] == [["f1", 2], ["f2", 1]], str(o["groups"]))
    check("/api/search に作ったクエリで問い合わせる", o["url"] == "/api/search?query=bud&type=all", o["url"])
    check("件数を出す", o["hasCount"])
    check("ファイル 2 つ、行は line>0 の 2 件だけ（line 0 の f2 は行なしでファイル行のみ）",
          o["fileRows"] == 2 and o["hitRows"] == 2, str((o["fileRows"], o["hitRows"])))
    check("200 件未満では打ち切りの案内を出さない", o["noCap"])
    check("200 件なら打ち切りの案内", o["cap"])
    check("空の検索は API を呼ばない", o["noCall"])
    check("見つからない案内", o["none"])
    check("文字起こしの結果は開いて、読み込み後に line-1 行目へスクロールして光らせる",
          o["openCalls"] == [["open", "fx"]] and o["scrolled"] == "center" and o["flash"], str(o))
    check("行番号は見出し・空行を数えて nxLines の index に直す（重複した発言でも取り違えない）",
          o["map"] == {"l3": {"idx": 0, "flash": True}, "l4": {"idx": 1, "flash": True}, "l6": {"idx": 2, "flash": True},
                       "l7": {"idx": 3, "flash": True}, "l9": {"idx": 4, "flash": True}}, str(o["map"]))
    check("見出し・空行の結果は近い行へ動くだけで光らせない",
          all(v and v["flash"] is False for v in o["markHit"].values()) and o["markHit"]["l1"]["idx"] == 0
          and o["markHit"]["l5"]["idx"] == 2, str(o["markHit"]))
    check("範囲外・0 行目は動かない/末尾へ", o["zero"] is None and o["beyond"] == {"idx": 4, "flash": False}, str((o["zero"], o["beyond"])))
    check("翻訳は翻訳ファイルの行番号から、同じ時刻・話者の n 番目の行へ",
          o["tr"]["a"] == {"idx": 0, "flash": True} and o["tr"]["b"] == {"idx": 2, "flash": True}
          and o["tr"]["c"] is None and o["trDup"]["p"]["idx"] == 0 and o["trDup"]["q"]["idx"] == 1
          and o["trDup"]["swapped"] is None, str((o["tr"], o["trDup"])))
    check("翻訳の見出し・空行・本文が合わない結果は動かさない（誤った行を光らせない）",
          o["tr"]["hdr"] is None and o["tr"]["blank"] is None and o["tr"]["mismatch"] is None, str(o["tr"]))
    check("SSE で追記されて行がずれた可能性があるときは動かさない", o["drift"] is None)
    check("見出しの結果はスクロールするだけで光らせない", o["hdrOpen"] == {"scrolled": "center", "flash": False}, str(o["hdrOpen"]))
    check("翻訳の結果は表示が T のとき TR に切り替える",
          o["trCalls"] == ["view:TR", "open:fx"] or o["trCalls"] == ["open:fx", "view:TR"], str(o["trCalls"]))
    check("翻訳の結果でも R のときは表示を変えない", o["trKeepR"] == ["open:fx"], str(o["trKeepR"]))
    check("議事録の結果は右ペインの議事録タブを開き、行へは動かない",
          o["sum"] == {"right": True, "rtab": "sum", "timers": 0}, str(o["sum"]))
    check("日付だけの結果はファイルを開くだけ", o["dateOnly"] == {"calls": ["open:fy"], "timers": 0}, str(o["dateOnly"]))
    check("読み込み中は待って、描画されてからスクロールする", not o["waitedBefore"] and o["waitedAfter"])
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
