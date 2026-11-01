"""Shadow-clerk daemon: /next ダッシュボード JavaScript — Claude と会議（開始モーダル・ヘッダのボタン・会議中の帯）

開始モーダルは /next の見た目で描くが、入力欄は現行と同じ id（talkTopic・talkRoute ほか）にして、
流用する現行の _JS_TEMPLATE_TALK（togTalk・startTalk・talkPost・モードの保存と削除・ペルソナ・声の設定）がそのまま読み書きする。
POST /api/talk-mode の本文は現行の startTalk が作るので、現行と同じになる。#talkModal・#talkPresetModal は現行どおり open クラスで開く。
ここでは、モードの選択（選ぶまで開始できない）・声の届け先のラジオ・会議中の表示だけを足す
"""
from __future__ import annotations

_NEXT_JS_TALK = r"""
/* --- Claude と会議 --- */
let nxTalkMode=null;      // 選んだモード: '' は自由に話す、名前は保存したモード、null はまだ選んでいない
let nxTalkDefaults=null;  // 開いたときの値。モードを選ぶたびにここへ戻してから、そのモードの値を入れる
let nxTalkBusy=false;
const nxTalkFields=[['topic','talkTopic','value'],['persona','talkPersonaSel','value'],['route','talkRoute','value'],
  ['model','talkModel','value'],['workdir','talkWorkdir','value'],['glossary','talkGlossary','checked'],
  ['early_reply','talkEarlyReply','checked'],['skill','talkSkill','value']];
function nxTalkSnap(){return Object.fromEntries(nxTalkFields.map(([k,id,p])=>[k,nxEl(id)[p]]));}
function nxTalkRestore(v){nxTalkFields.forEach(([k,id,p])=>{nxEl(id)[p]=v[k];});}
function nxTalkNow(){return (nxState.status||{}).talk||{};}
/* モードは select で選ぶ（増えても縦に伸びない）。値は 'm:'+名前、'' はまだ選んでいない */
function nxTalkModeOpts(){
  const o=(v,t)=>'<option value="'+nxEsc(v)+'">'+nxEsc(t)+'</option>';
  return o('',I18N['nx.talk_mode_pick'])+o('m:',I18N['nx.talk_free'])+_talkPresets.map(p=>o('m:'+p.name,p.name)).join('');
}
function nxTalkModeDesc(){
  if(nxTalkMode==='')return I18N['nx.talk_free_desc'];
  const f=(_talkPresets.find(p=>p.name===nxTalkMode)||{}).fields||{};
  return f.topic||f.persona||'';
}
/* ラジオは #talkRoute の値から描く（空 = 自分にだけ）。使えない環境では現行の fillRouteSel が select を止める */
function nxRenderTalkRoute(){
  const rs=nxEl('talkRoute'),app=!rs.disabled&&!!rs.value;
  nxEl('nxTalkRouteApp').classList.toggle('disabled',rs.disabled);
  [['nxTalkRouteSelf',!app],['nxTalkRouteApp',app]].forEach(([id,on])=>{
    nxEl(id).classList.toggle('act',on);nxEl(id+'In').checked=on;
  });
}
function nxRenderTalkModal(){
  const sel=nxEl('nxTalkModeSel');
  sel.innerHTML=nxTalkModeOpts();sel.value=nxTalkMode===null?'':'m:'+nxTalkMode;
  nxEl('nxTalkModeDel').hidden=!nxTalkMode;
  nxEl('nxTalkModeDesc').textContent=nxTalkMode===null?'':nxTalkModeDesc();
  nxEl('nxTalkOk').disabled=nxTalkMode===null||nxTalkBusy;
  nxEl('talkPresetSel').value=nxTalkMode||'';
  nxRenderTalkRoute();
}
function nxPickTalkMode(name){
  nxTalkMode=name;
  nxTalkRestore(nxTalkDefaults);
  nxEl('talkPresetSel').value=name;
  loadTalkPreset();
  nxRenderTalkModal();
}
function nxPickRoute(app){
  const rs=nxEl('talkRoute');
  if(!app)rs.value='';
  else if(!rs.value){
    const o=[...rs.options].find(x=>x.value);
    if(o)rs.value=o.value;else nxToast(I18N['nx.talk_route_empty']);
  }
  nxRenderTalkRoute();
}
/* 現行の fillRouteSel は覚えた先を選び直すので、いま選んでいる先（自分にだけを含む）を保つ */
async function nxReloadRoute(){
  const rs=nxEl('talkRoute'),keep=rs.value;
  await fillRouteSel();
  rs.value=!keep||[...rs.options].some(o=>o.value===keep)?keep:'';
  nxRenderTalkRoute();
}
/* 現行の fillRouteSel は覚えた先がいま音を出していなくても選ぶ。/next では「自分にだけ」にしておく */
async function nxDropStaleRoute(){
  const rs=nxEl('talkRoute');
  if(rs.disabled||!rs.value)return;
  const r=await nxApi('/api/talk-route-targets').catch(()=>null);
  if(!(r&&r.targets||[]).some(t=>t.app===rs.value))rs.value='';
}
async function nxOpenTalk(){
  talkActive=false;nxTalkMode=null;
  await togTalk();
  await nxDropStaleRoute();
  nxEl('talkSkill').value='';  // skill はモードで決める。前に開いたときの値を持ち越さない
  nxTalkDefaults=nxTalkSnap();
  nxRenderTalkModal();
}
/* 始まったら、会話の出る記録中のファイルを中央に、くわしく表示ならドロワーの Claude と会議 の画面を開く */
async function nxStartTalk(){
  if(nxTalkMode===null||nxTalkBusy)return;
  nxTalkBusy=true;nxRenderTalkModal();
  await startTalk();
  nxTalkBusy=false;nxRenderTalkModal();
  if(!talkActive)return;
  nxState.dtab='talk';
  if(nxIsAdv())nxState.bottom=true;
  if(nxActive&&nxState.cur!==nxActive)nxOpenFile(nxActive);
  await nxFetchStatus();
}
async function nxEndTalk(){
  const r=await talkPost({on:false});
  nxToast(I18N[r.status==='ok'?'nx.talk_ended':'nx.cmd_failed']);
  await nxFetchStatus();
}
async function nxSaveTalkMode(){
  const name=nxEl('talkPresetNameInput').value.trim();
  if(!name)return;
  await doSaveTalkPreset();
  if(nxEl('talkPresetModal').classList.contains('open'))return;  // 保存できなければ現行は閉じない
  nxTalkMode=name;nxRenderTalkModal();
}
function nxDelTalkMode(name){
  nxConfirm({title:I18N['nx.talk_mode_del'],text:nxFmt('nx.talk_mode_del_text',{name}),ok:I18N['nx.del_ok'],onOk:async()=>{
    nxEl('talkPresetNameInput').value=name;
    await deleteTalkPreset();
    if(nxTalkMode===name){nxTalkMode=null;nxTalkRestore(nxTalkDefaults);}
    nxRenderTalkModal();
  }});
}
function nxRenderTalk(){
  const t=nxTalkNow(),on=!!t.active,r=t.route||{};
  nxEl('nxTalkBtn').classList.toggle('on',on);
  nxEl('nxTalkBtn').setAttribute('aria-pressed',String(on));
  nxEl('nxTalkLabel').textContent=I18N[on?'nx.talk_btn_end':'nx.talk_btn'];
  nxEl('nxTalkBand').classList.toggle('show',on);
  if(!on)return;
  const app=r.app?'→ '+r.app+' ('+I18N[r.connected?'dash.talk_route_connected':'dash.talk_route_disconnected']+')':'';
  nxEl('nxTalkBandInfo').textContent=[t.topic,t.persona,app,t.error&&'⚠ '+t.error].filter(x=>x).join(' / ');
  nxEl('nxTalkBandWhere').textContent=I18N[nxIsAdv()?'nx.talk_band_where_adv':'nx.talk_band_where'];
  nxEl('nxTalkBandWhere').hidden=!nxIsLive({name:nxState.cur});
}
function nxTalkInit(){
  nxRenderers.push(nxRenderTalk);
  nxEl('nxTalkBtn').addEventListener('click',()=>nxTalkNow().active?nxEndTalk():nxOpenTalk());
  nxEl('nxTalkBandEnd').addEventListener('click',nxEndTalk);
  nxEl('nxTalkModeSel').addEventListener('change',e=>{const v=e.target.value;if(v)nxPickTalkMode(v.slice(2));});
  nxEl('nxTalkModeDel').addEventListener('click',()=>{if(nxTalkMode)nxDelTalkMode(nxTalkMode);});
  nxEl('nxTalkRouteSelfIn').addEventListener('change',()=>nxPickRoute(false));
  nxEl('nxTalkRouteAppIn').addEventListener('change',()=>nxPickRoute(true));
  nxEl('talkRoute').addEventListener('change',nxRenderTalkRoute);
  nxEl('nxTalkRouteReload').addEventListener('click',nxReloadRoute);
  nxEl('nxTalkPersonaEdit').addEventListener('click',openPersonas);
  nxEl('nxTalkVoice').addEventListener('click',openVoice);
  nxEl('nxTalkSave').addEventListener('click',openSaveTalkPreset);
  nxEl('nxTalkCancel').addEventListener('click',closeTalk);
  nxEl('nxTalkOk').addEventListener('click',nxStartTalk);
  nxEl('nxTpCancel').addEventListener('click',closeSaveTalkPreset);
  nxEl('nxTpOk').addEventListener('click',nxSaveTalkMode);
  nxEl('talkPresetNameInput').addEventListener('keydown',e=>{if(e.key==='Enter')nxSaveTalkMode();});
  // skill が talk mode を終えたとき（/api/talk-end）も、talk の端末が止まるのでヘッダを戻せる
  nxOn('console',d=>{
    if(d.role==='talk'&&d.running!==undefined&&!!d.running!==!!(nxState.status||{}).talk_console_running)nxFetchStatus();
  });
}
nxTalkInit();
"""
