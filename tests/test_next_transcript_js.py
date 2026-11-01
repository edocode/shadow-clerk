"""/next 中央の文字起こし（まとまり・SSE 追記・翻訳列・選択と操作）を node で検証する

実行: uv run python tests/test_next_transcript_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_next_js_core import _NEXT_JS_CORE
from shadow_clerk._daemon_dashboard_next_js_list import _NEXT_JS_LIST
from shadow_clerk._daemon_dashboard_next_js_transcript import _NEXT_JS_TRANSCRIPT
from shadow_clerk.i18n import STRINGS

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


# 試作 dashboard-friendly-ui-interactive.js の今日のメモ（sessions[0].lines）
_MEMO = [
    ("09:02", "自分", "おはようございます"), ("09:03", "相手A", "おはようございます。昨日の件、見ておきました"),
    ("09:04", "自分", "ありがとうございます、助かります"),
    ("10:00", "相手A", "では acme 社との打ち合わせを始めます"), ("10:01", "相手B", "よろしくお願いします。まず見積もりの件からですが"),
    ("10:02", "自分", "前回いただいた要件で金額を出しています"), ("10:03", "相手B", "内訳を見せていただけますか"),
    ("10:04", "自分", "画面に出します。開発が7割、テストが2割です"), ("10:05", "相手A", "テストの割合は妥当だと思います"),
    ("10:06", "相手B", "納期はもう少し早められますか？"), ("10:07", "自分", "範囲を絞れば可能です"),
    ("10:08", "相手B", "どの機能を後回しにできますか"), ("10:09", "自分", "2週間なら前倒しできます"),
    ("10:10", "相手A", "管理画面は次の段階でも構いません"), ("10:11", "自分", "それなら 11/14 に出せます"),
    ("10:12", "相手B", "社内で確認します"), ("10:13", "相手A", "支払い条件は前回どおりでお願いします"),
    ("10:14", "自分", "承知しました"), ("10:15", "相手A", "では次回までに修正版をお送りします"),
    ("10:16", "相手B", "負荷テストの目標値はどうしますか"), ("10:17", "自分", "まだ決めていません。来週までに案を出します"),
    ("10:18", "相手B", "お願いします"), ("10:19", "相手A", "次回は来週の同じ時間で"), ("10:20", "自分", "大丈夫です"),
    ("10:21", "相手B", "議事録は共有いただけますか"), ("10:22", "自分", "今日中にお送りします"),
    ("10:23", "相手A", "以上です"), ("10:24", "相手B", "ありがとうございました"),
    ("12:17", "Claude", "練習用の会議は終えました。ここで終わりにしますか？"), ("12:18", "自分", "終わります"),
    ("13:40", "alice", "ちょっといいですか、レビューの件で"), ("13:41", "自分", "はい、どうぞ"),
    ("13:42", "alice", "テストの書き方を揃えたいです"), ("13:43", "自分", "雛形を作って共有しますね"),
    ("13:44", "alice", "助かります。金曜までにお願いします"),
]
_DAILY = [f"[2026-10-31 {t}:00] [{w}] {x}" for t, w, x in _MEMO]
_MTG = "transcript-202610300900@acme_sync.txt"
_MTG_LINES = ["--- meeting start ---", "[2026-10-30 09:00:00] [alice] Hello everyone",
              "[2026-10-30 09:00:05] [自分] おはようございます", "[2026-10-30 09:01:00] [bob] Shall we start?",
              "[2026-10-30 09:02:00] [Claude] メモを取ります"]
_MTG_TR = ["[2026-10-30 09:00:00] [alice] みなさんこんにちは", "[2026-10-30 09:01:00] [bob] 始めましょうか？"]
_FILES = {
    "files": ["transcript-20261031.txt", _MTG],
    "active": "transcript-20261031.txt",
    "file_info": {
        "transcript-20261031.txt": {"label": "2026-10-31", "dt": "20261031", "meeting_group": None},
        _MTG: {"label": "2026-10-30 09:00 @acme_sync", "dt": "202610300900", "meeting_group": "acme_sync"},
    },
}
_DATA = {"daily": _DAILY, "mtg": _MTG_LINES, "mtgTr": _MTG_TR, "files": _FILES, "mtgName": _MTG}

_PRE = "const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";\nconst DATA=" + json.dumps(_DATA, ensure_ascii=False) + ";\n" + r"""
const mkEl=()=>({textContent:'',innerHTML:'',className:'',title:'',style:{},dataset:{},value:'',disabled:false,children:[],
  scrollTop:0,scrollHeight:1000,clientHeight:200,
  classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
    toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
  handlers:{},addEventListener(t,f){this.handlers[t]=f;},setAttribute(){},getAttribute(){return null;},appendChild(c){this.children.push(c);},
  querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},focus(){},select(){}});
