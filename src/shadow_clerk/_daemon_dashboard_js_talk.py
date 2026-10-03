"""Shadow-clerk daemon: ダッシュボード JavaScript（Claude talk mode）"""

_JS_TEMPLATE_TALK = r"""
/* --- Claude talk mode --- */
let talkActive=false;
function updateTalk(s){
  talkActive=!!s.active;
  const b=document.getElementById('btnTalk');
  if(b){b.textContent=I18N[talkActive?'dash.talk_stop':'dash.talk_start'];b.classList.toggle('dan',talkActive);}
  const info=document.getElementById('talkInfo');if(!info)return;
  const parts=talkActive?[s.topic,s.persona,s.language,s.credit].filter(x=>x):[];
  if(talkActive&&s.route&&s.route.app)parts.push('→ '+s.route.app+'（'+I18N[s.route.connected?'dash.talk_route_connected':'dash.talk_route_disconnected']+'）');
  if(s.error)parts.push('⚠ '+s.error);
  info.textContent=parts.join(' / ');
}
async function talkPost(body){
  try{const r=await(await fetch('/api/talk-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
    if(r.talk)updateTalk(r.talk);return r;}
  catch(e){return {status:'error',message:String(e)};}
}
async function fillPersonaSel(){
  let ps={},def='';
  try{const c=await(await fetch('/api/config')).json();ps=c.talk_personas||{};def=c.talk_default_persona||'';document.getElementById('talkWorkdir').value=c.talk_workdir||c.ai_assistant_workdir||'';}catch(e){}
  const sel=document.getElementById('talkPersonaSel');sel.innerHTML='';
  const none=document.createElement('option');none.value='';none.textContent=I18N['dash.talk_persona_none'];sel.appendChild(none);
  Object.keys(ps).forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n;sel.appendChild(o);});
  sel.value=(def in ps)?def:'';
}
async function fillRouteSel(){
  const sel=document.getElementById('talkRoute'),note=document.getElementById('talkRouteNote');
  if(!sel)return;
  let r={available:false,targets:[]},want='';
  try{r=await(await fetch('/api/talk-route-targets')).json();}catch(e){}
  try{want=(await(await fetch('/api/config')).json()).talk_route_app||'';}catch(e){}
  sel.innerHTML='';
  const none=document.createElement('option');none.value='';none.textContent=I18N['dash.talk_route_none'];sel.appendChild(none);
  (r.targets||[]).forEach(t=>{const o=document.createElement('option');o.value=t.app;o.textContent=t.label;sel.appendChild(o);});
  if(!r.available)want='';
  if(want&&!(r.targets||[]).some(t=>t.app===want)){const o=document.createElement('option');o.value=want;o.textContent=want;sel.appendChild(o);}
  sel.value=want;sel.disabled=!r.available;
  note.textContent=r.available?'':I18N['dash.talk_route_unavailable'];
}
async function togTalk(){
  if(talkActive){await talkPost({on:false});return;}
  await fillPersonaSel();
  await fillRouteSel();
  document.getElementById('talkTopic').value='';
  document.getElementById('talkErr').textContent='';
  document.getElementById('talkModal').classList.add('open');
}
function closeTalk(){document.getElementById('talkModal').classList.remove('open');}
async function startTalk(){
  const rs=document.getElementById('talkRoute');
  const r=await talkPost({on:true,topic:document.getElementById('talkTopic').value.trim(),
                          persona:document.getElementById('talkPersonaSel').value,
                          workdir:document.getElementById('talkWorkdir').value.trim()||null,
                          route:(rs&&!rs.disabled&&rs.value)||null});
  if(r.status==='ok'){
    const route=rs.value||'';
    if(rs&&!rs.disabled)try{const cfg=await(await fetch('/api/config')).json();
      if((cfg.talk_route_app||'')!==route){cfg.talk_route_app=route;
        await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});}}catch(e){}
    closeTalk();if(r.talk&&r.talk.engine==='console')selectConsoleRole('talk');}else document.getElementById('talkErr').textContent=r.message||'';
}
function personaAddRow(name,text,isDefault){
  const tr=document.createElement('tr');
  const n=document.createElement('input');n.type='text';n.value=name||'';
  const ta=document.createElement('textarea');ta.rows=3;ta.value=text||'';
  const rd=document.createElement('input');rd.type='radio';rd.name='personaDef';rd.checked=!!isDefault;
  const del=document.createElement('td');del.className='gl-del';del.textContent='×';del.onclick=()=>tr.remove();
  [n,ta,rd].forEach((el,i)=>{const td=document.createElement('td');if(i===2)td.className='pd';td.appendChild(el);tr.appendChild(td);});
  tr.appendChild(del);document.getElementById('personaBody').appendChild(tr);
}
async function openPersonas(){
  let ps={},def='';
  try{const c=await(await fetch('/api/config')).json();ps=c.talk_personas||{};def=c.talk_default_persona||'';}catch(e){}
  document.getElementById('personaBody').innerHTML='';
  Object.entries(ps).forEach(([n,tx])=>personaAddRow(n,tx,n===def));
  if(!Object.keys(ps).length)personaAddRow();
  document.getElementById('personaSaved').style.display='none';
  document.getElementById('personaModal').classList.add('open');
}
function closePersonas(){document.getElementById('personaModal').classList.remove('open');}
async function savePersonas(){
  const ps={};let def='';
  document.querySelectorAll('#personaBody tr').forEach(tr=>{
    const n=tr.querySelector('input[type=text]').value.trim(),tx=tr.querySelector('textarea').value.trim();
    if(!n||!tx)return;ps[n]=tx;if(tr.querySelector('input[type=radio]').checked)def=n;
  });
  try{
    const cfg=await(await fetch('/api/config')).json();
    cfg.talk_personas=ps;cfg.talk_default_persona=def;
    await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
    const s=document.getElementById('personaSaved');s.style.display='inline';setTimeout(()=>s.style.display='none',2000);
    if(document.getElementById('talkModal').classList.contains('open'))await fillPersonaSel();
  }catch(e){}
}
const VOICE_KEYS=['speed','pitch','intonation','volume'];
let _voiceCfgSpeaker=3;
function voiceShow(k){document.getElementById('voice_'+k+'_v').textContent=Number(document.getElementById('voice_'+k).value).toFixed(2);}
function voiceValues(){
  const sid=parseInt(document.getElementById('voiceSpeaker').value,10);
  const v={speaker_id:Number.isNaN(sid)?_voiceCfgSpeaker:sid};
  VOICE_KEYS.forEach(k=>v[k]=parseFloat(document.getElementById('voice_'+k).value));
  return v;
}
async function openVoice(){
  const err=document.getElementById('voiceErr');err.textContent='';
  let cfg={};try{cfg=await(await fetch('/api/config')).json();}catch(e){}
  _voiceCfgSpeaker=cfg.talk_speaker_id??3;
  const sel=document.getElementById('voiceSpeaker');sel.innerHTML='';
  try{const r=await(await fetch('/api/talk-voices')).json();
    if(r.status!=='ok')err.textContent=r.message||'';
    (r.voices||[]).forEach(v=>{const o=document.createElement('option');o.value=v.id;o.textContent=v.name;sel.appendChild(o);});
  }catch(e){err.textContent=String(e);}
  sel.value=String(_voiceCfgSpeaker);
  VOICE_KEYS.forEach(k=>{const el=document.getElementById('voice_'+k);el.value=cfg['talk_'+k]??el.defaultValue;voiceShow(k);});
  document.getElementById('voiceSaved').style.display='none';
  document.getElementById('voiceModal').classList.add('open');
}
function closeVoice(){document.getElementById('voiceModal').classList.remove('open');}
async function previewVoice(){
  const err=document.getElementById('voiceErr');err.textContent='';
  try{const r=await(await fetch('/api/talk-preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voice:voiceValues()})})).json();
    if(r.status!=='ok')err.textContent=r.message||'';}
  catch(e){err.textContent=String(e);}
}
async function saveVoice(){
  const v=voiceValues();
  try{
    const cfg=await(await fetch('/api/config')).json();
    cfg.talk_speaker_id=v.speaker_id;VOICE_KEYS.forEach(k=>cfg['talk_'+k]=v[k]);
    await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
    const s=document.getElementById('voiceSaved');s.style.display='inline';setTimeout(()=>s.style.display='none',2000);
  }catch(e){document.getElementById('voiceErr').textContent=String(e);}
}
"""
