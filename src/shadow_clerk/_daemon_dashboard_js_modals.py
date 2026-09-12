"""Shadow-clerk daemon: ダッシュボード JavaScript (削除・抽出モーダル)

core から切り出したもの。ここは全てモーダルのイベントハンドラで、
onclick からしか呼ばれない。core の esc / curFile / fileInfo などに
依存するため、連結順は core の後でなければならない。
"""

_JS_TEMPLATE_MODALS = """\
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
  const isMtg=_isMeetingFile(curFile);
  const mergeOpt=document.getElementById('fileDelMergeOpt');
  mergeOpt.style.display=isMtg?'':'none';
  if(isMtg){
    const r=document.querySelector('input[name="fileDelMode"][value="merge"]');
    if(r)r.checked=true;
  }
  // サーバが返す related（翻訳・summary・offset）を使い、実際に削除されるファイルと一致させる。
  // 翻訳ファイルは /api/files に載らず fsel にも無いため、以前は一覧から漏れていた
  const files=[curFile,...((fi?.related)||[])];
  const list=document.getElementById('fileDelList');
  list.innerHTML='';
  files.forEach(f=>{const d=document.createElement('div');d.textContent=f;list.appendChild(d);});
  document.getElementById('fileDelModal').classList.add('open');
}
function closeFileDelModal(){document.getElementById('fileDelModal').classList.remove('open');}
async function doFileDel(){
  if(!curFile)return;
  const mode=(document.querySelector('input[name="fileDelMode"]:checked')?.value)||'delete';
  const url=(_isMeetingFile(curFile)&&mode==='merge')?'/api/transcript/merge-to-daily':'/api/transcript/delete-file';
  const errKey=mode==='merge'?'dash.merge_to_daily_error':'dash.delete_error';
  try{
    const r=await fetch(url,{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({file:curFile})});
    const d=await r.json();
    if(d.status==='ok'){closeFileDelModal();loadFiles();}
    else{alert(I18N[errKey]||d.message||'Error');}
  }catch(e){alert(I18N[errKey]||'Error');}
}
/* --- Extract meeting modal --- */
function _dtPlusDays(dateStr,n){
  // new Date('YYYY-MM-DD') は UTC 解釈になり、UTC より遅いタイムゾーンで1日ずれるため
  // ローカル時刻のコンポーネント指定で構築する
  const d=new Date(+dateStr.substring(0,4),+dateStr.substring(4,6)-1,+dateStr.substring(6,8));
  d.setDate(d.getDate()+n);
  return `${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`;
}

function openExtractModal(){
  const sel=getSelectedLines();const n=sel.length;
  if(n!==0&&n!==2)return;
  const has2=(n===2);
  // 2行選択時のみ表示する選択肢
  document.getElementById('lblSplitRange').style.display=has2?'':'none';
  document.getElementById('lblExtractRange').style.display=has2?'':'none';
  // デフォルトモードの設定
  const defaultMode=has2?'splitRange':'splitAll';
  const modeRadio=document.querySelector(`input[name="extractMode"][value="${defaultMode}"]`);
  if(modeRadio)modeRadio.checked=true;
  if(has2){
    const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
    if(!ts0||!ts1)return;
    const startTs=ts0<ts1?ts0:ts1;const endTs=ts0<ts1?ts1:ts0;
    document.getElementById('extractRange').textContent=
      (I18N['dash.extract_meeting_range']||'Range: {start} - {end}').replace('{start}',startTs).replace('{end}',endTs);
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
    document.querySelector('input[name="extractTarget"][value="new"]').checked=true;
    document.querySelector('input[name="extractNewType"][value="adhoc"]').checked=true;
    document.querySelectorAll('input[name="extractTarget"],input[name="extractNewType"]').forEach(r=>{
      r.onchange=_updateExtractControls;
    });
  }
  document.querySelectorAll('input[name="extractMode"]').forEach(r=>{r.onchange=_updateExtractMode;});
  _updateExtractMode();
  document.getElementById('extractModal').classList.add('open');
}
function _updateExtractMode(){
  const modeVal=(document.querySelector('input[name="extractMode"]:checked')||{}).value||'splitAll';
  const isSplitRange=modeVal==='splitRange';
  const isExtractRange=modeVal==='extractRange';
  document.getElementById('extractRangeInfo').style.display=(isSplitRange||isExtractRange)?'':'none';
  document.getElementById('extractTargetOpts').style.display=isExtractRange?'':'none';
  if(isExtractRange)_updateExtractControls();
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
  const modeVal=(document.querySelector('input[name="extractMode"]:checked')||{}).value||'splitAll';
  const file=document.getElementById('tf').textContent;
  if(modeVal==='splitAll'||modeVal==='splitRange'){
    const minEl=document.getElementById(modeVal==='splitAll'?'splitAllMin':'splitRangeMin');
    const minSilence=parseInt(minEl.value)||1;
    const body={file,min_silence_minutes:minSilence};
    if(modeVal==='splitRange'){
      const sel=getSelectedLines();
      const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
      body.start_ts=ts0<ts1?ts0:ts1;body.end_ts=ts0<ts1?ts1:ts0;
    }
    try{
      const r=await fetch('/api/transcript/split-by-silence',{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(body)});
      const d=await r.json();
      if(d.status==='ok'){
        deselectAll();closeExtractModal();
        loadFiles();loadT(curFile);loadR(curFile);
        if(d.message)alert(d.message);
      }else{alert(d.message||I18N['dash.extract_split_error']||'Failed');}
    }catch(e){alert(I18N['dash.extract_split_error']||'Failed');}
    return;
  }
  // extractRange モード（既存の切り出し処理）
  const sel=getSelectedLines();if(sel.length!==2)return;
  const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
  const startTs=ts0<ts1?ts0:ts1;const endTs=ts0<ts1?ts1:ts0;
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
      body:JSON.stringify({file,start_ts:startTs,end_ts:endTs,target,name})});
    const d=await r.json();
    if(d.status==='ok'){
      deselectAll();closeExtractModal();
      loadFiles();loadT(curFile);loadR(curFile);
      if(d.message)alert(d.message);
    }else{alert(d.message||I18N['dash.extract_meeting_error']||'Failed');}
  }catch(e){alert(I18N['dash.extract_meeting_error']||'Failed');}
}

/* --- Welcome / スキル更新 --- */
// 判定は /api/skill-status の state (missing|outdated|current) 一本に寄せる。
// 2つのモーダルで別々に判定を書くと、片方だけ直したときに黙ってずれる
async function _skillStatus(){
  try{return await(await fetch('/api/skill-status')).json();}catch(e){return null;}
}

function _skillRows(targets){
  return targets.map(t=>{
    const done=t.state==='current';
    return `<div class="wc-row">`
      +`<button onclick="installSkill('${escAttr(escJs(t.name))}',this)"${done?' disabled':''}>`
      +`${esc(done?I18N['welcome.skill_done']:I18N['welcome.skill'])}</button>`
      +`<span>${esc(t.name)}</span><code>${esc(t.path)}</code></div>`;
  }).join('');
}

async function installSkill(target,btn){
  btn.disabled=true;
  try{
    const r=await(await fetch('/api/skill-install',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({target})})).json();
    btn.textContent=r.status==='ok'?I18N['welcome.skill_done']:(r.message||r.status);
    if(r.status!=='ok')btn.disabled=false;
  }catch(e){btn.disabled=false;}
}

async function maybeShowWelcome(){
  let exists=true;
  try{exists=(await(await fetch('/api/config-exists')).json()).exists;}catch(e){return;}
  if(exists)return;
  const st=await _skillStatus();if(!st)return;
  // おすすめ設定は案内だけにする。初回に無断で値を書き換えると、あとから
  // 挙動の原因を追えなくなる
  // gcal だけは設定に Google Cloud 側の準備が要るので、手順書へ導く
  const recs=['rec_auto_analyze','rec_gcal','rec_asr','rec_workdir'].map(k=>{
    const doc=k==='rec_gcal'
      ?' — '+docLink('cfg.gcal_setup_url','cfg.gcal_setup_link'):'';
    return `<div class="wc-li">・${esc(I18N['welcome.'+k])}${doc}</div>`;
  }).join('');
  document.getElementById('welcomeBody').innerHTML=
    `<div style="font-size:12px;line-height:1.7">${esc(I18N['welcome.intro'])}</div>`
    +`<div class="wc-h">${esc(I18N['welcome.skill_where'])}</div>${_skillRows(st.targets)}`
    +`<div class="wc-h">${esc(I18N['welcome.recommend'])}</div>${recs}`;
  document.getElementById('welcomeModal').classList.add('open');
}

async function closeWelcome(){
  document.getElementById('welcomeModal').classList.remove('open');
  // 閉じた時点で config.yaml を作る。初回の印はこのファイルの不在なので、
  // 書かないと毎回出てしまう。専用のマーカーを増やさない代わりの処理
  try{
    const cfg=await(await fetch('/api/config')).json();
    await fetch('/api/config',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
  }catch(e){}
}
async function openCfgFromWelcome(){await closeWelcome();openCfg();}

let _outdatedSkills=[];

async function maybeShowSkillUpdate(){
  const st=await _skillStatus();if(!st||!st.bundled)return;
  const old=st.targets.filter(t=>t.state==='outdated');
  if(!old.length)return;
  try{
    const cfg=await(await fetch('/api/config')).json();
    if(cfg.skill_update_dismissed_version===st.bundled)return;
  }catch(e){}
  _outdatedSkills=old.map(t=>t.name);
  document.getElementById('skillUpdateBody').innerHTML=
    `<div style="font-size:12px;line-height:1.7">`
    +`${esc((I18N['skill_update.body']||'').replace('{bundled}',st.bundled))}</div>`
    +_skillRows(old);
  document.getElementById('skillUpdateModal').dataset.bundled=st.bundled;
  document.getElementById('skillUpdateModal').classList.add('open');
}

async function updateOutdatedSkills(btn){
  btn.disabled=true;
  for(const name of _outdatedSkills){
    try{await fetch('/api/skill-install',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify({target:name})});}catch(e){}
  }
  document.getElementById('skillUpdateModal').classList.remove('open');
}

async function dismissSkillUpdate(){
  const m=document.getElementById('skillUpdateModal');
  const version=m.dataset.bundled||'';
  m.classList.remove('open');
  // 同じ版では二度と出さない。毎回出ると必ず無視されるようになる
  try{
    const cfg=await(await fetch('/api/config')).json();
    cfg.skill_update_dismissed_version=version;
    await fetch('/api/config',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
  }catch(e){}
}

"""
