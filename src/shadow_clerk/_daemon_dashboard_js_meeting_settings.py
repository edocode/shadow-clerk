"""Shadow-clerk daemon: ダッシュボード JavaScript（会議ごとの設定）"""
from __future__ import annotations

_JS_TEMPLATE_MEETING_SETTINGS = r"""
/* --- 会議ごとの設定。左で会議を選び、右のパネルでまとめて（1 件なら現在値から）変える --- */
let _msRows=[],_msSel=new Set();
async function openMeetingSettings(){
  _msSel=new Set();document.getElementById('msFilter').value='';
  await _msLoad();
  document.getElementById('msModal').classList.add('open');
  msRender();msFillEdit();
}
async function _msLoad(){
  // 名前なしの会議は ad-hoc にまとめられている。会議名で照合する設定は持てない
  const names=Object.keys(meetingGroups||{}).filter(n=>n!=='ad-hoc').sort((a,b)=>a.localeCompare(b));
  let d={meetings:[],path:''};
  try{d=await(await fetch('/api/meeting-settings?'+names.map(n=>'meeting='+encodeURIComponent(n)).join('&'))).json();}catch(e){}
  _msRows=(d.meetings||[]).map(m=>({...m,count:(meetingGroups[m.name]||[]).length}));
  document.getElementById('msPath').textContent=(I18N['ms.config_file']||'{path}').replace('{path}',d.path||'-');
}
function closeMeetingSettings(){document.getElementById('msModal').classList.remove('open');}
function _msVisible(){
  const q=document.getElementById('msFilter').value.trim().toLowerCase();
  return _msRows.filter(m=>!q||m.name.toLowerCase().includes(q));
}
function msRender(){
  const tb=document.getElementById('msBody');tb.innerHTML='';
  const vis=_msVisible();
  vis.forEach(m=>{
    const tr=document.createElement('tr');if(_msSel.has(m.name))tr.className='sel';
    const sub=m.matched==='(defaults)'?I18N['ms.uses_defaults']
      :m.shared?(I18N['ms.shared_rule']||'{rule}').replace('{rule}',m.matched):'';
    const dest=(m.publish_to==='notion'?'Notion':'Artifact')+(m.publish_advice?' + Advice':'');
    tr.innerHTML=`<td><input type="checkbox" ${_msSel.has(m.name)?'checked':''}></td>`
      +`<td>${esc(m.name)} <span style="color:var(--muted);font-size:11px">(${m.count})</span>${sub?`<small>${esc(sub)}</small>`:''}</td>`
      +`<td><span class="ms-badge${m.publish?' on':''}">${esc(I18N[m.publish?'ms.publish_on':'ms.publish_off'])}</span></td>`
      +`<td>${dest}${m.publish_to==='notion'&&m.notion_url?` <a href="${escAttr(m.notion_url)}" target="_blank" rel="noopener">↗</a>`:''}</td>`
      +`<td><button class="ms-gear" title="${escAttr(I18N['ms.edit_one'])}">⚙</button></td>`;
    tr.querySelector('input').onchange=e=>{e.target.checked?_msSel.add(m.name):_msSel.delete(m.name);msRender();msFillEdit();};
    tr.querySelector('.ms-gear').onclick=()=>{_msSel=new Set([m.name]);msRender();msFillEdit();};
    tb.appendChild(tr);
  });
  document.getElementById('msAll').checked=vis.length>0&&vis.every(m=>_msSel.has(m.name));
}
function msToggleAll(on){_msVisible().forEach(m=>on?_msSel.add(m.name):_msSel.delete(m.name));msRender();msFillEdit();}
function _msOne(){return _msSel.size===1?_msRows.find(m=>_msSel.has(m.name)):null;}
// 1 件なら現在値を入れ、全項目をそのまま書く。複数なら「変更しない」から始め、触った項目だけ書く
function msFillEdit(){
  const one=_msOne(),n=_msSel.size,$=id=>document.getElementById(id);
  $('msTitle').textContent=one?(I18N['ms.title_one']||'{name}').replace('{name}',one.name)
    :n?(I18N['ms.title_many']||'{n}').replace('{n}',n):I18N['ms.pick'];
  $('msChips').innerHTML=n>1?[..._msSel].map(x=>`<span>${esc(x)}</span>`).join(''):'';
  $('msPublish').value=one?(one.publish?'1':'0'):'';
  $('msWorkdir').value=one?one.workdir:'';
  $('msWorkdirHint').style.display=one?'none':'';
  $('msDest').value=one?one.publish_to:'';
  $('msNotionUrl').value=one?one.notion_url:'';
  $('msAdvice').value=one?(one.publish_advice?'1':'0'):'';
  $('msErr').textContent='';
  $('msApply').disabled=!n;
  msDestChanged();
}
function msDestChanged(){
  document.getElementById('msNotionUrl').style.display=document.getElementById('msDest').value==='notion'?'':'none';
}
async function msApply(){
  const $=id=>document.getElementById(id),one=_msOne(),set={};
  const pub=$('msPublish').value,wd=$('msWorkdir').value.trim(),dest=$('msDest').value,url=$('msNotionUrl').value.trim();
  if(pub)set.publish=pub==='1';
  if($('msAdvice').value)set.publish_advice=$('msAdvice').value==='1';
  if(one||wd)set.workdir=wd;
  if(dest){set.publish_to=dest;if(dest==='notion')set.notion_url=url;}
  if(dest==='notion'&&!/^https:\/\//.test(url)){$('msErr').textContent=I18N['ms.notion_url_required'];return;}
  if(!Object.keys(set).length){$('msErr').textContent=I18N['ms.nothing'];return;}
  let r={status:'error'};
  try{r=await(await fetch('/api/meeting-settings',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({meetings:[..._msSel],set})})).json();}catch(e){r={status:'error',message:String(e)};}
  if(r.status!=='ok'){$('msErr').textContent=r.message||'error';return;}
  await _msLoad();
  msRender();msFillEdit();
  const s=$('msSaved');s.style.display='inline';setTimeout(()=>{s.style.display='none';},1500);
}
"""
