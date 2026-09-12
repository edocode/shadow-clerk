"""Shadow-clerk daemon: ダッシュボード JavaScript (part B)"""

_JS_TEMPLATE_PANELS = """\
/* --- 検索 --- */
async function doSearch(){
  const year=document.getElementById('srYear').value.trim();
  const month=document.getElementById('srMonth').value.trim();
  const day=document.getElementById('srDay').value.trim();
  const hour=document.getElementById('srHour').value.trim();
  const query=document.getElementById('srQuery').value.trim();
  const type=(document.querySelector('input[name="srType"]:checked')||{}).value||'all';
  const p=new URLSearchParams();
  if(year)p.set('year',year);if(month)p.set('month',month);
  if(day)p.set('day',day);if(hour)p.set('hour',hour);
  if(query)p.set('query',query);p.set('type',type);
  const res=document.getElementById('searchResults');
  res.innerHTML=`<div style="color:var(--muted);font-size:12px;padding:8px">${esc(I18N['dash.loading']||'...')}</div>`;
  try{
    const d=await(await fetch('/api/search?'+p.toString())).json();
    renderSearchResults(d.results||[]);
  }catch(e){res.innerHTML='';}
}
function renderSearchResults(results){
  const res=document.getElementById('searchResults');
  if(!results.length){
    res.innerHTML=`<div style="color:var(--muted);font-size:12px;padding:8px">${esc(I18N['dash.search_empty']||'No results.')}</div>`;
    return;
  }
  const typeLabel={transcript:'T',translation:'R',summary:'S'};
  res.innerHTML=results.map(r=>{
    const tl=r.type&&r.type!=='transcript'?(typeLabel[r.type]||r.type):'';
    return `<div class="sr-item" onclick="openSearchResult('${escAttr(escJs(r.file))}',${r.line||0},'${escAttr(escJs(r.type||''))}')" title="${escAttr(r.text||'')}">`
      +`<span class="sr-display">${esc(r.display||r.file)}</span>`
      +(tl?`<span class="sr-type">${esc(tl)}</span>`:'')
      +`</div>`;
  }).join('');
}
function openSearchResult(file,line,type){
  selectMtgFile(file); // fsel への追加 + onSel() を一括処理
  if(type==='summary'){openSumPane();return;} // summary ヒットは transcript 行と対応しない
  if(line>0){
    const panelId=type==='translation'?'rp':'tp';
    // 読み込み完了を待つ（大きいファイルで 400ms 固定だと間に合わないためリトライ）
    let tries=0;
    const tryScroll=()=>{
      const el=document.getElementById(panelId);
      const lns=el?el.querySelectorAll('.ln'):[];
      if(lns.length>=line){
        lns[line-1].scrollIntoView({block:'center'});
        lns[line-1].style.outline='1px solid var(--accent)';
        setTimeout(()=>{if(lns[line-1])lns[line-1].style.outline='';},2000);
      }else if(++tries<15){setTimeout(tryScroll,400);}
    };
    setTimeout(tryScroll,400);
  }
}
let meetingSortMode=(function(){try{return localStorage.getItem('meetingSortMode')||'newest';}catch(e){return 'newest';}})();
function _groupMaxDt(name){
  const fs=meetingGroups[name]||[];
  let m='';
  for(const f of fs){const d=fileInfo[f]?.dt||'';if(d>m)m=d;}
  return m;
}
function _updateMtgSortBtn(){
  const b=document.getElementById('btnMtgSort');if(!b)return;
  b.textContent=meetingSortMode==='abc'?(I18N['dash.sort_abc']||'ABC'):(I18N['dash.sort_newest']||'Newest');
}
function togMtgSort(){
  meetingSortMode=meetingSortMode==='abc'?'newest':'abc';
  try{localStorage.setItem('meetingSortMode',meetingSortMode);}catch(e){}
  renderMtgPane();
}
function renderMtgPane(){
  const mp=document.getElementById('mp');if(!mp)return;
  _updateMtgSortBtn();
  if(curGroup===null){
    // グループ一覧を表示
    document.getElementById('meetingBack').style.display='none';
    document.getElementById('meetingGroupLabel').style.display='none';
    document.getElementById('meetingListLabel').style.display='';
    document.getElementById('btnRenameMtgGroup').style.display='none';
    const order=Object.keys(meetingGroups).sort((a,b)=>{
      if(a==='ad-hoc')return -1;if(b==='ad-hoc')return 1;
      if(meetingSortMode==='newest'){
        const da=_groupMaxDt(a),db=_groupMaxDt(b);
        if(da!==db)return db.localeCompare(da);
      }
      return a.localeCompare(b);
    });
    if(!order.length){mp.innerHTML=`<div style="color:var(--muted);font-size:12px;padding:8px">${esc(I18N['dash.meetings_empty']||'No meetings yet.')}</div>`;return;}
    mp.innerHTML=order.map(name=>{
      const cnt=meetingGroups[name].length;
      const icon=name==='ad-hoc'?'📁':'📂';
      return `<div class="mg-item" onclick="selectMtgGroup('${escAttr(escJs(name))}')">`
        +`<span class="mg-name">${icon} ${esc(name)}</span>`
        +`<span class="mg-cnt">${cnt}</span></div>`;
    }).join('');
  }else{
    // グループ内のファイル一覧を表示
    document.getElementById('meetingBack').style.display='';
    document.getElementById('meetingGroupLabel').textContent=curGroup;
    document.getElementById('meetingGroupLabel').style.display='';
    document.getElementById('meetingListLabel').style.display='none';
    document.getElementById('btnRenameMtgGroup').style.display=curGroup==='ad-hoc'?'none':'';
    const files=(meetingGroups[curGroup]||[]).slice().sort((a,b)=>{
      if(meetingSortMode==='abc'){
        const la=(fileInfo[a]?.label||a),lb=(fileInfo[b]?.label||b);
        const c=la.localeCompare(lb);if(c)return c;
      }
      const da=fileInfo[a]?.dt||'',db=fileInfo[b]?.dt||'';
      return db.localeCompare(da);
    });
    mp.innerHTML=files.map(f=>{
      const fi=fileInfo[f];
      return `<div class="mg-file${f===curFile?' active':''}" onclick="selectMtgFile('${escAttr(escJs(f))}')" title="${escAttr(f)}"><span class="mg-file-label">${esc((fi?.label||f))}</span>${_badges(fi)}${_wdBtn(f)}</div>`;
    }).join('');
  }
}
function selectMtgGroup(name){curGroup=name;renderMtgPane();}
function clearMtgGroup(){curGroup=null;renderMtgPane();return false;}
function selectMtgFile(file){
  const fsel=document.getElementById('fsel');
  // 選んだファイルと同じ日付のファイルをまとめて fsel に追加
  const selDt=(fileInfo[file]?.dt||'').substring(0,8);
  const existing=new Set(Array.from(fsel.options).map(o=>o.value));
  Object.keys(fileInfo)
    .filter(f=>selDt?(fileInfo[f]?.dt||'').startsWith(selDt):f===file)
    .forEach(f=>{
      if(existing.has(f))return;
      const o=document.createElement('option');o.value=f;
      o.textContent=(fileInfo[f]?.label||f)+(f===activeFile?' ★':'');
      fsel.appendChild(o);
    });
  fsel.value=file;onSel();_updateRenameMtgBtn();
}
async function loadT(file){
  const g=++_tGen;
  try{const u=file?'/api/transcript?file='+encodeURIComponent(file):'/api/transcript';
  const d=await(await fetch(u)).json();if(g!==_tGen)return;
  const el=document.getElementById('tp');el.innerHTML='';
  d.lines.forEach(l=>el.insertAdjacentHTML('beforeend',fmtTranscriptLine(l)));
  document.getElementById('tf').textContent=d.file;el.scrollTop=el.scrollHeight;}catch(e){}
}
async function loadR(file){
  const g=++_rGen;
  try{const u=file?'/api/translation?file='+encodeURIComponent(file):'/api/translation';
  const d=await(await fetch(u)).json();if(g!==_rGen)return;
  const el=document.getElementById('rp');el.innerHTML='';
  if(d.translating&&!d.lines.length){
    el.insertAdjacentHTML('beforeend','<div class="translating-msg">'+esc(I18N['dash.translating'])+'</div>');
  }else{
    d.lines.forEach(l=>el.insertAdjacentHTML('beforeend',fmtLine(l)));
  }
  document.getElementById('rf').textContent=d.file;el.scrollTop=el.scrollHeight;}catch(e){}
}
async function loadLogs(){
  try{const d=await(await fetch('/api/logs')).json(),el=document.getElementById('logc');
  d.lines.forEach(l=>{const c=l.includes('ERROR')?'e':l.includes('WARNING')?'w':'';
    el.insertAdjacentHTML('beforeend','<div class="ll '+c+'">'+esc(l)+'</div>');});
  el.scrollTop=el.scrollHeight;}catch(e){}
}
function onSel(){deselectAll();curFile=document.getElementById('fsel').value;_setHashFile(curFile);loadT(curFile);loadR(curFile);loadS(curFile);loadAdvice(curFile);loadAnalysis(curFile);renderMtgPane();_updateRenameMtgBtn();}
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
  const d=JSON.parse(e.data);if(d.message){alert(d.message);loadS(curFile);openSumPane();}
});
function hideResp(){document.getElementById('resp').classList.remove('show');}
// ペインの初回読み込みは loadFiles() に一本化する。ここでも読むと、
// ハッシュの有無で「二重に読む」と「一度も読まない」に分かれてしまう
initSearchSelects();switchLeftTab('dates');switchSumTab('summary');loadFiles();loadLogs();
// 翻訳・ミュート等のボタン状態は SSE に載らないため、定期的にステータスも同期する
setInterval(()=>{loadFiles();fetchStatus();},10000);
window.addEventListener('hashchange',()=>{const f=_hashFile();if(f&&fileInfo[f]&&f!==curFile)selectMtgFile(f);});
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
let glossaryComments=[];
async function openGlossary(){
  let text='';
  try{const r=await fetch('/api/glossary');text=await r.text();}catch(e){}
  // コメント行は編集 UI に出さないが、保存時に消さないよう保持する
  glossaryComments=text.split('\\n').filter(l=>l.startsWith('#'));
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
  const rows=[...glossaryComments,glossaryCols.join('\\t')];
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
function _renderAttendees(list){
  if(!Array.isArray(list)||list.length===0)return '';
  const label=I18N['dash.attendees']||'Attendees';
  const note=I18N['dash.attendees_note']||'';
  return '<div class="attendees-box" style="border:1px solid var(--border);border-radius:4px;padding:6px 8px;margin-bottom:8px;font-size:12px;background:var(--bg2,transparent)">'
    +'<div style="font-weight:600;margin-bottom:2px">'+esc(label)+'</div>'
    +'<div>'+list.map(esc).join(', ')+'</div>'
    +(note?'<div style="font-size:11px;color:var(--muted);margin-top:2px">'+esc(note)+'</div>':'')
    +'</div>';
}
let _sumMd='';   // 画面には HTML を出すので、コピー用に生の Markdown を持っておく
async function loadS(file){
  const el=document.getElementById('sp');if(!el)return;
  const g=++_sGen;
  const f=file?'?file='+encodeURIComponent(file):'';
  try{
    const [sumD,attD]=await Promise.all([
      fetch('/api/summary'+f).then(r=>r.json()),
      file?fetch('/api/attendees?file='+encodeURIComponent(file)).then(r=>r.json()).catch(()=>({attendees:[]})):Promise.resolve({attendees:[]}),
    ]);
    if(g!==_sGen)return;
    document.getElementById('sf').textContent=sumD.file||'';
    _sumMd=sumD.content||'';
    const cp=document.getElementById('btnCopySum');if(cp)cp.style.display=_sumMd?'':'none';
    const attHtml=_renderAttendees(attD.attendees||[]);
    if(sumD.content){
      // html はサーバが起こしたもの。レンダラが落ちたときだけ生の Markdown を出す
      el.innerHTML=attHtml+(sumD.html
        ?'<div class="md-body">'+sumD.html+'</div>'
        :'<div class="summary-body">'+esc(sumD.content)+'</div>');
    }else{
      el.innerHTML=attHtml+'<div class="summary-empty"><div style="color:var(--muted);margin-bottom:8px">'+esc(I18N['dash.no_summary']||'No summary.')+'</div>'
        +'<button class="pri" onclick="genSummary()">'+esc(I18N['dash.summary']||'Summary')+'</button></div>';
    }
  }catch(e){el.innerHTML='';}
}
/* 画面は HTML なので、選択してコピーすると書式が落ちる。元の Markdown を渡す */
async function copySummaryMd(){
  if(!_sumMd)return;
  let ok=false;
  try{await navigator.clipboard.writeText(_sumMd);ok=true;}
  catch(e){
    // localhost 以外の http では clipboard API が無い。textarea 経由に落とす
    const ta=document.createElement('textarea');
    ta.value=_sumMd;ta.style.position='fixed';ta.style.opacity='0';
    document.body.appendChild(ta);ta.select();
    try{ok=document.execCommand('copy');}catch(e2){}
    ta.remove();
  }
  // 失敗しても ✓ を出すと、貼り付けて初めて空だと気づくことになる
  const b=document.getElementById('btnCopySum');
  if(b&&!b.dataset.copied){
    b.dataset.copied='1';const o=b.textContent;b.textContent=ok?'\u2713':'\u2717';
    setTimeout(()=>{b.textContent=o;delete b.dataset.copied;},1200);
  }
}
async function loadAdvice(file){
  const g=++_adGen;
  const f=file?'?file='+encodeURIComponent(file):'';
  try{const d=await(await fetch('/api/advice'+f)).json();if(g!==_adGen)return;
    _renderGenerated('adp','adf',d,'dash.no_advice');
  }catch(e){}
}
async function loadAnalysis(file){
  const g=++_anGen;
  const f=file?'?file='+encodeURIComponent(file):'';
  try{const d=await(await fetch('/api/analysis'+f)).json();if(g!==_anGen)return;
    _renderGenerated('anp','anf',d,'dash.no_analysis');
    const el=document.getElementById('anp');if(el)el.scrollTop=el.scrollHeight;
  }catch(e){}
}
/* 開始と停止を1つのボタンで受ける。走っているかは _consoleRunning が持つ */
async function toggleAnalysis(){
  // 連打すると「分析開始」が多重送信され、起動途中の PTY に2回目の初期
  // プロンプトが即 write されて消えうる(I1)。送信中はボタンを無効化する
  const btn=document.getElementById('btnStartAnalysis');
  if(btn){if(btn.disabled)return;btn.disabled=true;}
  if(_consoleRunning){
    try{await stopConsole();}finally{if(btn)btn.disabled=false;}
    return;
  }
  const body=curFile?JSON.stringify({transcript:curFile}):'{}';
  try{const r=await fetch('/api/console/start',{method:'POST',
    headers:{'Content-Type':'application/json'},body});
    const d=await r.json();
    if(d.status!=='ok')alert(I18N['dash.console_start_failed']||'Failed to start the AI assistant.');
    else switchLogTab('console');
  }catch(e){}
  finally{if(btn)btn.disabled=false;}
}
async function genSummary(){
  const f=curFile||undefined;
  const b=f?JSON.stringify({file:f}):'{}';
  try{await fetch('/api/summary',{method:'POST',headers:{'Content-Type':'application/json'},body:b});
    const el=document.getElementById('sp');
    if(el)el.innerHTML='<div class="summary-empty"><div style="color:var(--muted)">'+esc(I18N['dash.summary_started']||'Generating...')+'</div></div>';
  }catch(e){}
}
async function regenSummary(){
  if(!confirm(I18N['dash.summary_regen_confirm']))return;
  await genSummary();
}
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
    await loadFiles();
    // loadFiles は旧ファイル名が消えた時点でアクティブファイルにフォールバックするため、
    // リネーム後のファイルを明示的に選択し直す（fsel への option 追加 + パネル再読込）
    selectMtgFile(d.new_file);
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
      const attendees=Array.isArray(ev.attendees)?ev.attendees:[];
      const attLabel=I18N['dash.attendees']||'Attendees';
      const attHtml=attendees.length?`<div style="font-size:11px;color:var(--muted);margin-top:2px">${esc(attLabel)}: ${attendees.map(esc).join(', ')}</div>`:'';
      return `<div style="display:flex;align-items:flex-start;gap:8px;padding:6px 0;border-bottom:1px solid var(--border);">`
        +`<span style="font-size:16px">${status}</span>`
        +`<div style="flex:1;min-width:0">`
        +`<div style="font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(ev.summary)}</div>`
        +`<div style="font-size:11px;color:var(--muted)">${dateStr}${fmt(start)} – ${fmt(end)}</div>`
        +attHtml
        +`</div></div>`;
    }).join('');
    body.innerHTML=rows;
  }catch(e){body.textContent='Error: '+e.message;}
}
function closeGcal(){document.getElementById('gcalModal').classList.remove('open');}
"""