const els={};
const docHandlers={};
const document={getElementById:id=>els[id]||(els[id]=mkEl()),createElement:mkEl,querySelectorAll:()=>[],querySelector:()=>null,
  addEventListener(t,f){docHandlers[t]=f;},body:mkEl(),documentElement:mkEl()};
const localStorage={getItem(){return null;},setItem(){}};
const location={hash:'',pathname:'/next',search:''};
const history={replaceState(a,b,u){location.hash=u.startsWith('#')?u:'';}};
const window={addEventListener(){}};
const clipboard=[];
const navigator={clipboard:{writeText:async t=>{clipboard.push(t);}}};
const setTimeout=()=>0;
const clearTimeout=()=>{};
const setInterval=()=>0;
const posts=[];
const MOCK={translating:false,noTr:false};
const fetch=async (url,opt)=>{
  const ok=v=>({json:async()=>JSON.parse(JSON.stringify(v))});
  if(opt&&opt.method==='POST'){posts.push([url,JSON.parse(opt.body)]);return ok({status:'ok',message:'done'});}
  const q=decodeURIComponent((url.split('file=')[1]||''));
  if(url==='/api/files')return ok(DATA.files);
  if(url.startsWith('/api/transcript?'))return ok({file:q,lines:q===DATA.mtgName?DATA.mtg:DATA.daily});
  if(url.startsWith('/api/translation?'))return ok({file:q.replace(/\.txt$/,'-ja.txt'),
    lines:q===DATA.mtgName&&!MOCK.noTr?DATA.mtgTr:[],translating:MOCK.translating});
  if(url.startsWith('/api/speakers/provisional?'))return ok({status:'ok',labels:{},lines:{}});
  if(url.startsWith('/api/speakers?'))return ok({status:'ok',suggestions:['alice','bob'],groups:['acme','beta'],provisional:false,active:false,translating:false});
  return ok({});
};
/* 現行 _JS_TEMPLATE_SPEAKERS の loadSpeakerGroups（話者の色・グループの候補を読み直す） */
let speakerGroupLoads=0;
async function loadSpeakerGroups(){speakerGroupLoads++;}
const tick=()=>new Promise(r=>setImmediate(r));
const sse=(type,d)=>nxHandlers.filter(([t])=>t===type).forEach(([,h])=>h({data:JSON.stringify(d)}));
// e.target.closest(sel) の偽物: 属性名で合うものだけ返す
const tgt=(attrs,shift)=>({shiftKey:!!shift,target:{closest:sel=>{
  for(const k of Object.keys(attrs))if(sel.includes(k==='i'?'.ln':'data-'+k))return {dataset:attrs};return null;}}});
