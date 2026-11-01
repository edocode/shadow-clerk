"""Shadow-clerk daemon: /next ダッシュボード JavaScript — その他 ▾ メニュー（現行のモーダル・押して話す・話す言語）と音声コマンドの応答"""
from __future__ import annotations

# 用語集・今日の予定・音声コマンド・設定・使い方は、流用する現行のモーダル（openGlossary ほか）をそのまま開く。
# 現行の関数は流用モジュールにあり、ここより後ろで読み込まれるので、クリックした時点の名前で呼ぶ。
# 音声コマンドの応答（SSE response）はトースト。短いものは「もう一度」で出し直せる（かんたんには応答タブが無い）。
# nxRespShort 文字を超えるか改行を含むものは頭だけ出し、全文は下ドロワーの「応答」タブに置く
_NEXT_JS_MORE = r"""
/* --- more menu / PTT / spoken language / voice-command response --- */
const nxRespShort=80;
function nxHelpKey(e){
  if(e.key==='Escape'){e.stopPropagation();closeHelp();return;}
  if(e.key!=='Tab')return;
  const items=nxEl('helpModal').querySelectorAll('button,a[href],summary');
  const first=items[0],last=items[items.length-1];
  if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}
  else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}
}
async function nxTogglePtt(){
  const on=!(nxState.status||{}).ptt;
  if(!await nxCmd(on?'ptt_on':'ptt_off'))return;
  if(nxState.status)nxState.status.ptt=on;
  nxRenderMore();
}
function nxLangLabel(lang){return !lang||lang==='auto'?I18N['nx.st_lang_auto']:I18N['nx.st_lang_'+lang]||lang;}
/* 現行のヘッダ #asrInfo と同じ書き方 */
function nxAsrLabel(st){return st.asr_backend==='whisper'?'Whisper: '+st.asr_model_id:st.asr_backend||'';}
function nxRenderMore(){
  const st=nxState.status||{},asr=nxAsrLabel(st);
  nxEl('nxMiGcal').hidden=!st.gcal_enabled;
  nxEl('nxMiPtt').classList.toggle('on',!!st.ptt);
  nxEl('nxMiPttSt').textContent=I18N[st.ptt?'nx.mi_on':'nx.mi_off'];
  nxEl('nxMiLangSub').textContent=nxLangLabel(st.language)+(asr?' · '+asr:'');
  nxEl('nxLgModel').textContent=asr||'—';
  // ヘッダの言語（現行のヘッダ #langSel と同じ auto / ja / en …）。一覧は流用する設定の LANG_OPTS で、描画のときには読み込み済み
  const q=nxEl('nxLangQuick');
  if(!q.dataset.ready){q.dataset.ready='1';q.innerHTML=['auto',...LANG_OPTS].map(l=>'<option value="'+l+'">'+l+'</option>').join('');}
  if(document.activeElement!==q)q.value=st.language||'auto';
}
/* 言語の一覧は現行の設定（LANG_OPTS）と同じ。現行のヘッダの言語セレクト（onLangChange）と同じコマンドを送る */
function nxOpenLang(){
  const sel=nxEl('nxLgSel');
  sel.innerHTML=['auto',...LANG_OPTS].map(l=>'<option value="'+l+'">'+nxEsc(nxLangLabel(l))+'</option>').join('');
  sel.value=(nxState.status||{}).language||'auto';
  nxRenderMore();
  nxModal('nxLgModal',true);
}
async function nxSetLang(lang){
  if(!await nxCmd(lang==='auto'?'unset_language':'set_language '+lang))return;
  if(nxState.status)nxState.status.language=lang==='auto'?null:lang;
  nxRenderAll();
  nxToast(nxFmt('nx.lg_changed',{lang:nxLangLabel(lang)}));
}
/* 認識モデルは現行でも設定（文字起こし のタブ）で選ぶ */
async function nxLangToCfg(){
  nxModal('nxLgModal',false);
  await openCfg();
  cfgShowTab(CFG_TAB_IDS.indexOf('transcription'));
}
/* 応答タブのためにくわしく表示にするが、選んだモードとしては覚えない */
function nxShowResp(){
  if(!nxIsAdv())nxSetAdv(true,false);
  nxState.dtab='resp';nxState.bottom=true;
  nxRenderAll();
}
function nxOnResponse(d){
  const text=(d.content||'').trim();
  if(!text)return;
  nxEl('nxRespView').textContent=text;
  if(text.length<=nxRespShort&&!text.includes('\n')){nxToast('💬 '+text,[I18N['nx.resp_again'],()=>nxOnResponse(d)]);return;}
  nxToast('💬 '+text.split('\n')[0].slice(0,nxRespShort)+'…',[I18N['nx.resp_more'],nxShowResp]);
}
function nxMoreInit(){
  const item=(id,fn)=>nxEl(id).addEventListener('click',()=>{nxCloseMenus(null);fn();});
  item('nxMiGlossary',()=>openGlossary());
  item('nxMiGcal',()=>openGcal());
  item('nxMiCmds',()=>openCustomCmds());
  item('nxMiCfg',()=>openCfg());
  item('nxMiHelp',()=>openHelp());
  item('nxMiLang',nxOpenLang);
  // 押して話すはメニューを開いたまま、いまの状態を見せる
  nxEl('nxMiPtt').addEventListener('click',nxTogglePtt);
  nxEl('nxLgSel').addEventListener('change',e=>nxSetLang(e.target.value));
  nxEl('nxLangQuick').addEventListener('change',e=>{nxSetLang(e.target.value);e.target.blur();});
  nxEl('nxLgCfg').addEventListener('click',nxLangToCfg);
  nxEl('nxLgClose').addEventListener('click',()=>nxModal('nxLgModal',false));
  nxOn('ptt',d=>{if(nxState.status)nxState.status.ptt=!!d.active;nxRenderMore();});
  nxOn('asr_status',d=>{
    if(nxState.status)Object.assign(nxState.status,{asr_backend:d.asr_backend,asr_model_id:d.asr_model_id},
      d.language?{language:d.language}:{});
    nxRenderMore();
  });
  nxOn('response',nxOnResponse);
  nxRenderers.push(nxRenderMore);
  // 現行と同じく、開いたときに初めての人へのようこそ・同梱スキルが新しくなった知らせ（流用する _JS_TEMPLATE_MODALS）。
  // 流用モジュールはこのモジュールより後ろで読み込まれるので、nxInit の最初の描画で 1 度だけ呼ぶ
  let started=false;
  nxRenderers.push(()=>{if(started)return;started=true;
    maybeShowWelcome().then(shown=>{if(!shown)maybeShowSkillUpdate();});});
}
nxMoreInit();
"""
