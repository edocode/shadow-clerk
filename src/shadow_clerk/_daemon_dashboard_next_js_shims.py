"""Shadow-clerk daemon: /next ダッシュボード JavaScript — shim（流用する現行モジュールが呼ぶ現行コアの名前を nx* へ橋渡しする）

流用するのはコンソールの描画（_JS_TEMPLATE_CONSOLE_ROLE / _JS_TEMPLATE_CONSOLE）とブラウザの読み上げ（_JS_TEMPLATE_SPEECH）、
話者の名前付けと覚えている声（_JS_TEMPLATE_SPEAKERS / _JS_TEMPLATE_VOICEPRINTS）、Claude と会議（_JS_TEMPLATE_TALK。現行コアから使うのは esc だけ。現行の talkActive は /next では nxState.status.talk から
_daemon_dashboard_next_js_talk.py が開く前に揃える）、ようこそ・スキル更新（_JS_TEMPLATE_MODALS）、設定（_JS_TEMPLATE_SETTINGS /
_JS_TEMPLATE_DEVICES）、用語集・音声コマンド・使い方・今日の予定（_JS_TEMPLATE_GLOSSARY / _CUSTOM_CMDS / _HELP_GCAL）。
現行の核（_daemon_dashboard_js_core.py）は読み込まないので、そこにある名前だけをここに置く。
流用モジュールは読み込み時に es を使うので、_NEXT_JS ではこれを流用モジュールより前に連結する。
以後のタスクで流用するものが増えたら、ここに足す（名前の衝突は tests/test_next_dashboard.py が見る）
"""
from __future__ import annotations

_NEXT_JS_SHIMS = r"""
/* --- shims: 現行コアの名前（流用モジュールから呼ばれる） --- */
/* SSE。nxOn に載せるので、再接続で EventSource が作り直されても付け直される。現行のハンドラーは生のイベントを受ける */
const es={addEventListener:(type,fn)=>nxOn(type,(d,e)=>fn(e))};
let curFile=null;
function esc(s){return nxEsc(s);}
function nearBottom(el){return el.scrollTop+el.clientHeight>=el.scrollHeight-40;}
/* 現行の下部ペイン・右ペイン。/next では nxState が開閉を持つ。
   togLogs・togSumPane は流用モジュールが畳まれているとき（#logp・#pnlS）だけ呼び、/next では呼ばれない。名前を解決するためだけに置く */
function togLogs(){nxToggleDrawer();}
function togSumPane(){nxTogglePane('right');}
function switchSumTab(tab){nxState.rtab=tab==='ai'?'ai':'sum';nxState.right=true;nxRenderAll();}
/* 現行の画面の復元。/next は nxState から描くので何もしない */
function restorePanes(){}
function applyPanelMode(){}
function applyFontSize(){}
/* 設定・ようこそ・スキル更新の画面が使う、現行コアの書き出し */
function escAttr(s){return nxEsc(s);}
function escJs(s){return s.replace(/\\/g,'\\\\').replace(/'/g,"\\'");}
function docLink(urlKey,textKey){return '<a href="'+nxEsc(I18N[urlKey])+'" target="_blank" rel="noopener">'+nxEsc(I18N[textKey])+'</a>';}
/* _JS_TEMPLATE_MODALS の行の削除・ファイルの削除・会議の切り出しは /next に HTML が無く、呼ばれない（/next は nx 側の画面）。
   名前を解決するためだけに置く */
function getSelectedLines(){return [];}
function deselectAll(){}
function _isMeetingFile(){return false;}
function loadFiles(){}
/* 話者の名前付けの後に現行が読み直す本文。/next は開いているファイルなら文字起こし（翻訳も一緒）を読み直す */
function loadT(f){if(f&&f===nxTxFile)nxLoadTranscript(f,true);}
function loadR(){}
/* 流用モジュールの alert（モデル一覧の取得失敗など）は、画面を止めないトーストにする */
function alert(message){nxToast(String(message));}
/* 話者の名前付け（_JS_TEMPLATE_SPEAKERS / _VOICEPRINTS）が読む、現行コアの記録中のファイルと人のグループ */
let activeFile='';
let spkGroups={names:{},persons:{},groups:{},self_group:''};
/* 現行の loadProvisional は下で差し替えるので呼ばれない（中で使う現行コアの名前を解決するためだけに置く） */
function spSpan(){return '';}
/* 現行の関数を /next のものに差し替える。関数の宣言は読み込み時に巻き上がるので、流用モジュールより前のここで代入できる。
   confirm を使う所は確認モーダル（nxConfirm）に、名前付けの保存は「元に戻す」のトーストを足すように包む。
   現行の showToast は /next では見えない（.toast に .show が付かない）ので nxToast に出す */
showToast=m=>{if(m!=null&&m!=='')nxToast(String(m));};
loadProvisional=f=>{if(f===nxTxFile)nxLoadProvisional(f);};
/* 議事録の作り直しは、包んだ saveSpeakers（nxSaveSpeakers）が「元に戻す」と一緒に確かめる。/next で呼ぶのは saveSpeakers だけ */
regenSummaryFor=()=>{};
{const o=_postJSON;_postJSON=(url,body)=>nxPostJSON(o,url,body);}
undoNaming=nxAskUndoNaming;
deleteVoiceprint=nxAskDeleteVoiceprint;
{const o=saveSpeakers;saveSpeakers=()=>nxSaveSpeakers(o);}
{const o=_vpClusterRow;_vpClusterRow=(name,c)=>nxVpClusterRow(o,name,c);}
nxRenderers.push(()=>{curFile=nxState.cur||null;activeFile=nxActive||'';});
nxRenderers.push(()=>{const l=nxEl('langSel');if(l)l.value=(nxState.status||{}).language||'';});
"""