const lnHtml=()=>els.nxTranscript.innerHTML.split('<div class="ln').slice(1);
"""

_BODY = r"""
(async()=>{
const out={};
for(let k=0;k<6;k++)await tick();
// 1) まとまり
const memo=DATA.daily.map(nxParseLine);
out.chunks=nxFindChunks(memo,10).map(c=>memo[c.from].ts.slice(11,16)+'-'+memo[c.to].ts.slice(11,16));
out.cur=nxState.cur;
out.nLines=nxLines.length;
const html=els.nxTranscript.innerHTML;
out.chunkHeads=(html.match(/class="chunk"/g)||[]).length;
out.gapText=html.includes(nxFmt('nx.chunk_gap',{n:56}));
out.suggestShown=els.nxSuggest.style.display!=='none';

// 2) 会議ファイル: SSE 追記で選択と行メニューが残る / 下端なら追従
nxOpenFile(DATA.mtgName);
for(let k=0;k<4;k++)await tick();
out.mtgLines=nxLines.length;
out.marks=nxMarks.length;
const tx=els.nxTranscript;
tx.handlers.click(tgt({i:'1'}));
tx.handlers.click(tgt({i:'2'}));
tx.handlers.click(tgt({more:'1'}));
out.selBefore=[...nxSel].sort();
out.menuBefore=nxMenu;
tx.scrollHeight=1000;tx.clientHeight=200;tx.scrollTop=800;
sse('transcript',{file:DATA.mtgName,diff:'[2026-10-30 09:03:00] [alice] One more thing\n'});
out.afterAppend=nxLines.length;
out.selAfter=[...nxSel].sort();
out.menuAfter=nxMenu;
out.menuHtml=tx.innerHTML.includes('class="lmenu"');
out.follow=tx.scrollTop;
tx.scrollTop=100;tx.scrollHeight=1000;
sse('transcript',{file:DATA.mtgName,diff:'[2026-10-30 09:04:00] [bob] Sure\n'});
out.noFollow=tx.scrollTop;
sse('transcript',{file:'transcript-20261031.txt',diff:'[2026-10-31 14:00:00] [自分] 別のファイル\n'});
out.otherFileIgnored=nxLines.length;
sse('translation',{file:'transcript-202610300900@acme_sync-ja.txt',diff:'[2026-10-30 09:03:00] [alice] もう一つ\n'});
out.trAppended=nxLines[4].tr;

// 3) 翻訳なし
nxState.view='TR';nxRenderTx(false);
let ls=lnHtml();
out.trCellTranslated=ls[0].includes('みなさんこんにちは');
out.trCellNone=ls[1].includes(I18N['nx.no_tr']);
out.colHeadShown=els.nxColHead.className.includes('show');
// ✕ で翻訳の表示を閉じ、文字起こしだけに戻す（翻訳は止めない）
out.trCloseBtn=els.nxColHead.innerHTML.includes('data-act="tr-close"');
const setViews=[];globalThis.nxSetView=v=>setViews.push(v);
els.nxMain.handlers.click({target:{closest:s=>s.includes('data-act')?{dataset:{act:'tr-close'}}:null}});
out.trClose=[setViews,posts.length];
nxState.view='R';nxRenderTx(false);
ls=lnHtml();
out.rTranslated=ls[0].includes('みなさんこんにちは')&&!ls[0].includes('Hello everyone');
out.rOriginal=ls[1].includes('おはようございます')&&ls[1].includes(I18N['nx.no_tr']);
nxState.view='T';nxRenderTx(false);
out.tNoTr=!tx.innerHTML.includes('class="trn');

// 4) 選択: Shift+クリックで範囲、選択バー
tx.handlers.click(tgt({i:'1'}));tx.handlers.click(tgt({i:'2'}));
out.selCleared=nxSel.size;
tx.handlers.click(tgt({i:'1'}));
tx.handlers.click(tgt({i:'3'},true));
out.range=nxSelRange();
out.selBar=els.nxSelBar.classList.contains('show');
out.selCount=els.nxSelCount.textContent;
// コピー
els.nxMain.handlers.click({target:{closest:s=>s.includes('data-sa')?{dataset:{sa:'copy'}}:null}});
await tick();
out.clip=clipboard[0];
// 削除
els.nxMain.handlers.click({target:{closest:s=>s.includes('data-sa')?{dataset:{sa:'delete'}}:null}});
out.delShown=els.nxDelModal.classList.contains('show');
posts.length=0;
await nxDoDelete();
out.delPost=posts[0];
// 話した人を直す（Claude の行は送らない）
for(let k=0;k<3;k++)await tick();
nxSel=new Set([2,3]);
await nxOpenRelabel();
out.spkOkEnabled=!els.nxSpkOk.disabled;
out.grpSuggest=els.grpSuggest?els.grpSuggest.innerHTML:null;
els.nxSpkName.value='carol';
posts.length=0;speakerGroupLoads=0;
await nxSaveRelabel();
out.spkPost=posts[0];
out.groupReload=speakerGroupLoads;
// 2 行を選ぶと「2 行の間を全部」。範囲の行数（自分の行は端が自分のときだけ）、グループ・個人区分も現行と同じ本文
nxSel=new Set([0,2]);
await nxOpenRelabel();
out.rangeOpt=!els.nxSpkScopeRangeOpt.hidden;
els.nxSpkScopeRange.checked=true;els.nxSpkScopeRange.handlers.change();
out.rangeTarget=els.nxSpkTarget.textContent;
els.nxSpkName.value='dave';
els.nxSpkPerson.checked=false;els.nxSpkPerson.handlers.change();
out.groupShown=!els.nxSpkGroup.hidden;
els.nxSpkGroup.value='acme';els.nxSpkGroup.handlers.input();
posts.length=0;
await nxSaveRelabel();
out.rangePost=posts[0];
nxSel=new Set([1]);
await nxOpenRelabel();
out.oneLine=[els.nxSpkScopeRangeOpt.hidden,els.nxSpkScopeLinesText.textContent];
// 翻訳の作り直し（確認モーダル → translate_regenerate <dt@name>）
posts.length=0;
els.nxMain.handlers.click({target:{closest:s=>s.includes('data-act')?{dataset:{act:'tr-regen'}}:null}});
out.cfShown=els.nxCfModal.classList.contains('show');
out.cfTitle=els.nxCfTitle.textContent;
els.nxCfOk.handlers.click();
await tick();
out.regenCmd=posts.map(p=>p[1].command);
// ヘッダの翻訳トグル: 記録中でないファイルなら日付引数、表示は ＋翻訳 に
posts.length=0;nxState.translating=false;nxState.view='T';
nxToggleTranslate();await tick();
out.startCmd=posts.map(p=>p[1].command);
out.viewAfterStart=nxState.view;
// ミュート中の帯
nxState.muteMic=true;nxState.useMic=true;nxRenderAll();
out.muteBand=els.nxMuteBand.textContent;
out.muteBandShown=els.nxMuteBand.classList.contains('show');

// 5) 翻訳中の表示は翻訳先のファイルだけ（記録中の翻訳が動いていても過去のファイルは「翻訳なし」）
MOCK.translating=true;MOCK.noTr=true;nxState.translating=true;nxTrTarget='';
nxLoadTranscript(DATA.mtgName);for(let k=0;k<4;k++)await tick();
nxState.view='TR';nxRenderTx(false);
out.pastBusy=tx.innerHTML.includes(I18N['nx.tr_busy']);
out.pastNoTr=lnHtml()[0].includes(I18N['nx.no_tr']);
nxOpenFile('transcript-20261031.txt');for(let k=0;k<4;k++)await tick();
out.liveBusy=tx.innerHTML.includes(I18N['nx.tr_busy']);
nxToggleTranslate();await tick();
out.stopCmd=posts[posts.length-1][1].command;
out.busyAfterStop=tx.innerHTML.includes(I18N['nx.tr_busy']);
MOCK.translating=false;MOCK.noTr=false;
// 6) 途中の文字起こし: 記録中のファイルだけ、最後の行の下に薄く。確定した行が来たら消える
nxState.view='T';nxRenderTx(false);
sse('interim_transcript',{source:'monitor',speaker:'相手',text:'途中の発言',timestamp:'14:00:00'});
out.interimShown=tx.innerHTML.includes('ln interim')&&tx.innerHTML.includes('途中の発言');
out.interimLast=tx.innerHTML.lastIndexOf('ln interim')>tx.innerHTML.lastIndexOf('data-i=');
sse('interim_transcript',{source:'monitor',speaker:'相手',text:'途中の発言です',timestamp:'14:00:01'});
out.interimReplaced=(tx.innerHTML.match(/ln interim/g)||[]).length===1&&tx.innerHTML.includes('途中の発言です');
nxState.view='TR';
sse('interim_translation',{source:'monitor',speaker:'相手',text:'途中の発言です',translated:'still talking',timestamp:'14:00:01'});
out.interimTr=tx.innerHTML.includes('still talking');
const nBefore=nxLines.length;
sse('transcript',{file:'transcript-20261031.txt',diff:'[2026-10-31 14:00:05] [相手] 途中の発言です。\n'});
out.interimClearedByFinal=!tx.innerHTML.includes('ln interim')&&nxLines.length===nBefore+1;
sse('interim_transcript',{source:'monitor',speaker:'相手',text:'もう一度',timestamp:'14:01:00'});
sse('interim_clear',{source:'monitor'});
out.interimClearedByEvent=!tx.innerHTML.includes('ln interim');
nxOpenFile(DATA.mtgName);for(let k=0;k<4;k++)await tick();
sse('interim_transcript',{source:'monitor',speaker:'相手',text:'別の会議',timestamp:'14:02:00'});
out.interimNotOnPast=!tx.innerHTML.includes('ln interim');
// 7) ⋯ の削除をキャンセルすると元の選択に戻る / 開いたメニューの余白クリックで選択は変わらない
nxSel=new Set([0,1]);nxMenu=3;nxRenderTx(false);
tx.handlers.click({target:{closest:s=>s.includes('data-lm')?{dataset:{lm:'delete'}}:null}});
out.delOne=[...nxSel];
els.nxDelCancel.handlers.click();
out.restored=[...nxSel].sort();
nxMenu=2;nxRenderTx(false);
tx.handlers.click({target:{closest:s=>s.includes('.lmenu')||s.includes('.ln')?{dataset:{i:'2'}}:null}});
out.menuGapClick=[...nxSel].sort();
console.log(JSON.stringify(out));
})();
"""


def main() -> None:
    r = subprocess.run(["node", "-e", _PRE + _NEXT_JS_CORE + _NEXT_JS_LIST + _NEXT_JS_TRANSCRIPT + _BODY],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-1200:])
        sys.exit(1)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    ja = STRINGS["ja"]
    check("nxFindChunks: 試作の今日のメモを gapMin=10 で 4 まとまり",
          out["chunks"] == ["09:02-09:04", "10:00-10:24", "12:17-12:18", "13:40-13:44"], repr(out["chunks"]))
    check("日次ファイルを開くと全行を読み、まとまりごとの見出しと会話なしの間隔を出す",
          out["cur"] == "transcript-20261031.txt" and out["nLines"] == 35 and out["chunkHeads"] == 4 and out["gapText"],
          repr((out["cur"], out["nLines"], out["chunkHeads"], out["gapText"])))
    check("まとまりが 2 つ以上なら 💡 案内を出す", out["suggestShown"])
    check("会議ファイル: 行と --- 区切り行を分けて持つ", out["mtgLines"] == 4 and out["marks"] == 1,
          repr((out["mtgLines"], out["marks"])))
    check("SSE 追記: 選択 {1,2} と行メニューが残る",
          out["selBefore"] == [1, 2] and out["selAfter"] == [1, 2] and out["menuBefore"] == 1
          and out["menuAfter"] == 1 and out["menuHtml"] and out["afterAppend"] == 5,
          repr((out["selAfter"], out["menuAfter"], out["afterAppend"])))
    check("SSE 追記: 下端にいれば追従、上にいれば追従しない", out["follow"] == 1000 and out["noFollow"] == 100,
          repr((out["follow"], out["noFollow"])))
    check("ほかのファイルの追記は混ぜない", out["otherFileIgnored"] == 6, repr(out["otherFileIgnored"]))
    check("翻訳の SSE はタイムスタンプで行に付く", out["trAppended"] == "もう一つ", repr(out["trAppended"]))
    check("翻訳の ✕ は文字起こしだけの表示に戻し、コマンドは送らない",
          out["trCloseBtn"] and out["trClose"] == [["T"], 0], repr((out["trCloseBtn"], out["trClose"])))
    check("＋翻訳: 翻訳がある行は翻訳、無い行は「翻訳なし」", out["trCellTranslated"] and out["trCellNone"] and out["colHeadShown"],
          repr((out["trCellTranslated"], out["trCellNone"])))
    check("翻訳だけ: 翻訳がある行は翻訳だけ、無い行は原文と「翻訳なし」", out["rTranslated"] and out["rOriginal"],
          repr((out["rTranslated"], out["rOriginal"])))
    check("文字起こしだけでは翻訳列を出さない", out["tNoTr"])
    check("クリックで選択を外し、Shift+クリックで範囲", out["selCleared"] == 0 and out["range"] == [1, 3],
          repr((out["selCleared"], out["range"])))
    check("選択バーに N 行選択中", out["selBar"] and out["selCount"] == ja["nx.sel_count"].replace("{n}", "3"),
          repr(out["selCount"]))
    check("📋 コピーは選んだ行をそのままクリップボードへ",
          out["clip"] == "\n".join(_MTG_LINES[2:5]), repr(out["clip"]))
    check("削除は現行 doBulkDel と同じ本文", out["delShown"] and out["delPost"] == [
        "/api/transcript/delete", {"lines": _MTG_LINES[2:5], "file": _MTG}], repr(out["delPost"]))
    check("話した人を直すは現行 saveRelabel と同じ本文（Claude の行は除く）", out["spkOkEnabled"] and out["spkPost"] == [
        "/api/speakers/assign-lines",
        {"file": _MTG, "lines": [{"ts": "2026-10-30 09:01:00", "label": "bob"}], "name": "carol"}], repr(out["spkPost"]))
    check("2 行なら「2 行の間を全部」。scope:'range' とグループ・個人区分を現行 saveRelabel と同じに送る",
          out["rangeOpt"] and out["groupShown"]
          and out["rangeTarget"] == ja["dash.relabel_target_range"].replace("{count}", "2")
          and out["rangePost"] == ["/api/speakers/assign-lines", {
              "file": _MTG, "lines": [{"ts": "2026-10-30 09:00:00", "label": "alice"},
                                      {"ts": "2026-10-30 09:01:00", "label": "bob"}],
              "name": "dave", "group": "acme", "person": False, "scope": "range"}],
          repr((out["rangeTarget"], out["rangePost"])))
    check("グループの候補（grpSuggest）を /api/speakers の groups で埋める",
          out["grpSuggest"] == '<option value="acme"><option value="beta">', repr(out["grpSuggest"]))
    check("保存したら現行 saveRelabel と同じく loadSpeakerGroups で読み直す", out["groupReload"] == 1, repr(out["groupReload"]))
    check("1 行だけなら範囲は出さない", out["oneLine"] == [True, ja["dash.relabel_scope_one"]], repr(out["oneLine"]))
    check("翻訳の 🔄 作り直す は確認モーダルから translate_regenerate <日付@会議名>",
          out["cfShown"] and out["cfTitle"] == ja["nx.tr_regen_title"]
          and out["regenCmd"] == ["translate_regenerate 202610300900@acme_sync"], repr(out["regenCmd"]))
    check("ヘッダの翻訳開始は開いているファイルの引数付きで、表示を ＋翻訳 に",
          out["startCmd"] == ["translate_start 202610300900@acme_sync"] and out["viewAfterStart"] == "TR",
          repr((out["startCmd"], out["viewAfterStart"])))
    check("ミュート中の帯", out["muteBandShown"] and out["muteBand"] == ja["nx.mute_band_mic"], repr(out["muteBand"]))
    check("記録中の翻訳が動いていても、翻訳先でない過去のファイルは「翻訳なし」",
          not out["pastBusy"] and out["pastNoTr"], repr((out["pastBusy"], out["pastNoTr"])))
    check("記録中のファイルで翻訳がまだ無ければ「翻訳しています」、translate_stop で消える",
          out["liveBusy"] and out["stopCmd"] == "translate_stop" and not out["busyAfterStop"],
          repr((out["liveBusy"], out["stopCmd"], out["busyAfterStop"])))
    check("途中の文字起こしは記録中のファイルの最後に 1 行、次の途中結果で置き換わる",
          out["interimShown"] and out["interimLast"] and out["interimReplaced"],
          repr((out["interimShown"], out["interimLast"], out["interimReplaced"])))
    check("途中の翻訳は ＋翻訳 の列に出る", out["interimTr"])
    check("確定した行・interim_clear で途中の行は消える", out["interimClearedByFinal"] and out["interimClearedByEvent"],
          repr((out["interimClearedByFinal"], out["interimClearedByEvent"])))
    check("過去のファイルには途中の行を出さない", out["interimNotOnPast"])
    check("⋯ の削除をキャンセルすると元の選択に戻る", out["delOne"] == [3] and out["restored"] == [0, 1],
          repr((out["delOne"], out["restored"])))
    check("開いた行メニューの余白クリックで選択は変わらない", out["menuGapClick"] == [0, 1], repr(out["menuGapClick"]))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
