"""Shadow-clerk daemon: ダッシュボード JavaScript (part A)"""

_JS_TEMPLATE_CORE = """\
/*I18N_JSON*/
/* --- TranscriptName 構築ヘルパー（regex なし・fileInfo を使用） --- */
const TN={
  filename(dt,name){return 'transcript-'+dt+(name?'@'+name:'')+'.txt';},
  summaryFilename(dt,name){return 'summary-'+dt+(name?'@'+name:'')+'.md';},
};
let fileInfo={}; // /api/files の file_info をキャッシュ
let curFile='', activeFile='';
let leftTab='dates'; // 左ペインのアクティブタブ
let meetingActive=false, translating=false, muteMic=false, muteMonitor=false, pttActive=false;
let audioBackend='';
let panelMode=0; // 0=T|R, 1=T, 2=R
let meetingGroups={}, curGroup=null; // 会議グループ管理
const as={tp:true,rp:true,logc:true};
['tp','rp','logc'].forEach(id=>{
  document.getElementById(id).addEventListener('scroll',function(){
    as[id]=this.scrollTop+this.clientHeight>=this.scrollHeight-30;
  });
});
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function escAttr(s){return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmtLine(t){
  if(/^---\\s.*\\s---$/.test(t)) return '<div class="ln"><span class="mk">'+esc(t)+'</span></div>';
  const m=t.match(/^\\[(\\d{4}-\\d{2}-\\d{2}\\s\\d{2}:\\d{2}:\\d{2})\\]\\s\\[([^\\]]+)\\]\\s(.*)$/);
  if(m){const sp=m[2],mic=I18N['speaker.mic']||'自分';const c=(sp===mic||sp==='自分')?'sp-s':'sp-o';
    const dl=sp===mic?mic:sp==='自分'?mic:(sp===(I18N['speaker.monitor']||'相手')||sp==='相手')?(I18N['speaker.monitor']||'相手'):sp;
    return '<div class="ln" data-ts="'+escAttr(m[1])+'" data-raw="'+escAttr(t)+'"><span class="ln-text"><span class="ts">['+esc(m[1])+']</span> <span class="'+c+'">['+esc(dl)+']</span> '+esc(m[3])+'</span></div>';}
  return '<div class="ln" data-raw="'+escAttr(t)+'"><span class="ln-text">'+esc(t)+'</span></div>';
}
function fmtTranscriptLine(t){
  if(/^---\\s.*\\s---$/.test(t)) return '<div class="ln"><span class="mk">'+esc(t)+'</span></div>';
  const m=t.match(/^\\[(\\d{4}-\\d{2}-\\d{2}\\s\\d{2}:\\d{2}:\\d{2})\\]\\s\\[([^\\]]+)\\]\\s(.*)$/);
  if(m){const sp=m[2],mic=I18N['speaker.mic']||'自分';const c=(sp===mic||sp==='自分')?'sp-s':'sp-o';
    const dl=sp===mic?mic:sp==='自分'?mic:(sp===(I18N['speaker.monitor']||'相手')||sp==='相手')?(I18N['speaker.monitor']||'相手'):sp;
    return '<div class="ln" data-ts="'+escAttr(m[1])+'" data-raw="'+escAttr(t)+'"><input type="checkbox" class="ln-cb" onchange="onSelChange()"><span class="ln-text"><span class="ts">['+esc(m[1])+']</span> <span class="'+c+'">['+esc(dl)+']</span> '+esc(m[3])+'</span></div>';}
  return '<div class="ln" data-raw="'+escAttr(t)+'"><span class="ln-text">'+esc(t)+'</span></div>';
}
function addLines(id,text,fmt){
  const el=document.getElementById(id);
  text.split('\\n').forEach(l=>{if(l.trim())el.insertAdjacentHTML('beforeend',fmt(l));});
  if(as[id])el.scrollTop=el.scrollHeight;
}
/* --- Selection management --- */
function getSelectedLines(){return Array.from(document.querySelectorAll('#tp .ln-cb:checked')).map(cb=>cb.closest('.ln'));}
function onSelChange(){
  const sel=getSelectedLines();const n=sel.length;
  const bar=document.getElementById('selActions');
  const cnt=document.getElementById('selCount');
  const btnExt=document.getElementById('btnExtract');
  if(n>0){
    bar.classList.add('show');
    cnt.textContent=(I18N['dash.selected_count']||'{count} selected').replace('{count}',n);
    btnExt.style.display=(n===2)?'':'none';
  }else{bar.classList.remove('show');btnExt.style.display='none';}
}
function deselectAll(){
  document.querySelectorAll('#tp .ln-cb:checked').forEach(cb=>{cb.checked=false;});
  onSelChange();
}
/* --- Bulk delete modal --- */
function openBulkDelModal(){
  const sel=getSelectedLines();if(!sel.length)return;
  const tDiv=document.getElementById('bulkDelTranscript');
  const rDiv=document.getElementById('bulkDelTranslation');
  tDiv.innerHTML='';rDiv.innerHTML='';
  sel.forEach(ln=>{
    const d=document.createElement('div');d.textContent=ln.dataset.raw||ln.textContent;tDiv.appendChild(d);
    const ts=ln.dataset.ts||'';
    if(ts){
      const rp=document.getElementById('rp');
      const els=rp.querySelectorAll('.ln[data-ts]');
      for(const el of els){if(el.dataset.ts===ts){const rd=document.createElement('div');rd.textContent=el.dataset.raw||el.textContent;rDiv.appendChild(rd);break;}}
    }
  });
  if(!rDiv.children.length){const d=document.createElement('div');d.textContent='—';rDiv.appendChild(d);}
  const rangeOpt=document.getElementById('bulkDelRangeOpt');
  if(sel.length===2){rangeOpt.style.display='';document.querySelector('input[name="bulkDelMode"][value="range"]').checked=true;}
  else{rangeOpt.style.display='none';}
  document.getElementById('bulkDelModal').classList.add('open');
}
function closeBulkDelModal(){document.getElementById('bulkDelModal').classList.remove('open');
  const r=document.querySelector('input[name="bulkDelMode"][value="range"]');if(r)r.checked=true;}
async function doBulkDel(){
  const sel=getSelectedLines();if(!sel.length)return;
  const mode=document.querySelector('input[name="bulkDelMode"]:checked');
  const isRange=mode&&mode.value==='range'&&sel.length===2;
  let targets=sel;
  if(isRange){
    const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
    const tsMin=ts0<ts1?ts0:ts1;const tsMax=ts0<ts1?ts1:ts0;
    const allLn=document.querySelectorAll('#tp .ln[data-ts]');
    targets=Array.from(allLn).filter(ln=>{const ts=ln.dataset.ts||'';return ts>=tsMin&&ts<=tsMax;});
  }
  const lines=targets.map(ln=>ln.dataset.raw||'').filter(Boolean);
  const file=document.getElementById('tf').textContent;
  try{
    const r=await fetch('/api/transcript/delete',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({lines:lines,file:file})});
    const d=await r.json();
    if(d.status==='ok'){
      targets.forEach(ln=>{
        const ts=ln.dataset.ts||'';
        if(ts){const rp=document.getElementById('rp');const els=rp.querySelectorAll('.ln[data-ts]');
          for(const el of els){if(el.dataset.ts===ts){el.remove();break;}}}
        ln.remove();
      });
      deselectAll();closeBulkDelModal();
    }else{alert(I18N['dash.delete_error']||'Failed to delete');}
  }catch(e){alert(I18N['dash.delete_error']||'Failed to delete');}
}
/* --- File delete modal --- */
function openFileDelModal(){
  if(!curFile)return;
  const fi=fileInfo[curFile];
  const stem=curFile.replace(/\\.txt$/,'');
  const files=[curFile];
  const sel=document.getElementById('fsel');
  for(const opt of sel.options){
    const v=opt.value;
    if(v!==curFile && v.startsWith(stem+'-') && v.endsWith('.txt'))files.push(v);
  }
  if(fi?.summary)files.push(fi.summary);
  files.push(curFile+'.translate_offset');
  const list=document.getElementById('fileDelList');
  list.innerHTML='';
  files.forEach(f=>{const d=document.createElement('div');d.textContent=f;list.appendChild(d);});
  document.getElementById('fileDelModal').classList.add('open');
}
function closeFileDelModal(){document.getElementById('fileDelModal').classList.remove('open');}
async function doFileDel(){
  if(!curFile)return;
  try{
    const r=await fetch('/api/transcript/delete-file',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({file:curFile})});
    const d=await r.json();
    if(d.status==='ok'){closeFileDelModal();loadFiles();}
    else{alert(I18N['dash.delete_error']||'Failed to delete');}
  }catch(e){alert(I18N['dash.delete_error']||'Failed to delete');}
}
/* --- Extract meeting modal --- */
function _dtPlusDays(dateStr,n){
  const d=new Date(dateStr.substring(0,4)+'-'+dateStr.substring(4,6)+'-'+dateStr.substring(6,8));
  d.setDate(d.getDate()+n);
  return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`;
}

function openExtractModal(){
  const sel=getSelectedLines();if(sel.length!==2)return;
  const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
  if(!ts0||!ts1)return;
  const startTs=ts0<ts1?ts0:ts1;const endTs=ts0<ts1?ts1:ts0;
  document.getElementById('extractRange').textContent=
    (I18N['dash.extract_meeting_range']||'Range: {start} - {end}').replace('{start}',startTs).replace('{end}',endTs);
  // タイムスタンプ範囲内の行数カウント
  const allLns=document.querySelectorAll('#tp .ln[data-ts]');
  let cnt=0;
  allLns.forEach(ln=>{const t=ln.dataset.ts;if(t>=startTs&&t<=endTs)cnt++;});
  document.getElementById('extractLineCount').textContent=
    (I18N['dash.extract_meeting_lines']||'{count} lines selected').replace('{count}',cnt);
  // 既存会議ファイル: 現在ファイルの日付 ±1日の範囲
  const curDt=(fileInfo[curFile]?.dt||'').substring(0,8);
  const near=curDt?new Set([curDt,_dtPlusDays(curDt,-1),_dtPlusDays(curDt,1)]):null;
  const eSel=document.getElementById('extractExistingSel');
  eSel.innerHTML='';
  Object.keys(fileInfo).sort().reverse().forEach(f=>{
    const fi=fileInfo[f];
    if(fi?.meeting_group==null)return;
    if(near&&!near.has((fi.dt||'').substring(0,8)))return;
    const opt=document.createElement('option');opt.value=f;opt.textContent=(fileInfo[f]?.label||f);eSel.appendChild(opt);
  });
  // 既存グループ名 select
  const gSel=document.getElementById('extractGroupSel');
  gSel.innerHTML='';
  Object.keys(meetingGroups).filter(g=>g!=='ad-hoc').sort().forEach(g=>{
    const opt=document.createElement('option');opt.value=g;opt.textContent=g;gSel.appendChild(opt);
  });
  // ラジオ初期化
  document.querySelector('input[name="extractTarget"][value="new"]').checked=true;
  document.querySelector('input[name="extractNewType"][value="adhoc"]').checked=true;
  _updateExtractControls();
  document.querySelectorAll('input[name="extractTarget"],input[name="extractNewType"]').forEach(r=>{
    r.onchange=_updateExtractControls;
  });
  document.getElementById('extractModal').classList.add('open');
}
function _updateExtractControls(){
  const targetVal=(document.querySelector('input[name="extractTarget"]:checked')||{}).value;
  const newTypeVal=(document.querySelector('input[name="extractNewType"]:checked')||{}).value;
  const isNew=targetVal==='new';
  document.getElementById('extractNewOpts').style.display=isNew?'':'none';
  document.getElementById('extractExistingSel').disabled=targetVal!=='existing';
  document.getElementById('extractGroupSel').disabled=!(isNew&&newTypeVal==='group');
  document.getElementById('extractNameInput').disabled=!(isNew&&newTypeVal==='newname');
}
function closeExtractModal(){document.getElementById('extractModal').classList.remove('open');}
async function doExtractMeeting(){
  const sel=getSelectedLines();if(sel.length!==2)return;
  const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
  const startTs=ts0<ts1?ts0:ts1;const endTs=ts0<ts1?ts1:ts0;
  const file=document.getElementById('tf').textContent;
  const targetVal=(document.querySelector('input[name="extractTarget"]:checked')||{}).value||'new';
  let target='new',name='';
  if(targetVal==='existing'){
    target=document.getElementById('extractExistingSel').value||'new';
  }else{
    const newTypeVal=(document.querySelector('input[name="extractNewType"]:checked')||{}).value||'adhoc';
    if(newTypeVal==='group') name=document.getElementById('extractGroupSel').value||'';
    else if(newTypeVal==='newname') name=document.getElementById('extractNameInput').value.trim()||'';
  }
  try{
    const r=await fetch('/api/transcript/extract-meeting',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({file:file,start_ts:startTs,end_ts:endTs,target:target,name:name})});
    const d=await r.json();
    if(d.status==='ok'){
      deselectAll();closeExtractModal();
      loadFiles();loadT(curFile);loadR(curFile);
      if(d.message)alert(d.message);
    }else{alert(d.message||I18N['dash.extract_meeting_error']||'Failed');}
  }catch(e){alert(I18N['dash.extract_meeting_error']||'Failed');}
}
/* --- Meeting toggle --- */
function updateMeetingBtn(session){
  meetingActive=!!session;
  const btn=document.getElementById('btnMeeting');
  if(meetingActive){
    btn.textContent='\\u25A0 '+I18N['dash.meeting_toggle_end'];
    btn.className='dan';
  }else{
    btn.textContent='\\u25B6 '+I18N['dash.meeting_toggle_start'];
    btn.className='pri';
  }
}
function togMeeting(){cmd(meetingActive?'end_meeting':'start_meeting');}
/* --- Translation toggle --- */
function updateTranslateBtn(active){
  translating=active;
  const btn=document.getElementById('btnTranslate');
  if(translating){
    btn.textContent='\\u25A0 '+I18N['dash.translate_stop'];
    btn.className='dan';
  }else{
    btn.textContent='\\u25B6 '+I18N['dash.translate_start'];
    btn.className='pri';
  }
}
function _curFileArg(){
  const fi=fileInfo[curFile];
  return fi?(fi.dt+(fi.name?'@'+fi.name:'')):'';
}
async function togTranslate(){
  if(translating){cmd('translate_stop');updateTranslateBtn(false);return;}
  const dateArg=curFile&&curFile!==activeFile?_curFileArg():'';
  cmd('translate_start'+(dateArg?' '+dateArg:''));updateTranslateBtn(true);
}
async function regenTranslate(){
  if(!confirm(I18N['dash.translate_regen_confirm']))return;
  const dateArg=_curFileArg();
  cmd('translate_regenerate'+(dateArg?' '+dateArg:''));
  updateTranslateBtn(true);
}

/* --- Mute toggles --- */
function updateMuteBtn(type,muted,available){
  const btn=document.getElementById(type==='mic'?'btnMuteMic':'btnMuteMonitor');
  if(available===false){btn.classList.remove('off');btn.classList.add('unavail');btn.title=I18N[type==='mic'?'dash.mic_unavailable':'dash.monitor_unavailable']||'Unavailable';return;}
  btn.classList.remove('unavail');
  if(muted){btn.classList.add('off');btn.title=I18N[type==='mic'?'dash.unmute_mic':'dash.unmute_monitor'];}
  else{btn.classList.remove('off');btn.title=I18N[type==='mic'?'dash.mute_mic':'dash.mute_monitor'];}
}
function togMute(type){
  const btn=document.getElementById(type==='mic'?'btnMuteMic':'btnMuteMonitor');
  if(btn.classList.contains('unavail')){showTroubleshoot(type);return;}
  if(type==='mic'){muteMic=!muteMic;cmd(muteMic?'mute_mic':'unmute_mic');updateMuteBtn('mic',muteMic);}
  else{muteMonitor=!muteMonitor;cmd(muteMonitor?'mute_monitor':'unmute_monitor');updateMuteBtn('monitor',muteMonitor);}
}
function showTroubleshoot(type){
  const title=I18N[type==='mic'?'dash.mic_unavailable':'dash.monitor_unavailable']||'Unavailable';
  const isMic=type==='mic';
  const T=k=>I18N[k]||k;
  let html='<b>'+T(isMic?'dash.ts_mic_title':'dash.ts_monitor_title')+'</b><br><br>';
  html+='<b>'+T('dash.ts_possible_causes')+'</b><ol>';
  html+='<li>'+T(isMic?'dash.ts_mic_cause1':'dash.ts_monitor_cause1')+'</li>';
  html+='<li>'+T('dash.ts_cause_service')+'</li>';
  html+='</ol>';
  html+='<b>'+T('dash.ts_fix_steps')+'</b><ol>';
  let restartCmd='';
  if(audioBackend==='pipewire'){restartCmd='systemctl --user restart pipewire pipewire-pulse';}
  else if(audioBackend==='pulseaudio'){restartCmd='systemctl --user restart pulseaudio';}
  if(restartCmd){html+='<li>'+T('dash.ts_restart_service')+'<br><code>'+restartCmd+'</code></li>';}
  html+='<li>'+T('dash.ts_list_devices')+'<br><code>clerk-daemon --list-devices</code></li>';
  const opt=isMic?'--mic':'--monitor';
  html+='<li>'+T('dash.ts_restart_clerk').replace('{opt}',opt)+'</li>';
  html+='</ol>';
  document.getElementById('tsTitle').textContent=title;
  document.getElementById('tsBody').innerHTML=html;
  document.getElementById('troubleshootModal').classList.add('open');
}
function closeTroubleshoot(){document.getElementById('troubleshootModal').classList.remove('open');}
/* --- PTT toggle --- */
function updatePTT(active){
  pttActive=active;
  const btn=document.getElementById('btnPTT');
  if(active){btn.style.background='var(--red)';btn.style.color='#fff';}
  else{btn.style.background='';btn.style.color='';}
}
function togPTT(){
  pttActive=!pttActive;
  cmd(pttActive?'ptt_on':'ptt_off');
  updatePTT(pttActive);
}
/* --- Panel cycling (T|R -> T -> R) --- */
function cyclePanel(){
  panelMode=(panelMode+1)%3;
  const t=document.getElementById('pnlT'),r=document.getElementById('pnlR'),btn=document.getElementById('togTR');
  if(panelMode===0){t.classList.remove('hidden');r.classList.remove('hidden');btn.textContent='T|R';}
  else if(panelMode===1){t.classList.remove('hidden');r.classList.add('hidden');btn.textContent='T';}
  else{t.classList.add('hidden');r.classList.remove('hidden');btn.textContent='R';}
}
/* --- Logs toggle --- */
function togLogs(){
  const lp=document.getElementById('logp'),arr=document.getElementById('logArrow');
  lp.classList.toggle('collapsed');
  arr.textContent=lp.classList.contains('collapsed')?'▲':'▼';
}
/* --- Status fetch --- */
async function fetchStatus(){
  try{const d=await(await fetch('/api/status')).json();
    const s=document.getElementById('langSel');if(s&&d.language)s.value=d.language;
    updateMeetingBtn(d.session);
    updateTranslateBtn(d.translating);
    muteMic=d.mute_mic;muteMonitor=d.mute_monitor;if(d.backend)audioBackend=d.backend;
    updateMuteBtn('mic',muteMic,d.use_mic);updateMuteBtn('monitor',muteMonitor,d.use_monitor);
    if(d.ptt!==undefined)updatePTT(d.ptt);
    const ai=document.getElementById('asrInfo');
    if(ai&&d.asr_backend){ai.textContent=d.asr_backend==='whisper'?'Whisper: '+d.asr_model_id:d.asr_backend;}
    if(d.gcal_enabled){const b=document.getElementById('btnGcal');if(b)b.style.display='';}
  }catch(e){}
}
const es=new EventSource('/api/events');
es.addEventListener('transcript',e=>{
  const d=JSON.parse(e.data);
  if(!curFile||curFile===d.file){addLines('tp',d.diff,fmtTranscriptLine);document.getElementById('tf').textContent=d.file;}
});
es.addEventListener('translation',e=>{
  const d=JSON.parse(e.data);addLines('rp',d.diff,fmtLine);document.getElementById('rf').textContent=d.file;
});
es.addEventListener('log',e=>{
  const d=JSON.parse(e.data);const el=document.getElementById('logc');
  const c=d.line.includes('ERROR')?'e':d.line.includes('WARNING')?'w':'';
  el.insertAdjacentHTML('beforeend','<div class="ll '+c+'">'+esc(d.line)+'</div>');
  if(as.logc)el.scrollTop=el.scrollHeight;
});
es.addEventListener('session',e=>{
  try{const d=JSON.parse(e.data);updateMeetingBtn(d.content||null);}catch(ex){}
  loadFiles();
});
es.addEventListener('ptt',e=>{
  try{const d=JSON.parse(e.data);updatePTT(d.active);}catch(ex){}
});
es.addEventListener('asr_status',e=>{
  try{const d=JSON.parse(e.data);const ai=document.getElementById('asrInfo');
  if(ai&&d.asr_backend){ai.textContent=d.asr_backend==='whisper'?'Whisper: '+d.asr_model_id:d.asr_backend;}}catch(ex){}
});
es.addEventListener('interim_transcript',e=>{
  const d=JSON.parse(e.data);
  const el=document.getElementById('interim-monitor');
  if(el){el.innerHTML='<span class="sp-o">['+esc(d.speaker)+']</span> '+esc(d.text);}
  document.getElementById('interim-area').style.display='block';
});
es.addEventListener('interim_translation',e=>{
  const d=JSON.parse(e.data);
  const el=document.getElementById('itp');
  if(el){el.innerHTML='<span class="sp-o">['+esc(d.speaker)+']</span> '+esc(d.translated);}
  document.getElementById('interim-area').style.display='block';
});
es.addEventListener('interim_clear',e=>{
  const el=document.getElementById('interim-monitor');
  if(el)el.innerHTML='';
  document.getElementById('interim-area').style.display='none';
  const itp=document.getElementById('itp');
  if(itp)itp.innerHTML='';
});
function _todayYestStr(){
  const nd=new Date();
  const fd=d=>`${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`;
  const yd=new Date(nd);yd.setDate(yd.getDate()-1);
  return [fd(nd),fd(yd)];
}
async function loadFiles(){
  try{const r=await fetch('/api/files'),d=await r.json(),s=document.getElementById('fsel'),p=s.value;
  s.innerHTML='';activeFile=d.active||'';
  fileInfo=d.file_info||{};
  meetingGroups=d.groups||{};
  // ヘッダー fsel: 今日・前日 + アクティブ + 直前選択ファイルと同じ日のファイル
  const [tod,yes]=_todayYestStr();
  const prevDt=(p?(d.file_info[p]?.dt||''):'').substring(0,8);
  const shown=new Set(d.files.filter(f=>{
    const dt=fileInfo[f]?.dt||'';
    return dt.startsWith(tod)||dt.startsWith(yes)||f===d.active||(prevDt&&dt.startsWith(prevDt));
  }));
  d.files.forEach(f=>{
    if(!shown.has(f))return;
    const o=document.createElement('option');o.value=f;
    o.textContent=(fileInfo[f]?.label||f)+(f===d.active?' ★':'');s.appendChild(o);
  });
  s.value=(p&&shown.has(p))?p:(d.active||'');curFile=s.value;
  populateYearSelect();
  if(leftTab==='meetings') renderMtgPane();
  else if(leftTab==='dates') renderDatePane();
  }catch(e){}
}
function populateYearSelect(){
  const sel=document.getElementById('srYear');if(!sel)return;
  const cur=sel.value;
  const years=[...new Set(Object.values(fileInfo).map(fi=>(fi.dt||'').substring(0,4)).filter(Boolean))].sort().reverse();
  sel.innerHTML=`<option value="">${I18N['dash.search_year']||'年'}</option>`;
  years.forEach(y=>{const o=document.createElement('option');o.value=y;o.textContent=y;sel.appendChild(o);});
  if(cur)sel.value=cur;
}
function initSearchSelects(){
  const mo=document.getElementById('srMonth');
  const dy=document.getElementById('srDay');
  const hr=document.getElementById('srHour');
  if(!mo||!dy||!hr)return;
  for(let i=1;i<=12;i++){const o=document.createElement('option');o.value=String(i).padStart(2,'0');o.textContent=String(i).padStart(2,'0');mo.appendChild(o);}
  for(let i=1;i<=31;i++){const o=document.createElement('option');o.value=String(i).padStart(2,'0');o.textContent=String(i).padStart(2,'0');dy.appendChild(o);}
  for(let i=0;i<=23;i++){const o=document.createElement('option');o.value=String(i).padStart(2,'0');o.textContent=String(i).padStart(2,'0');hr.appendChild(o);}
}
function togMtgPane(){
  const p=document.getElementById('pnlM');if(!p)return;
  const collapsed=p.classList.toggle('collapsed');
  const ch=document.getElementById('mtgChevron');
  if(ch)ch.innerHTML=collapsed?'&#x25BA;':'&#x25C4;';
}

/* --- 左ペイン タブ切替 --- */
function switchLeftTab(tab){
  leftTab=tab;
  ['dates','meetings','search'].forEach(t=>{
    const id=t.charAt(0).toUpperCase()+t.slice(1);
    const btn=document.getElementById('tab'+id);
    let pane;
    if(t==='dates') pane=document.getElementById('datePane');
    else if(t==='meetings') pane=document.getElementById('mtgContent');
    else pane=document.getElementById('searchPane');
    if(t===tab){
      if(btn) btn.classList.add('active');
      if(pane) pane.style.display=(t==='meetings')?'flex':'';
    }else{
      if(btn) btn.classList.remove('active');
      if(pane) pane.style.display='none';
    }
  });
  if(tab==='dates') renderDatePane();
  else if(tab==='meetings') renderMtgPane();
}
function renderDatePane(){
  const dp=document.getElementById('datePane');if(!dp)return;
  const files=Object.entries(fileInfo)
    .filter(([,fi])=>fi.meeting_group===null)
    .sort((a,b)=>b[0].localeCompare(a[0]));
  if(!files.length){
    dp.innerHTML=`<div style="color:var(--muted);font-size:12px;padding:8px">${esc(I18N['dash.dates_empty']||'No daily transcripts.')}</div>`;
    return;
  }
  dp.innerHTML=files.map(([f])=>
    `<div class="mg-file${f===curFile?' active':''}" onclick="selectMtgFile('${escAttr(f)}')" title="${escAttr(f)}">${esc((fileInfo[f]?.label||f))}</div>`
  ).join('');
}
"""
