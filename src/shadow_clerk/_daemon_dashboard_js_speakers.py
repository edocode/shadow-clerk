"""Shadow-clerk daemon: ダッシュボード JavaScript (話者の名前付けと声紋)

core の esc / escAttr / curFile / activeFile / loadT / loadR と、modals の showToast に
依存するため、連結順は core・modals の後でなければならない。
"""
from __future__ import annotations

_JS_TEMPLATE_SPEAKERS = r"""
let _spkFile='';
function spColor(sp,mic){
  if(sp.endsWith('?')&&sp!=='相手?')sp=sp.slice(0,-1);  // 識別の「alice?」は alice の色
  const g=(sp===mic||sp==='自分')?spkGroups.self_group:spkGroups.names[sp];
  const c=g?spkGroups.groups[g]:'';
  return /^#[0-9a-f]{6}$/.test(c||'')?c:'';
}
function recolorSpeakers(){
  const mic=I18N['speaker.mic']||'自分';
  for(const s of document.querySelectorAll('#tp [data-sp],#rp [data-sp]'))s.style.color=spColor(s.dataset.sp,mic);
}
async function loadSpeakerGroups(){
  try{const d=await(await fetch('/api/speaker-groups')).json();if(d.status==='ok'){spkGroups=d;recolorSpeakers();}}catch(e){}
}
function _applyNameDefaults(name,g,p,og,op){
  if(g&&g.dataset.touched!=='1')g.value=name?(spkGroups.names[name]||''):og;
  if(p&&p.dataset.touched!=='1')p.checked=name?!(spkGroups.groups[name]||spkGroups.persons[name]===false):op;
  if(g&&p)g.hidden=p.checked;
}
function onSpkPersonChange(p){
  p.dataset.touched='1';
  const g=[...document.querySelectorAll('#spkRows input[data-group-for]')].find(c=>c.dataset.groupFor===p.dataset.personFor);
  if(g)g.hidden=p.checked;
}
function onRlPersonChange(){
  const p=document.getElementById('rlPerson');p.dataset.touched='1';document.getElementById('rlGroup').hidden=p.checked;
}
function onSpkNameInput(el){
  const l=el.dataset.label,find=(k)=>[...document.querySelectorAll('#spkRows input[data-'+k+'-for]')].find(c=>c.dataset[k+'For']===l);
  const g=find('group'),p=find('person');
  _applyNameDefaults(el.value.trim(),g,p,g?g.dataset.orig||'':'',p?p.dataset.orig==='1':true);
}
function onRlNameInput(){
  _applyNameDefaults(document.getElementById('rlName').value.trim(),document.getElementById('rlGroup'),document.getElementById('rlPerson'),'',true);
}
async function regenSummaryFor(f){
  if(!confirm(I18N['dash.summary_regen_after_naming']))return;
  try{await fetch('/api/summary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:f})});
    showToast(I18N['dash.summary_started']||'');}catch(e){alert(String(e));}
}
function _fillOptions(id,values){
  const dl=document.getElementById(id);dl.innerHTML='';
  for(const v of values){const o=document.createElement('option');o.value=v;dl.appendChild(o);}
}
async function openSpeakerModal(){
  _spkFile=curFile||activeFile;
  const box=document.getElementById('spkRows'),info=document.getElementById('spkInfo');
  box.innerHTML='';info.textContent='';document.getElementById('spkHistory').innerHTML='';
  if(!_spkFile){
    info.textContent=I18N['dash.speakers_none'];document.getElementById('spkSaveBtn').disabled=true;
    await loadVoiceprints();document.getElementById('speakerModal').classList.add('open');return;
  }
  let d;
  try{d=await(await fetch('/api/speakers?file='+encodeURIComponent(_spkFile))).json();}catch(e){alert(String(e));return;}
  if(d.status!=='ok'){alert(d.message||'error');return;}
  _fillOptions('spkSuggest',d.suggestions);_fillOptions('grpSuggest',d.groups||[]);
  info.textContent=!d.labels.length?I18N['dash.speakers_none']:d.active?I18N['dash.speakers_active']
    :d.translating?I18N['dash.speakers_translating']
    :!d.enrollment?I18N['dash.speakers_enrollment_off']:'';
  for(const l of d.labels){
    const row=document.createElement('div');row.className='spk-row';
    row.innerHTML='<span class="spk-label">'+esc(l.label)+'</span>'
      +'<span class="spk-meta">'+esc(I18N['dash.speakers_count'].replace('{count}',l.count))
      +(d.enrollment?' / '+esc(I18N['dash.speakers_samples'].replace('{count}',l.samples)):'')
      +(l.tentative?' / '+esc(I18N['dash.speakers_tentative']):'')+'</span>'
      +'<input type="text" list="spkSuggest" oninput="onSpkNameInput(this)" data-label="'+escAttr(l.label)+'"'
      +' data-named="'+(l.named?'1':'0')+'"'
      +(l.tentative?' data-suggested="'+escAttr(l.suggested)+'" placeholder="'+escAttr(l.suggested)+'"'
        :l.named?' placeholder="'+escAttr(l.label)+'"':'')+'>'
      +'<input type="text" class="spk-group" list="grpSuggest" data-group-for="'+escAttr(l.label)+'"'
      +(l.person===false?'':' hidden')+' oninput="this.dataset.touched=\'1\'" data-orig="'+escAttr(l.group||'')+'" value="'+escAttr(l.group||'')+'" placeholder="'+escAttr(I18N['dash.group_label'])+'">'
      +'<label class="spk-person"><input type="checkbox" onchange="onSpkPersonChange(this)" data-person-for="'+escAttr(l.label)+'"'
      +' data-orig="'+(l.person===false?'0':'1')+'"'+(l.person===false?'':' checked')+'>'+esc(I18N['dash.person_enroll'])+'</label>'
      +(l.tentative?'<label class="spk-person"><input type="checkbox" data-accept-for="'+escAttr(l.label)+'">'
        +esc(I18N['dash.speakers_tentative_accept'].replace('{name}',l.suggested))+'</label>':'')
      +(d.enrollment&&l.auto>0&&l.named&&!l.tentative?'<label class="spk-person"><input type="checkbox" data-confirm-for="'
        +escAttr(l.label)+'">'+esc(I18N['dash.speakers_auto_confirm'].replace('{count}',l.auto))+'</label>':'')
      +'<span class="spk-example" title="'+escAttr(l.example)+'">'+esc(l.example)+'</span>';
    box.appendChild(row);
  }
  document.getElementById('spkSaveBtn').disabled=!d.labels.length||!!(d.active||d.translating);
  renderNamingHistory(d.history||[],d.history_error);
  await loadVoiceprints();
  document.getElementById('speakerModal').classList.add('open');
}
function _span(text,cls){const s=document.createElement('span');s.textContent=text;if(cls)s.className=cls;return s;}
function renderNamingHistory(items,error){
  const box=document.getElementById('spkHistory');box.innerHTML='';
  if(error){box.appendChild(_span(I18N['dash.naming_history_error'],'spk-meta'));return;}
  if(!items.length)return;
  const h=document.createElement('div');h.className='spk-sub';h.textContent=I18N['dash.naming_history_title'];box.appendChild(h);
  for(const r of items){
    const row=document.createElement('div');row.className='spk-row';
    row.appendChild(_span(r.at,'spk-meta'));
    row.appendChild(_span(r.label+' → '+r.name));
    row.appendChild(_span(I18N['dash.speakers_count'].replace('{count}',r.lines)
      +(r.added?' / '+I18N['dash.speakers_samples'].replace('{count}',r.added):''),'spk-meta'));
    if(r.undone)row.appendChild(_span(I18N['dash.naming_undone_mark'],'spk-meta'));
    else{
      const b=document.createElement('button');b.textContent=I18N['dash.naming_undo'];
      b.onclick=()=>undoNaming(r);row.appendChild(b);
    }
    box.appendChild(row);
  }
}
async function undoNaming(r){
  if(!confirm(I18N['dash.naming_undo_confirm'].replace('{label}',r.label).replace('{name}',r.name)))return;
  const f=_spkFile,d=await _postJSON('/api/speakers/undo',{file:f,id:r.id});
  if(!d)return;
  showToast(d.message);loadT(f);loadR(f);await loadSpeakerGroups();
  if(d.has_summary)await regenSummaryFor(f);
  await openSpeakerModal();
}
async function _postJSON(url,body){
  let d;
  try{d=await(await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();}
  catch(e){alert(String(e));return null;}
  if(d.status!=='ok'){alert(d.message||'error');return null;}
  return d;
}
function closeSpeakerModal(){document.getElementById('speakerModal').classList.remove('open');}
function speakerMapping(){
  const g={},p={},c={},a={},m={};
  for(const i of document.querySelectorAll('#spkRows input[data-group-for]'))g[i.dataset.groupFor]=i;
  for(const i of document.querySelectorAll('#spkRows input[data-person-for]'))p[i.dataset.personFor]=i;
  for(const i of document.querySelectorAll('#spkRows input[data-confirm-for]'))c[i.dataset.confirmFor]=i;
  for(const i of document.querySelectorAll('#spkRows input[data-accept-for]'))a[i.dataset.acceptFor]=i;
  for(const i of document.querySelectorAll('#spkRows input[data-label]')){
    const label=i.dataset.label,named=i.dataset.named==='1',tent=i.dataset.suggested||'';
    // 「alice?」は入力したか「alice として確定」にチェックしたときだけ送る（送ると声紋に足される）
    const name=i.value.trim()||(tent?(a[label]&&a[label].checked?tent:''):named?label:'');
    if(!name)continue;
    const gi=g[label],pi=p[label];
    const e={name};
    if(gi&&gi.dataset.touched==='1'&&!(pi&&pi.checked))e.group=gi.value.trim();
    if(pi&&pi.dataset.touched==='1')e.person=!!pi.checked;
    if(name===label&&c[label]&&c[label].checked)e.confirm=true;
    if(name!==label||Object.keys(e).length>1)m[label]=e;
  }
  return m;
}
async function saveSpeakers(){
  const mapping=speakerMapping();
  if(!Object.keys(mapping).length)return;
  const d=await _postJSON('/api/speakers/assign',{file:_spkFile,mapping});
  if(!d)return;
  closeSpeakerModal();showToast(d.message);loadT(_spkFile);loadR(_spkFile);await loadSpeakerGroups();
  if(d.has_summary)await regenSummaryFor(_spkFile);
}
async function loadVoiceprints(openName){
  const box=document.getElementById('vpRows');box.innerHTML='';
  let d,gd=null;
  try{d=await(await fetch('/api/voiceprints')).json();}catch(e){box.textContent=String(e);return;}
  if(d.status!=='ok'){box.textContent=d.message||'';return;}
  try{gd=await(await fetch('/api/speaker-groups')).json();}catch(e){}
  const book=gd&&gd.status==='ok'?gd:null,counts={};
  for(const p of d.people)counts[p.name]=p.count;
  if(book){
    for(const n of Object.keys(book.persons))if(book.persons[n]===true&&!(n in counts))counts[n]=0;
    _fillOptions('grpSuggest',Object.keys(book.groups||{}));
  }
  const names=Object.keys(counts).sort();
  if(!names.length){box.textContent=I18N['dash.voiceprints_empty'];return;}
  for(const n of names){
    const row=document.createElement('div');row.className='spk-row vp-person';
    const label=document.createElement('span');label.textContent=n+' ('+counts[n]+')';
    row.appendChild(label);
    if(book){
      const grp=document.createElement('input');grp.type='text';grp.className='spk-group';
      grp.setAttribute('list','grpSuggest');
      grp.value=book.names[n]||'';grp.placeholder=I18N['dash.group_label'];
      grp.onchange=()=>setPersonGroup(n,grp.value.trim());
      row.appendChild(grp);
    }
    const del=document.createElement('button');del.className='dan';del.textContent=I18N['dash.delete'];
    del.onclick=()=>deleteVoiceprint(n);
    const clusters=document.createElement('div');clusters.className='vp-clusters';
    row.appendChild(del);row.appendChild(vpShowButton(n,clusters));row.appendChild(clusters);box.appendChild(row);
    if(n===openName)await toggleVoiceprintClusters(n,clusters);
  }
}
async function deleteVoiceprint(name){
  if(!confirm(I18N['dash.voiceprint_delete_confirm'].replace('{name}',name)))return;
  if(await _postJSON('/api/voiceprints/delete',{name}))await loadVoiceprints();
}
async function setPersonGroup(name,group){
  if(await _postJSON('/api/speaker-groups/set',{name,group}))await loadSpeakerGroups();
}
let _rlFile='',_rlItems=[];
async function openRelabelModal(){
  _rlFile=curFile||activeFile;
  _rlItems=getSelectedLines().map(l=>(l.dataset.raw||'').match(/^\[([^\]]+)\]\s\[([^\]]+)\]/))
    .filter(m=>m&&m[2]!=='自分'&&m[2]!=='Claude').map(m=>({ts:m[1],label:m[2]}));
  const info=document.getElementById('rlInfo');
  info.textContent=I18N['dash.relabel_count'].replace('{count}',_rlItems.length);
  document.getElementById('rlName').value='';document.getElementById('rlGroup').value='';
  document.getElementById('rlPerson').checked=true;document.getElementById('rlGroup').hidden=true;
  document.getElementById('rlGroup').dataset.touched='';document.getElementById('rlPerson').dataset.touched='';
  let d=null;
  try{d=await(await fetch('/api/speakers?file='+encodeURIComponent(_rlFile))).json();}catch(e){}
  if(d&&d.status==='ok'){
    _fillOptions('rlSuggest',d.suggestions);_fillOptions('grpSuggest',d.groups||[]);
    if(d.active)info.textContent=I18N['dash.speakers_active'];
    else if(d.translating)info.textContent=I18N['dash.speakers_translating'];
  }
  document.getElementById('rlSaveBtn').disabled=!_rlItems.length||!!(d&&(d.active||d.translating));
  document.getElementById('relabelModal').classList.add('open');
}
function closeRelabelModal(){document.getElementById('relabelModal').classList.remove('open');}
async function saveRelabel(){
  const name=document.getElementById('rlName').value.trim();
  if(!name||!_rlItems.length)return;
  const body={file:_rlFile,lines:_rlItems,name},gi=document.getElementById('rlGroup'),pi=document.getElementById('rlPerson');
  if(gi.dataset.touched==='1'&&!pi.checked)body.group=gi.value.trim();
  if(pi.dataset.touched==='1')body.person=!!pi.checked;
  const d=await _postJSON('/api/speakers/assign-lines',body);
  if(!d)return;
  closeRelabelModal();deselectAll();showToast(d.message);loadT(_rlFile);loadR(_rlFile);await loadSpeakerGroups();
  if(d.has_summary)await regenSummaryFor(_rlFile);
}
loadSpeakerGroups();
"""
