"""Shadow-clerk daemon: ダッシュボード JavaScript (登録済みの人の声紋の塊: 表示・消す・移す・戻す、声紋の書き出し・取り込み)

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
// 書き出し・取り込み。_vpCounts は loadVoiceprints が入れる（名前 → 声紋の件数）
let _vpCounts={},_vpImport=null,_vpImportRows=[];
function _vpPicks(){return [...document.querySelectorAll('#vpRows input.vp-pick')];}
function _fillVpGroupPicker(groups){
  const sel=document.getElementById('vpPickGroup');sel.innerHTML='';
  const opt=(v,text)=>{const o=document.createElement('option');o.value=v;o.textContent=text;sel.appendChild(o);};
  opt('',I18N['dash.vp_pick_group']);opt('*',I18N['dash.vp_pick_all']);
  for(const g of [...new Set(groups.filter(Boolean))].sort())opt(g,g);
}
function vpPickGroup(sel){
  const g=sel.value;sel.value='';
  for(const c of _vpPicks())if(!c.disabled&&(g==='*'||c.dataset.group===g))c.checked=true;
}
async function exportVoiceprints(){
  const names=_vpPicks().filter(c=>c.checked).map(c=>c.dataset.name);
  if(!names.length){alert(I18N['dash.vp_export_none']);return;}
  const d=await _postJSON('/api/voiceprints/export',{names});
  if(!d)return;
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([JSON.stringify(d.data)],{type:'application/json'}));
  a.download=d.filename;a.click();URL.revokeObjectURL(a.href);
  showToast(d.message);
}
async function readVoiceprintImport(input){
  const f=input.files[0];input.value='';
  if(!f)return;
  let data=null;
  try{data=JSON.parse(await f.text());}catch(e){}
  if(!data||data.format!=='shadow-clerk-voiceprints'||!Array.isArray(data.people)){alert(I18N['dash.vp_import_invalid']);return;}
  _vpImport=data;renderVoiceprintImport();
}
function renderVoiceprintImport(){
  const box=document.getElementById('vpImport');box.innerHTML='';_vpImportRows=[];
  if(!_vpImport)return;
  box.appendChild(_span(I18N['dash.vp_import_from'].replace('{date}',_vpImport.exported_at||''),'spk-meta'));
  for(const p of _vpImport.people){
    const row=document.createElement('div');row.className='spk-row vp-person';
    const pick=document.createElement('input');pick.type='checkbox';pick.className='vp-pick';pick.checked=true;
    const to=document.createElement('input');to.type='text';to.value=p.name;to.setAttribute('list','vpNames');
    const state=_span('','spk-meta');
    to.oninput=()=>{
      const v=to.value.trim();
      state.textContent=!v?'':v in _vpCounts?I18N['dash.vp_import_existing'].replace('{name}',v):I18N['dash.vp_import_new'];
    };
    to.oninput();
    const name=_span(p.name,'vp-name');name.title=p.name;
    for(const c of [pick,name,_span(String(p.samples.length),'vp-count'),_span(p.group||'','spk-meta'),to,state])
      row.appendChild(c);
    box.appendChild(row);_vpImportRows.push({from:p.name,pick,to});
  }
  const foot=document.createElement('div');foot.className='vp-share';
  foot.appendChild(_vpButton('dash.vp_import_apply',importVoiceprints));
  foot.appendChild(_vpButton('dash.cancel',()=>{_vpImport=null;renderVoiceprintImport();}));
  box.appendChild(foot);
}
async function importVoiceprints(){
  const mapping={};
  for(const r of _vpImportRows){
    if(!r.pick.checked)continue;
    const v=r.to.value.trim();
    if(!v){alert(I18N['dash.vp_import_empty_name']);return;}
    mapping[r.from]=v;
  }
  if(!Object.keys(mapping).length)return;
  const d=await _postJSON('/api/voiceprints/import',{data:_vpImport,mapping});
  if(!d)return;
  _vpImport=null;renderVoiceprintImport();showToast(d.message);
  await loadSpeakerGroups();await loadVoiceprints();
}
"""
