"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 会議の開始（開始モーダル）と終了"""
from __future__ import annotations

# 「変更」は会議ごとの設定モーダル（_daemon_dashboard_next_js_mtgcfg.py の nxOpenMeetingSettings）を開き、閉じたら戻ってくる
_NEXT_JS_START = r"""
/* --- 会議の開始・終了 --- */
const nxSt={auto:false,analyze:null,cfg:null,lang:'auto',seq:0};
let nxStTimer=null;
/* AI アシスタントのチェックの初期値: 会議の analyze がオン / オフならそれ、未指定なら auto_analyze */
function nxStInitial(analyze,auto){return analyze==null?!!auto:analyze;}
function nxStHint(analyze,auto){
  return I18N[analyze===false?'nx.st_hint_off':analyze==null&&!auto?'nx.st_hint_auto_off':'nx.st_hint_on'];
}
function nxStChips(m){
  if(!m)return [];
  const c=[];
  if(m.analyze===false)c.push(I18N['nx.st_chip_no_analyze']);else if(m.analyze===true)c.push(I18N['nx.st_chip_analyze']);
  if(!m.publish)c.push(I18N['nx.st_chip_no_publish']);else if(m.publish_to==='notion')c.push(I18N['nx.st_chip_notion']);
  if(m.publish_advice)c.push(I18N['nx.st_chip_advice']);
  if(m.workdir)c.push('📁 '+m.workdir);
  return c;
}
function nxRenderStart(){
  nxEl('nxStAssistHint').textContent=nxStHint(nxSt.analyze,nxSt.auto);
  const chips=nxStChips(nxSt.cfg),box=nxEl('nxStCfg');
  box.textContent=nxFmt('nx.st_cfg',{items:chips.length?chips.join('、'):I18N['nx.st_cfg_none']});
  const name=nxEl('nxStName').value.trim();
  if(name){
    const a=document.createElement('a');a.href='#';a.textContent=' '+I18N['nx.st_cfg_change'];
    a.addEventListener('click',e=>{
      e.preventDefault();nxModal('nxStModal',false);
      nxOpenMeetingSettings(name,()=>{nxModal('nxStModal',true);nxStLoadCfg();});
    });
    box.appendChild(a);
  }
}
/* 名前に当たる会議ごとの設定を取り、チェックの初期値と説明を描き直す。遅れて返った古い応答は捨てる */
async function nxStLoadCfg(){
  const name=nxEl('nxStName').value.trim(),seq=++nxSt.seq;
  let m=null;
  if(name){
    try{const d=await nxApi('/api/meeting-settings?meeting='+encodeURIComponent(name));m=d&&d.meetings&&d.meetings[0]||null;}
    catch(e){}
  }
  if(seq!==nxSt.seq)return;
  nxSt.cfg=m;nxSt.analyze=m?m.analyze:null;
  nxEl('nxStAssist').checked=nxStInitial(nxSt.analyze,nxSt.auto);
  nxRenderStart();
}
/* config.yaml の auto_analyze（設定画面「会議開始時に分析」）。会議ごとの analyze が既定のときに効く */
async function nxAutoAnalyze(){
  const cfg=await nxApi('/api/config').catch(()=>null);
  return !!(cfg&&cfg.auto_analyze);
}
function nxStSetLang(lang){
  const sel=nxEl('nxStLang');
  if(![...sel.options].some(o=>o.value===lang)){
    const o=document.createElement('option');o.value=lang;o.textContent=lang;sel.appendChild(o);
  }
  sel.value=lang;
}
async function nxOpenStart(){
  nxSt.lang=(nxState.status&&nxState.status.language)||'auto';
  nxStSetLang(nxSt.lang);
  nxEl('nxStName').value='';nxEl('nxStCal').textContent='';
  nxModal('nxStModal',true);
  [nxSt.auto]=await Promise.all([nxAutoAnalyze(),nxExLoadCal()]);
  const ev=nxCalAtMs(Date.now());
  if(ev&&!nxEl('nxStName').value){nxEl('nxStName').value=ev.summary;nxEl('nxStCal').textContent=I18N['nx.st_cal'];}
  await nxStLoadCfg();
  nxEl('nxStName').focus();
}
function nxOnStName(){
  nxEl('nxStCal').textContent='';
  clearTimeout(nxStTimer);
  nxStTimer=setTimeout(nxStLoadCfg,300);
}
/* チェックを初期値から変えたときだけ、その値をこの回だけの指定として送る（会議ごとの設定より優先する）。
   初期値のままなら送らず設定に従わせる——false を送ると、後で手で起動したアシスタントも監視しなくなる。
   名前が空なら daemon が進行中の予定の名前を付ける。言語を変えられなければ始めない。
   10 秒ごとの /api/status は遅れるので、押した時点の状態を取り直し、ほかで会議が始まっていたら言語も変えない */
async function nxStStart(){
  const name=nxEl('nxStName').value.trim(),checked=nxEl('nxStAssist').checked,lang=nxEl('nxStLang').value;
  const body={action:'start',name};
  if(checked!==nxStInitial(nxSt.analyze,nxSt.auto))body.analyze=checked;
  nxModal('nxStModal',false);
  await nxFetchStatus();
  if(nxState.session){nxToast(I18N['nx.st_already']);return;}
  if(lang!==nxSt.lang&&!await nxCmd(lang==='auto'?'unset_language':'set_language '+lang))return;
  try{
    const d=await nxApi('/api/meeting',body);
    if(d.status!=='ok')nxToast(I18N['nx.cmd_failed']);
  }catch(e){nxToast(I18N['nx.cmd_failed']);}
  await nxFetchStatus();
}
async function nxEndMeeting(){
  if(await nxCmd('end_meeting'))nxToast(I18N['nx.meeting_ended']);
  await nxFetchStatus();
}
function nxStartInit(){
  nxEl('nxMeetingBtn').addEventListener('click',()=>nxState.session?nxEndMeeting():nxOpenStart());
  nxEl('nxStName').addEventListener('input',nxOnStName);
  nxEl('nxStCancel').addEventListener('click',()=>nxModal('nxStModal',false));
  nxEl('nxStOk').addEventListener('click',nxStStart);
}
nxStartInit();
"""
