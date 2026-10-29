"""Shadow-clerk daemon: ダッシュボード JavaScript (登録済みの人の声紋の塊: 表示・消す・移す・戻す)

speakers の loadVoiceprints / _postJSON / _span / _spkFile / loadSpeakerGroups と、core の loadT / loadR、
modals の showToast に依存するため、連結順は speakers の後でなければならない。
"""
from __future__ import annotations

_JS_TEMPLATE_VOICEPRINTS = r"""
function vpShowButton(name,box){return _vpButton('dash.vp_show',()=>toggleVoiceprintClusters(name,box));}
function _vpButton(key,fn){
  const b=document.createElement('button');b.textContent=I18N[key];b.onclick=fn;return b;
}
async function toggleVoiceprintClusters(name,box){
  const open=box.dataset.open==='1';
  box.innerHTML='';box.dataset.open=open?'':'1';
  if(open)return;
  let d;
  try{d=await(await fetch('/api/voiceprints/clusters?name='+encodeURIComponent(name))).json();}catch(e){box.textContent=String(e);return;}
  if(d.status!=='ok'){box.textContent=d.message||'';return;}
  for(const c of d.clusters)box.appendChild(_vpClusterRow(name,c));
}
function _vpClusterRow(name,c){
  const row=document.createElement('div');row.className='spk-row vp-cluster vp-'+c.kind;
  const kind=_span(I18N['dash.vp_kind_'+c.kind]||c.kind,'vp-kind');
  if(c.kind==='different')kind.appendChild(_span(I18N['dash.vp_kind_different_hint'],'vp-hint'));
  row.appendChild(kind);
  row.appendChild(_span(I18N['dash.speakers_samples'].replace('{count}',c.count),'spk-meta'));
  row.appendChild(_span(c.sources.map(s=>s.file+(s.labels.length?' ('+s.labels.join(', ')+')':'')).join(', '),'vp-sources'));
  const ex=_span(c.example,'spk-example');ex.title=c.example;row.appendChild(ex);
  const body={name,keys:c.keys};
  if(c.kind==='different'){
    const form=_span('','vp-move'),to=document.createElement('input');form.hidden=true;
    to.type='text';to.setAttribute('list','spkSuggest');form.appendChild(to);
    form.appendChild(_vpButton('dash.vp_move_apply',()=>{
      const v=to.value.trim();
      if(v)return _vpAction(name,'/api/voiceprints/move',{...body,to:v},true);
    }));
    row.appendChild(_vpButton('dash.vp_delete',()=>{
      if(confirm(I18N['dash.vp_delete_confirm'].replace('{name}',name).replace('{count}',c.count)))
        return _vpAction(name,'/api/voiceprints/delete-samples',body);
    }));
    row.appendChild(_vpButton('dash.vp_move',()=>{form.hidden=false;to.focus?.();}));
    row.appendChild(form);
  }else if(c.kind==='outlier'){
    row.appendChild(_vpButton('dash.vp_restore',()=>_vpAction(name,'/api/voiceprints/restore',body)));
  }
  return row;
}
// 「自分の声を登録」: 取り終えるまでボタンに残り秒数を出し、終わったら一覧を読み直す
async function enrollSelfVoice(btn){
  const d=await _postJSON('/api/voiceprints/enroll-self',{});
  if(!d)return;
  showToast(d.message);
  const label=btn.textContent;let left=d.seconds;
  btn.disabled=true;btn.textContent=label+' ('+left+')';
  const timer=setInterval(()=>{
    if(--left>0){btn.textContent=label+' ('+left+')';return;}
    clearInterval(timer);btn.disabled=false;btn.textContent=label;
    showToast(I18N['dash.vp_enroll_done']);loadVoiceprints();
  },1000);
}
async function _vpAction(name,url,body,relabels){
  const d=await _postJSON(url,body);
  if(!d)return;
  if(d.message)showToast(d.message);
  if(relabels&&_spkFile){loadT(_spkFile);loadR(_spkFile);}
  if(relabels)await loadSpeakerGroups();
  await loadVoiceprints(name);
}
"""
