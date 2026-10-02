"""Shadow-clerk daemon: ダッシュボード JavaScript（Claude talk mode）"""

_JS_TEMPLATE_TALK = r"""
/* --- Claude talk mode --- */
let talkActive=false;
function updateTalk(s){
  talkActive=!!s.active;
  const b=document.getElementById('btnTalk');
  if(b){b.textContent=I18N[talkActive?'dash.talk_stop':'dash.talk_start'];b.classList.toggle('pri',talkActive);}
  const info=document.getElementById('talkInfo');if(!info)return;
  const parts=talkActive?[s.topic,s.persona,s.language,s.credit].filter(x=>x):[];
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
  try{const c=await(await fetch('/api/config')).json();ps=c.talk_personas||{};def=c.talk_default_persona||'';}catch(e){}
  const sel=document.getElementById('talkPersonaSel');sel.innerHTML='';
  const none=document.createElement('option');none.value='';none.textContent=I18N['dash.talk_persona_none'];sel.appendChild(none);
  Object.keys(ps).forEach(n=>{const o=document.createElement('option');o.value=n;o.textContent=n;sel.appendChild(o);});
  sel.value=(def in ps)?def:'';
}
async function togTalk(){
  if(talkActive){await talkPost({on:false});return;}
  await fillPersonaSel();
  document.getElementById('talkTopic').value='';
  document.getElementById('talkErr').textContent='';
  document.getElementById('talkModal').classList.add('open');
}
function closeTalk(){document.getElementById('talkModal').classList.remove('open');}
async function startTalk(){
  const r=await talkPost({on:true,topic:document.getElementById('talkTopic').value.trim(),
                          persona:document.getElementById('talkPersonaSel').value});
  if(r.status==='ok')closeTalk();else document.getElementById('talkErr').textContent=r.message||'';
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
"""
