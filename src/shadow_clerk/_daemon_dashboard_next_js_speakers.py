"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 話者の名前付けと覚えている声

モーダルは現行のまま（_JS_TEMPLATE_SPEAKERS / _JS_TEMPLATE_VOICEPRINTS と _HTML_SPEAKER_MODAL）。ここには
/next が現行と変える所だけを置き、_daemon_dashboard_next_js_shims.py が現行の関数をこれらに差し替える:
confirm の代わりに確認モーダル（nxConfirm）、名前付けの後の「元に戻す」のトースト（/api/speakers/undo。
/api/speakers/assign が返す history_ids を使う）
"""
from __future__ import annotations

# 保存の結果（/api/speakers/assign の応答）は、現行 saveSpeakers が使う _postJSON を包んで受け取る
_NEXT_JS_SPEAKERS = r"""
/* --- speakers: 話者の名前付け（現行のモーダルを流用） --- */
let nxSpkSaved=null;
/* 現行 _postJSON を包む。名前付けの保存の応答だけ控える */
async function nxPostJSON(orig,url,body){
  const d=await orig(url,body);
  if(url==='/api/speakers/assign')nxSpkSaved=d;
  return d;
}
/* 現行の saveSpeakers を包む。履歴に残った名前付け（history_ids）を「元に戻す」で取り消せるようにする。
   議事録があれば先に作り直すかを確かめ、答えた後のトーストに「元に戻す」を付ける（確かめる間に消えないように） */
async function nxSaveSpeakers(orig){
  const file=_spkFile;
  nxSpkSaved=null;
  await orig();
  const d=nxSpkSaved;
  if(!d||d.provisional)return;
  const ids=d.history_ids||[],undo=ids.length?[[I18N['nx.spk_undo'],()=>nxUndoNamings(file,[...ids].reverse())]]:[];
  if(d.has_summary)nxAskRegenSummary(file,d.message||'',...undo);
  else if(undo.length)nxToast(d.message||'',...undo);
}
/* 取り消せたら true。1 件目で失敗したら何も読み直さない（現行 undoNaming と同じ） */
async function nxUndoNamings(file,ids){
  const msgs=[];let sum=false,done=0;
  for(const id of ids){
    let d=null;
    try{d=await nxApi('/api/speakers/undo',{file,id});}catch(e){}
    if(!d||d.status!=='ok'){msgs.push((d&&d.message)||I18N['nx.spk_undo_failed']);break;}
    done++;
    if(d.message)msgs.push(d.message);
    sum=sum||!!d.has_summary;
  }
  if(msgs.length)nxToast(msgs.join(' '));
  if(!done)return false;
  if(file===nxTxFile)nxLoadTranscript(file,true);
  await loadSpeakerGroups();
  if(sum)nxAskRegenSummary(file);
  return done===ids.length;
}
/* モーダルの履歴の「取り消す」。取り消したらモーダルを開き直す（現行 undoNaming と同じ） */
function nxAskUndoNaming(r){
  nxConfirm({title:I18N['dash.naming_undo_confirm'].replace('{label}',r.label).replace('{name}',r.name),text:'',
    ok:I18N['dash.naming_undo'],onOk:async()=>{if(await nxUndoNamings(_spkFile,[r.id]))await openSpeakerModal();}});
}
function nxAskDeleteVoiceprint(name){
  nxConfirm({title:I18N['dash.voiceprint_delete_confirm'].replace('{name}',name),text:'',ok:I18N['nx.del_ok'],
    onOk:async()=>{if(await _postJSON('/api/voiceprints/delete',{name}))await loadVoiceprints();}});
}
/* 塊の行。「消す」（現行は confirm）だけを確認モーダルに付け替える。ボタンは文言で探す（並び順に頼らない） */
function nxVpClusterRow(orig,name,c){
  const row=orig(name,c),del=[...row.children].find(x=>x.tagName==='BUTTON'&&x.textContent===I18N['dash.vp_delete']);
  if(del)del.onclick=()=>nxConfirm({title:I18N['dash.vp_delete_confirm'].replace('{name}',name).replace('{count}',c.count),
    text:'',ok:I18N['nx.del_ok'],onOk:()=>_vpAction(name,'/api/voiceprints/delete-samples',{name,keys:c.keys})});
  return row;
}
nxEl('nxSpeakersBtn').addEventListener('click',()=>openSpeakerModal());
"""
