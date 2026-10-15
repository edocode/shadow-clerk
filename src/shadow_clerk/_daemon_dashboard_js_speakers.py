"""Shadow-clerk daemon: ダッシュボード JavaScript (話者の名前付けと声紋)

core の esc / escAttr / curFile / activeFile / loadT / loadR と、modals の showToast に
依存するため、連結順は core・modals の後でなければならない。
"""

_JS_TEMPLATE_SPEAKERS = r"""
let _spkFile='';
function spColor(sp,mic){
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
  box.innerHTML='';info.textContent='';
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
      +(d.enrollment?' / '+esc(I18N['dash.speakers_samples'].replace('{count}',l.samples)):'')+'</span>'
      +'<input type="text" list="spkSuggest" oninput="onSpkNameInput(this)" data-label="'+escAttr(l.label)+'"'
      +' data-named="'+(l.named?'1':'0')+'"'+(l.named?' placeholder="'+escAttr(l.label)+'"':'')+'>'
      +'<input type="text" class="spk-group" list="grpSuggest" data-group-for="'+escAttr(l.label)+'"'
      +' oninput="this.dataset.touched=\'1\'" data-orig="'+escAttr(l.group||'')+'" value="'+escAttr(l.group||'')+'" placeholder="'+escAttr(I18N['dash.group_label'])+'">'
      +'<label class="spk-person"><input type="checkbox" onchange="this.dataset.touched=\'1\'" data-person-for="'+escAttr(l.label)+'"'
      +' data-orig="'+(l.person===false?'0':'1')+'"'+(l.person===false?'':' checked')+'>'+esc(I18N['dash.person_enroll'])+'</label>'
      +'<span class="spk-example">'+esc(l.example)+'</span>';
    box.appendChild(row);
  }
  document.getElementById('spkSaveBtn').disabled=!d.labels.length||!!(d.active||d.translating);
  await loadVoiceprints();
  document.getElementById('speakerModal').classList.add('open');
}
function closeSpeakerModal(){document.getElementById('speakerModal').classList.remove('open');}
function speakerMapping(){
  const g={},p={},m={};
  for(const i of document.querySelectorAll('#spkRows input[data-group-for]'))g[i.dataset.groupFor]=i;
  for(const i of document.querySelectorAll('#spkRows input[data-person-for]'))p[i.dataset.personFor]=i;
  for(const i of document.querySelectorAll('#spkRows input[data-label]')){
    const label=i.dataset.label,named=i.dataset.named==='1';
    const name=i.value.trim()||(named?label:'');
    if(!name)continue;
    const gi=g[label],pi=p[label];
    const e={name};
    if(gi&&gi.dataset.touched==='1')e.group=gi.value.trim();
    if(pi&&pi.dataset.touched==='1')e.person=!!pi.checked;
    if(name!==label||Object.keys(e).length>1)m[label]=e;
  }
  return m;
}
async function saveSpeakers(){
  const mapping=speakerMapping();
  if(!Object.keys(mapping).length)return;
  let d;
  try{d=await(await fetch('/api/speakers/assign',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({file:_spkFile,mapping})})).json();}catch(e){alert(String(e));return;}
  if(d.status!=='ok'){alert(d.message||'error');return;}
  closeSpeakerModal();showToast(d.message);loadT(_spkFile);loadR(_spkFile);await loadSpeakerGroups();
  if(d.has_summary)await regenSummaryFor(_spkFile);
}
async function loadVoiceprints(){
  const box=document.getElementById('vpRows');box.innerHTML='';
  let d;
  try{d=await(await fetch('/api/voiceprints')).json();}catch(e){box.textContent=String(e);return;}
  if(d.status!=='ok'){box.textContent=d.message||'';return;}
  if(!d.people.length){box.textContent=I18N['dash.voiceprints_empty'];return;}
  for(const p of d.people){
    const row=document.createElement('div');row.className='spk-row';
    const name=document.createElement('span');name.textContent=p.name+' ('+p.count+')';
    const del=document.createElement('button');del.className='dan';del.textContent=I18N['dash.delete'];
    del.onclick=()=>deleteVoiceprint(p.name);
    const grp=document.createElement('input');grp.type='text';grp.className='spk-group';
    grp.setAttribute('list','grpSuggest');
    grp.value=spkGroups.names[p.name]||'';grp.placeholder=I18N['dash.group_label'];
    grp.onchange=()=>setPersonGroup(p.name,grp.value.trim());
    row.appendChild(name);row.appendChild(grp);row.appendChild(del);box.appendChild(row);
  }
}
async function deleteVoiceprint(name){
  if(!confirm(I18N['dash.voiceprint_delete_confirm'].replace('{name}',name)))return;
  let d;
  try{d=await(await fetch('/api/voiceprints/delete',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name})})).json();}catch(e){alert(String(e));return;}
  if(d.status!=='ok'){alert(d.message||'error');return;}
  await loadVoiceprints();
}
async function setPersonGroup(name,group){
  let d;
  try{d=await(await fetch('/api/speaker-groups/set',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,group})})).json();}catch(e){alert(String(e));return;}
  if(d.status!=='ok'){alert(d.message||'error');return;}
  await loadSpeakerGroups();
}
let _rlFile='',_rlItems=[];
async function openRelabelModal(){
  _rlFile=curFile||activeFile;
  _rlItems=getSelectedLines().map(l=>(l.dataset.raw||'').match(/^\[([^\]]+)\]\s\[([^\]]+)\]/))
    .filter(m=>m&&m[2]!=='自分'&&m[2]!=='Claude').map(m=>({ts:m[1],label:m[2]}));
  const info=document.getElementById('rlInfo');
  info.textContent=I18N['dash.relabel_count'].replace('{count}',_rlItems.length);
  document.getElementById('rlName').value='';document.getElementById('rlGroup').value='';
  document.getElementById('rlPerson').checked=true;
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
  if(gi.dataset.touched==='1')body.group=gi.value.trim();
  if(pi.dataset.touched==='1')body.person=!!pi.checked;
  let d;
  try{d=await(await fetch('/api/speakers/assign-lines',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)})).json();}catch(e){alert(String(e));return;}
  if(d.status!=='ok'){alert(d.message||'error');return;}
  closeRelabelModal();deselectAll();showToast(d.message);loadT(_rlFile);loadR(_rlFile);await loadSpeakerGroups();
  if(d.has_summary)await regenSummaryFor(_rlFile);
}
loadSpeakerGroups();
"""
