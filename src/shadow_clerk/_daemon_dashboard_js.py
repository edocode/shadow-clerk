"""Shadow-clerk daemon: ダッシュボード JavaScript"""

# JavaScript content extracted from _HTML_TEMPLATE (between <script> and </script> tags)
_JS_TEMPLATE = """\
/*I18N_JSON*/
/* --- TranscriptName 構築ヘルパー（regex なし・fileInfo を使用） --- */
const TN={
  filename(dt,name){return 'transcript-'+dt+(name?'@'+name:'')+'.txt';},
  summaryFilename(dt,name){return 'summary-'+dt+(name?'@'+name:'')+'.md';},
};
let fileInfo={}; // /api/files の file_info をキャッシュ
let curFile='', activeFile='';
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
  // 既存会議ファイルドロップダウン
  const fsel=document.getElementById('fsel');
  const eSel=document.getElementById('extractExistingSel');
  eSel.innerHTML='';
  Array.from(fsel.options).forEach(o=>{
    if(o.value&&fileInfo[o.value]?.meeting_group!=null){
      const opt=document.createElement('option');opt.value=o.value;opt.textContent=o.value;eSel.appendChild(opt);
    }
  });
  // ラジオ初期化
  document.querySelector('input[name="extractTarget"][value="new"]').checked=true;
  eSel.disabled=true;
  document.querySelectorAll('input[name="extractTarget"]').forEach(r=>{
    r.onchange=()=>{eSel.disabled=(r.value!=='existing'||!r.checked);};
  });
  document.getElementById('extractModal').classList.add('open');
}
function closeExtractModal(){document.getElementById('extractModal').classList.remove('open');}
async function doExtractMeeting(){
  const sel=getSelectedLines();if(sel.length!==2)return;
  const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
  const startTs=ts0<ts1?ts0:ts1;const endTs=ts0<ts1?ts1:ts0;
  const file=document.getElementById('tf').textContent;
  const rad=document.querySelector('input[name="extractTarget"]:checked');
  let target='new';
  if(rad&&rad.value==='existing'){
    const eSel=document.getElementById('extractExistingSel');
    target=eSel.value||'new';
  }
  try{
    const r=await fetch('/api/transcript/extract-meeting',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({file:file,start_ts:startTs,end_ts:endTs,target:target})});
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
async function togTranslate(){
  if(translating){cmd('translate_stop');updateTranslateBtn(false);return;}
  cmd('translate_start');updateTranslateBtn(true);
}
async function regenTranslate(){
  if(!confirm(I18N['dash.translate_regen_confirm']))return;
  const fi=fileInfo[curFile];
  const dateArg=fi?(fi.dt+(fi.name?'@'+fi.name:'')):'';
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
async function loadFiles(){
  try{const r=await fetch('/api/files'),d=await r.json(),s=document.getElementById('fsel'),p=s.value;
  s.innerHTML='';activeFile=d.active||'';
  fileInfo=d.file_info||{};
  d.files.forEach(f=>{const o=document.createElement('option');o.value=f;
    o.textContent=(fileInfo[f]?.label||f)+(f===d.active?' ★':'');s.appendChild(o);});
  s.value=(p&&d.files.includes(p))?p:(d.active||'');curFile=s.value;
  meetingGroups=d.groups||{};
  renderMtgPane();}catch(e){}
}
function togMtgPane(){
  const p=document.getElementById('pnlM');if(!p)return;
  const collapsed=p.classList.toggle('collapsed');
  const ch=document.getElementById('mtgChevron');
  if(ch)ch.innerHTML=collapsed?'&#x25BA;':'&#x25C4;';
}

function renderMtgPane(){
  const mp=document.getElementById('mp');if(!mp)return;
  if(curGroup===null){
    // グループ一覧を表示
    document.getElementById('mtgBack').style.display='none';
    document.getElementById('mtgGroupLabel').style.display='none';
    document.getElementById('mtgListLabel').style.display='';
    document.getElementById('btnRenameMtgGroup').style.display='none';
    const order=Object.keys(meetingGroups).sort((a,b)=>a==='ad-hoc'?-1:b==='ad-hoc'?1:a.localeCompare(b));
    if(!order.length){mp.innerHTML=`<div style="color:var(--muted);font-size:12px;padding:8px">${esc(I18N['dash.meetings_empty']||'No meetings yet.')}</div>`;return;}
    mp.innerHTML=order.map(name=>{
      const cnt=meetingGroups[name].length;
      const icon=name==='ad-hoc'?'📁':'📂';
      return `<div class="mg-item" onclick="selectMtgGroup('${escAttr(name)}')">`
        +`<span class="mg-name">${icon} ${esc(name)}</span>`
        +`<span class="mg-cnt">${cnt}</span></div>`;
    }).join('');
  }else{
    // グループ内のファイル一覧を表示
    document.getElementById('mtgBack').style.display='';
    document.getElementById('mtgGroupLabel').textContent=curGroup;
    document.getElementById('mtgGroupLabel').style.display='';
    document.getElementById('mtgListLabel').style.display='none';
    document.getElementById('btnRenameMtgGroup').style.display=curGroup==='ad-hoc'?'none':'';
    const files=(meetingGroups[curGroup]||[]);
    mp.innerHTML=files.map(f=>{
      const label=fileInfo[f]?.meeting_label||f;
      return `<div class="mg-file${f===curFile?' active':''}" onclick="selectMtgFile('${escAttr(f)}')" title="${escAttr(f)}">${esc(label)}</div>`;
    }).join('');
  }
}
function selectMtgGroup(name){curGroup=name;renderMtgPane();}
function clearMtgGroup(){curGroup=null;renderMtgPane();return false;}
function selectMtgFile(file){
  const fsel=document.getElementById('fsel');fsel.value=file;onSel();_updateRenameMtgBtn();
}
async function loadT(file){
  try{const u=file?'/api/transcript?file='+encodeURIComponent(file):'/api/transcript';
  const d=await(await fetch(u)).json(),el=document.getElementById('tp');el.innerHTML='';
  d.lines.forEach(l=>el.insertAdjacentHTML('beforeend',fmtTranscriptLine(l)));
  document.getElementById('tf').textContent=d.file;el.scrollTop=el.scrollHeight;}catch(e){}
}
async function loadR(file){
  try{const u=file?'/api/translation?file='+encodeURIComponent(file):'/api/translation';
  const d=await(await fetch(u)).json(),el=document.getElementById('rp');el.innerHTML='';
  d.lines.forEach(l=>el.insertAdjacentHTML('beforeend',fmtLine(l)));
  document.getElementById('rf').textContent=d.file;el.scrollTop=el.scrollHeight;}catch(e){}
}
async function loadLogs(){
  try{const d=await(await fetch('/api/logs')).json(),el=document.getElementById('logc');
  d.lines.forEach(l=>{const c=l.includes('ERROR')?'e':l.includes('WARNING')?'w':'';
    el.insertAdjacentHTML('beforeend','<div class="ll '+c+'">'+esc(l)+'</div>');});
  el.scrollTop=el.scrollHeight;}catch(e){}
}
function onSel(){deselectAll();curFile=document.getElementById('fsel').value;loadT(curFile);loadR(curFile);renderMtgPane();_updateRenameMtgBtn();}
function goActive(){if(!activeFile)return;const s=document.getElementById('fsel');s.value=activeFile;onSel();}
async function cmd(c){try{await fetch('/api/command',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({command:c})});}catch(e){}}
function onLangChange(l){cmd(l==='auto'?'unset_language':'set_language '+l);}
fetchStatus();
es.addEventListener('response',e=>{
  const d=JSON.parse(e.data);if(d.content){
    document.getElementById('respBody').textContent=d.content;
    document.getElementById('resp').classList.add('show');}
});
es.addEventListener('alert',e=>{
  const d=JSON.parse(e.data);if(d.message){alert(d.message);}
});
function hideResp(){document.getElementById('resp').classList.remove('show');}
loadFiles();loadT('');loadR('');loadLogs();setInterval(loadFiles,10000);
const LANG_OPTS=['ja','en','zh','ko','fr','de','es','pt','ru'];
const CFG_FIELDS=[
  {type:'section',label:I18N['cfg.section.general']},
  {key:'ui_language',label:I18N['cfg.ui_language'],type:'select',opts:['ja','en']},
  {key:'output_directory',label:I18N['cfg.output_directory'],type:'text',ph:I18N['cfg.output_directory_ph']},
  {type:'section',label:I18N['cfg.section.transcription']},
  {key:'default_language',label:I18N['cfg.default_language'],type:'select',opts:['auto',...LANG_OPTS]},
  {key:'default_model',label:I18N['cfg.default_model'],type:'select',opts:['tiny','base','small','medium','large-v3']},
  {key:'initial_prompt',label:I18N['cfg.initial_prompt'],type:'text',ph:I18N['cfg.initial_prompt_ph']},
  {key:'whisper_beam_size',label:I18N['cfg.whisper_beam_size'],type:'select',opts:['1','2','3','5']},
  {key:'whisper_compute_type',label:I18N['cfg.whisper_compute_type'],type:'select',opts:['int8','float16','float32']},
  {key:'whisper_device',label:I18N['cfg.whisper_device'],type:'select',opts:['cpu','cuda']},
  {key:'japanese_asr_model',label:I18N['cfg.japanese_asr_model'],type:'select',opts:['default','kotoba-whisper','reazonspeech-k2']},
  {key:'interim_transcription',label:I18N['cfg.interim_transcription'],type:'bool'},
  {key:'interim_model',label:I18N['cfg.interim_model'],type:'select',opts:['tiny','base','small','medium']},
  {key:'interim_japanese_asr_model',label:I18N['cfg.interim_japanese_asr_model'],type:'select',opts:['default','kotoba-whisper','reazonspeech-k2']},
  {key:'voice_command_key',label:I18N['cfg.voice_command_key'],type:'select',opts:['menu','f23','ctrl_r','ctrl_l','alt_r','alt_l','shift_r','shift_l']},
  {key:'wake_word',label:I18N['cfg.wake_word'],type:'text',ph:I18N['cfg.wake_word_ph']},
  {type:'section',label:I18N['cfg.section.translation']},
  {key:'translate_language',label:I18N['cfg.translate_language'],type:'select',opts:LANG_OPTS},
  {key:'auto_translate',label:I18N['cfg.auto_translate'],type:'bool'},
  {key:'translation_provider',label:I18N['cfg.translation_provider'],type:'select',opts:['','claude','api','libretranslate']},
  {key:'libretranslate_endpoint',label:I18N['cfg.libretranslate_endpoint'],type:'text',ph:'http://localhost:5000'},
  {key:'libretranslate_api_key',label:I18N['cfg.libretranslate_api_key'],type:'text',ph:''},
  {key:'libretranslate_spell_check',label:I18N['cfg.libretranslate_spell_check'],type:'bool'},
  {key:'spell_check_model',label:I18N['cfg.spell_check_model'],type:'text',ph:'sonoisa/t5-base-japanese-spell-checker'},
  {key:'translation_hiragana_step',label:I18N['cfg.translation_hiragana_step'],type:'bool',def:true},
  {type:'section',label:I18N['cfg.section.summary']},
  {key:'auto_summary',label:I18N['cfg.auto_summary'],type:'bool'},
  {key:'summary_source',label:I18N['cfg.summary_source'],type:'select',opts:['transcript','translate']},
  {key:'summary_hiragana_step',label:I18N['cfg.summary_hiragana_step'],type:'bool',def:true},
  {key:'summary_length',label:I18N['cfg.summary_length'],type:'select',opts:['half','1page','2pages','3pages','4pages','5pages']},
  {type:'section',label:I18N['cfg.section.api']},
  {key:'llm_provider',label:I18N['cfg.llm_provider'],type:'select',opts:['claude','api']},
  {key:'api_endpoint',label:I18N['cfg.api_endpoint'],type:'text',ph:'https://...'},
  {key:'api_model',label:I18N['cfg.api_model'],type:'api_model'},
  {key:'api_key_env',label:I18N['cfg.api_key_env'],type:'text',ph:'SHADOW_CLERK_API_KEY'},
  {type:'section',label:I18N['cfg.section.gcal']},
  {key:'gcal_integration',label:I18N['cfg.gcal_integration'],type:'bool'},
  {key:'gcal_credentials_file',label:I18N['cfg.gcal_credentials_file'],type:'text',ph:I18N['cfg.gcal_credentials_file_ph']},
  {key:'gcal_calendar_id',label:I18N['cfg.gcal_calendar_id'],type:'text',ph:'primary'},
  {key:'gcal_buffer_minutes',label:I18N['cfg.gcal_buffer_minutes'],type:'select',num:true,opts:['0','1','2','3','5','10']},
  {key:'gcal_end_buffer_minutes',label:I18N['cfg.gcal_end_buffer_minutes'],type:'select',num:true,opts:['0','1','2','3','5']},
];
let cfgData={};
async function openCfg(){
  try{cfgData=await(await fetch('/api/config')).json();}catch(e){return;}
  const b=document.getElementById('cfgBody');b.innerHTML='';
  CFG_FIELDS.forEach(f=>{
    if(f.type==='section'){
      const h=document.createElement('div');h.className='cfg-section';h.textContent=f.label;b.appendChild(h);return;
    }
    const lbl=document.createElement('label');lbl.textContent=f.label;b.appendChild(lbl);
    let el;const v=(cfgData[f.key]!==undefined)?cfgData[f.key]:f.def;
    if(f.type==='bool'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      ['true','false'].forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      el.value=v?'true':'false';
    }else if(f.type==='select'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      f.opts.forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      if(v!==null&&v!==undefined)el.value=String(v);
    }else if(f.type==='api_model'){
      el=document.createElement('div');el.style.display='flex';el.style.gap='4px';el.style.alignItems='center';el.style.width='100%';
      const sel=document.createElement('select');sel.id='cfg_'+f.key;sel.style.flex='1';sel.style.width='auto';
      const cur=document.createElement('option');cur.value=(v===null||v===undefined)?'':String(v);
      cur.textContent=(v===null||v===undefined)?'(not set)':String(v);sel.appendChild(cur);
      el.appendChild(sel);
      const btn=document.createElement('button');btn.textContent='\\u21BB';btn.title='Fetch models';
      btn.style.cssText='padding:2px 8px;cursor:pointer;width:auto;flex-shrink:0;';
      btn.onclick=async()=>{
        btn.disabled=true;btn.textContent='...';
        try{const d=await(await fetch('/api/models')).json();
          if(d.error){alert(d.error);return;}
          const prev=sel.value;sel.innerHTML='';
          const empty=document.createElement('option');empty.value='';empty.textContent='(not set)';sel.appendChild(empty);
          d.models.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);});
          if(prev)sel.value=prev;
        }catch(e){alert('Failed to fetch models');}
        finally{btn.disabled=false;btn.textContent='\\u21BB';}
      };el.appendChild(btn);
    }else if(f.type==='json'){
      el=document.createElement('textarea');el.id='cfg_'+f.key;
      el.value=JSON.stringify(v||[],null,2);
    }else{
      el=document.createElement('input');el.type='text';el.id='cfg_'+f.key;
      el.value=(v===null||v===undefined)?'':String(v);
      if(f.ph)el.placeholder=f.ph;
    }
    b.appendChild(el);
  });
  document.getElementById('cfgSaved').style.display='none';
  const jaEl=document.getElementById('cfg_japanese_asr_model');
  if(jaEl)jaEl.onchange=updateCfgDisabled;
  const ijaEl=document.getElementById('cfg_interim_japanese_asr_model');
  if(ijaEl)ijaEl.onchange=updateCfgDisabled;
  updateCfgDisabled();
  document.getElementById('cfgModal').classList.add('open');
  if(cfgData.api_endpoint){fetchApiModels();}
}
async function fetchApiModels(){
  const sel=document.getElementById('cfg_api_model');if(!sel)return;
  try{const d=await(await fetch('/api/models')).json();
    if(d.error||!d.models.length)return;
    const prev=sel.value;sel.innerHTML='';
    const empty=document.createElement('option');empty.value='';empty.textContent='(not set)';sel.appendChild(empty);
    d.models.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);});
    if(prev)sel.value=prev;
  }catch(e){}
}
function closeCfg(){document.getElementById('cfgModal').classList.remove('open');}
async function saveCfg(){
  const d={};
  CFG_FIELDS.forEach(f=>{
    const el=document.getElementById('cfg_'+f.key);if(!el)return;
    if(f.type==='bool'){d[f.key]=el.value==='true';}
    else if(f.type==='json'){try{d[f.key]=JSON.parse(el.value);}catch(e){d[f.key]=cfgData[f.key];}}
    else if(f.type==='number'){const n=parseInt(el.value,10);d[f.key]=isNaN(n)?cfgData[f.key]:n;}
    else if(f.type==='select'&&f.num){const sv=el.value;const n=parseInt(sv,10);d[f.key]=isNaN(n)?null:n;}
    else if(f.type==='select'){const sv=el.value;d[f.key]=(sv===''||(sv==='auto'&&f.key==='default_language'))?null:sv;}
    else{const v=el.value.trim();d[f.key]=(v===''||v==='null')?null:v;}
  });
  const langChanged=d.ui_language&&d.ui_language!==cfgData.ui_language;
  try{await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(d)});
    if(langChanged){location.reload();return;}
    const s=document.getElementById('cfgSaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
function updateCfgDisabled(){
  const ija=document.getElementById('cfg_interim_japanese_asr_model');
  const iIsK2=ija&&ija.value==='reazonspeech-k2';
  const im=document.getElementById('cfg_interim_model');
  if(im){im.disabled=iIsK2;im.style.opacity=iIsK2?'0.5':'1';}
}
const GL_COL_OPTS=[...LANG_OPTS,'reading','note'];
let glossaryCols=[];
function glossaryAddRow(vals){
  const tb=document.getElementById('glossaryBody');
  const tr=document.createElement('tr');
  glossaryCols.forEach((c,i)=>{
    const td=document.createElement('td');
    const inp=document.createElement('input');
    inp.type='text'; inp.value=(vals&&vals[i])||'';
    inp.placeholder=c;
    td.appendChild(inp); tr.appendChild(td);
  });
  const del=document.createElement('td');
  del.className='gl-del'; del.textContent='\u00d7';
  del.onclick=()=>tr.remove();
  tr.appendChild(del); tb.appendChild(tr);
  return tr;
}
function glossaryMakeHeadSel(val){
  const sel=document.createElement('select');
  sel.style.cssText='background:transparent;color:var(--muted);border:none;font-weight:600;font-size:12px;cursor:pointer;padding:2px;';
  GL_COL_OPTS.forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;sel.appendChild(op);});
  sel.value=val;
  sel.onchange=()=>{const idx=[...sel.closest('tr').children].indexOf(sel.parentElement);glossaryCols[idx]=sel.value;};
  return sel;
}
async function openGlossary(){
  let text='';
  try{const r=await fetch('/api/glossary');text=await r.text();}catch(e){}
  const lines=text.split('\\n').filter(l=>l.trim()&&!l.startsWith('#'));
  glossaryCols=(lines.length>0)?lines[0].split('\\t'):['ja','en','reading','note'];
  const head=document.getElementById('glossaryHead');
  head.innerHTML='';
  glossaryCols.forEach(c=>{const th=document.createElement('th');th.appendChild(glossaryMakeHeadSel(c));head.appendChild(th);});
  const thDel=document.createElement('th');thDel.style.width='30px';head.appendChild(thDel);
  const tb=document.getElementById('glossaryBody');
  tb.innerHTML='';
  for(let i=1;i<lines.length;i++){
    const cols=lines[i].split('\\t');
    glossaryAddRow(cols);
  }
  if(lines.length<=1)glossaryAddRow();
  document.getElementById('glossarySaved').style.display='none';
  document.getElementById('glossaryModal').classList.add('open');
}
function closeGlossary(){document.getElementById('glossaryModal').classList.remove('open');}
async function saveGlossary(){
  glossaryCols=[...document.querySelectorAll('#glossaryHead select')].map(s=>s.value);
  const rows=[glossaryCols.join('\\t')];
  document.querySelectorAll('#glossaryBody tr').forEach(tr=>{
    const vals=Array.from(tr.querySelectorAll('input')).map(i=>i.value);
    if(vals.some(v=>v.trim()))rows.push(vals.join('\\t'));
  });
  const text=rows.join('\\n')+'\\n';
  try{await fetch('/api/glossary',{method:'POST',headers:{'Content-Type':'text/plain; charset=utf-8'},
    body:text});
    const s=document.getElementById('glossarySaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
async function genSummary(){
  const f=curFile||undefined;
  const b=f?JSON.stringify({file:f}):'{}';
  try{await fetch('/api/summary',{method:'POST',headers:{'Content-Type':'application/json'},body:b});
    alert(I18N['dash.summary_started']);}catch(e){}
}
async function viewSummary(){
  const f=curFile?'?file='+encodeURIComponent(curFile):'';
  try{const d=await(await fetch('/api/summary'+f)).json();
    document.getElementById('summaryTitle').textContent=I18N['dash.summary_prefix']+(d.file||'');
    document.getElementById('summaryContent').textContent=d.content||I18N['dash.no_summary'];
    document.getElementById('summaryModal').classList.add('open');
  }catch(e){}
}
function closeSummary(){document.getElementById('summaryModal').classList.remove('open');}
function customCmdAddRow(pattern,action){
  const tb=document.getElementById('customCmdBody');
  const tr=document.createElement('tr');
  const td1=document.createElement('td');
  const inp1=document.createElement('input');inp1.type='text';inp1.value=pattern||'';inp1.placeholder='regex pattern';
  td1.appendChild(inp1);tr.appendChild(td1);
  const td2=document.createElement('td');
  const inp2=document.createElement('input');inp2.type='text';inp2.value=action||'';inp2.placeholder='shell command';
  td2.appendChild(inp2);tr.appendChild(td2);
  const del=document.createElement('td');
  del.className='gl-del';del.textContent='\\u00d7';
  del.onclick=()=>tr.remove();
  tr.appendChild(del);tb.appendChild(tr);
  return tr;
}
async function openCustomCmds(){
  let cmds=[];
  try{const d=await(await fetch('/api/config')).json();cmds=d.custom_commands||[];}catch(e){}
  const tb=document.getElementById('customCmdBody');tb.innerHTML='';
  cmds.forEach(c=>customCmdAddRow(c.pattern||'',c.action||''));
  if(cmds.length===0)customCmdAddRow();
  document.getElementById('customCmdSaved').style.display='none';
  document.getElementById('customCmdModal').classList.add('open');
}
function closeCustomCmds(){document.getElementById('customCmdModal').classList.remove('open');}
async function saveCustomCmds(){
  const rows=[];
  document.querySelectorAll('#customCmdBody tr').forEach(tr=>{
    const inputs=tr.querySelectorAll('input');
    const p=(inputs[0]||{}).value||'';
    const a=(inputs[1]||{}).value||'';
    if(p.trim()||a.trim())rows.push({pattern:p,action:a});
  });
  try{
    const cfg=await(await fetch('/api/config')).json();
    cfg.custom_commands=rows;
    await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
    const s=document.getElementById('customCmdSaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
function openRenameMtgGroup(){
  if(!curGroup||curGroup==='ad-hoc')return;
  const inp=document.getElementById('renameMtgGroupInput');
  inp.value=curGroup;
  const cnt=(meetingGroups[curGroup]||[]).length;
  document.getElementById('renameMtgGroupPreview').textContent=
    (I18N['dash.rename_group_preview']||'{n} files will be renamed').replace('{n}',cnt);
  document.getElementById('renameMtgGroupSaved').style.display='none';
  document.getElementById('renameMtgGroupModal').classList.add('open');
  inp.focus();inp.select();
}
function closeRenameMtgGroup(){document.getElementById('renameMtgGroupModal').classList.remove('open');}
async function doRenameMtgGroup(){
  const newName=document.getElementById('renameMtgGroupInput').value.trim();
  if(!newName||newName===curGroup){closeRenameMtgGroup();return;}
  const files=meetingGroups[curGroup]||[];
  let renamed=0;
  for(const f of files){
    try{
      const r=await fetch('/api/transcript/rename-meeting',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({file:f,name:newName})});
      const d=await r.json();
      if(d.status==='ok')renamed++;
    }catch(e){}
  }
  const saved=document.getElementById('renameMtgGroupSaved');
  saved.style.display='inline';
  const prevGroup=curGroup;
  curGroup=newName;
  await loadFiles();
  // 新グループに切り替え
  if(meetingGroups[newName])selectMtgGroup(newName);
  setTimeout(closeRenameMtgGroup,800);
}
function _isMeetingFile(f){return f&&fileInfo[f]?.meeting_group!=null;}
function _updateRenameMtgBtn(){
  const btn=document.getElementById('btnRenameMtg');
  if(btn)btn.style.display=_isMeetingFile(curFile)?'':'none';
}
function openRenameMtg(){
  if(!_isMeetingFile(curFile))return;
  // 現在のファイル名から会議名を抽出
  const curName=fileInfo[curFile]?.name||'';
  document.getElementById('renameMtgCurrent').textContent=curFile;
  // 既存グループのドロップダウンを構築
  const sel=document.getElementById('renameMtgSel');
  sel.innerHTML='<option value="">— '+( I18N['dash.rename_meeting_new']||'新規入力')+' —</option>';
  Object.keys(meetingGroups).sort((a,b)=>a==='ad-hoc'?-1:b==='ad-hoc'?1:a.localeCompare(b)).forEach(n=>{
    const o=document.createElement('option');o.value=n;o.textContent=n;
    if(n===curName)o.selected=true;
    sel.appendChild(o);
  });
  const inp=document.getElementById('renameMtgInput');
  inp.value=curName;
  _updateRenameMtgPreview(curName);
  document.getElementById('renameMtgSaved').style.display='none';
  document.getElementById('renameMtgModal').classList.add('open');
  inp.focus();
}
function onRenameMtgSel(val){
  if(val)document.getElementById('renameMtgInput').value=val;
  _updateRenameMtgPreview(val||document.getElementById('renameMtgInput').value);
}
function _updateRenameMtgPreview(name){
  const fi=fileInfo[curFile];if(!fi)return;
  document.getElementById('renameMtgPreview').textContent='→ '+TN.filename(fi.dt,name||null);
}
function closeRenameMtg(){document.getElementById('renameMtgModal').classList.remove('open');}
async function doRenameMtg(){
  const name=document.getElementById('renameMtgInput').value.trim();
  try{
    const r=await fetch('/api/transcript/rename-meeting',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({file:curFile,name})});
    const d=await r.json();
    if(d.status!=='ok'){alert(d.message||'Error');return;}
    const saved=document.getElementById('renameMtgSaved');
    saved.style.display='inline';setTimeout(()=>saved.style.display='none',2000);
    curFile=d.new_file;
    await loadFiles();
    loadT(curFile);loadR(curFile);
    setTimeout(closeRenameMtg,800);
  }catch(e){alert('Error: '+e.message);}
}
function openHelp(){
  document.getElementById('helpContent').textContent=I18N['dash.help_body'];
  const lang=cfgData&&cfgData.ui_language||'en';
  document.getElementById('helpReadmeLink').href='https://github.com/edocode/shadow-clerk/blob/main/'+(lang==='ja'?'README.ja.md':'README.md');
  document.getElementById('helpModal').classList.add('open');
}
function closeHelp(){document.getElementById('helpModal').classList.remove('open');}
async function openGcal(){
  const body=document.getElementById('gcalBody');
  body.textContent=I18N['dash.loading']||'...';
  document.getElementById('gcalModal').classList.add('open');
  try{
    const d=await(await fetch('/api/gcal-events')).json();
    if(!d.enabled){body.textContent=I18N['dash.gcal_disabled']||'Google Calendar integration is not enabled.';return;}
    if(!d.events||d.events.length===0){body.textContent=I18N['dash.gcal_no_events']||'No upcoming events.';return;}
    const now=new Date();
    const rows=d.events.map(ev=>{
      const start=ev.start?new Date(ev.start):null;
      const end=ev.end?new Date(ev.end):null;
      const fmt=dt=>dt?dt.toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'}):'';
      const fmtDate=dt=>dt?dt.toLocaleDateString([],{month:'numeric',day:'numeric'}):'';
      const isToday=dt=>dt&&dt.toDateString()===now.toDateString();
      const dateStr=start?(isToday(start)?'':fmtDate(start)+' '):'';
      const status=ev.status==='started'?'🔴':ev.status==='ended'?'✅':'🔵';
      return `<div style="display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);">`
        +`<span style="font-size:16px">${status}</span>`
        +`<div style="flex:1;min-width:0">`
        +`<div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(ev.summary)}</div>`
        +`<div style="font-size:11px;color:var(--muted)">${dateStr}${fmt(start)} – ${fmt(end)}</div>`
        +`</div></div>`;
    }).join('');
    body.innerHTML=rows;
  }catch(e){body.textContent='Error: '+e.message;}
}
function closeGcal(){document.getElementById('gcalModal').classList.remove('open');}
"""
