"""Shadow-clerk daemon: ダッシュボード JavaScript (話者の名前付けと声紋)

core の esc / escAttr / curFile / activeFile / loadT / loadR と、modals の showToast に
依存するため、連結順は core・modals の後でなければならない。
"""

_JS_TEMPLATE_SPEAKERS = r"""
let _spkFile='';
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
  const dl=document.getElementById('spkSuggest');dl.innerHTML='';
  for(const s of d.suggestions){const o=document.createElement('option');o.value=s;dl.appendChild(o);}
  info.textContent=!d.labels.length?I18N['dash.speakers_none']:d.active?I18N['dash.speakers_active']
    :d.translating?I18N['dash.speakers_translating']
    :!d.enrollment?I18N['dash.speakers_enrollment_off']:'';
  for(const l of d.labels){
    const row=document.createElement('div');row.className='spk-row';
    row.innerHTML='<span class="spk-label">'+esc(l.label)+'</span>'
      +'<span class="spk-meta">'+esc(I18N['dash.speakers_count'].replace('{count}',l.count))
      +(d.enrollment?' / '+esc(I18N['dash.speakers_samples'].replace('{count}',l.samples)):'')+'</span>'
      +'<input type="text" list="spkSuggest" data-label="'+escAttr(l.label)+'">'
      +'<span class="spk-example">'+esc(l.example)+'</span>';
    box.appendChild(row);
  }
  document.getElementById('spkSaveBtn').disabled=!d.labels.length||!!(d.active||d.translating);
  await loadVoiceprints();
  document.getElementById('speakerModal').classList.add('open');
}
function closeSpeakerModal(){document.getElementById('speakerModal').classList.remove('open');}
function speakerMapping(){
  const m={};
  for(const i of document.querySelectorAll('#spkRows input[data-label]')){
    const v=i.value.trim();if(v)m[i.dataset.label]=v;
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
  closeSpeakerModal();showToast(d.message);loadT(_spkFile);loadR(_spkFile);
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
    row.appendChild(name);row.appendChild(del);box.appendChild(row);
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
"""
