"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 左ペイン（日付・会議・会議名の変更・記録の会議名）"""
from __future__ import annotations

# nxFiles は /api/files の各ファイルを {name, display, meeting, dt, …file_info} に直したもの。
# meeting は会議名（名前なしは 'ad-hoc'、日次ファイルは null）。検索タブの中身は別モジュール（#nxSearch に描く）
_NEXT_JS_LIST = r"""
/* --- left pane: dates / meetings / rename --- */
let nxFiles=[];
let nxActive='';
let nxFilesSig='';
let nxLoaded=false;
const nxRenameApi='/api/transcript/rename-meeting';
function nxEsc(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function nxFmt(key,vars){
  let s=I18N[key]||'';
  Object.keys(vars).forEach(k=>{s=s.split('{'+k+'}').join(vars[k]);});
  return s;
}
function nxHashFile(){
  const h=location.hash.replace(/^#/,'');
  if(!h)return null;
  try{return decodeURIComponent(h);}catch(e){return h;}
}
function nxSetHash(f){
  const nh=f?'#'+encodeURIComponent(f):'';
  if((location.hash||'')===nh)return;
  history.replaceState(null,'',nh||location.pathname+location.search);
}
function nxFileOf(name,info){
  return {...info,name,display:info.label||name,meeting:info.meeting_group??null,dt:info.dt||''};
}
function nxDayOf(dt){return dt.slice(0,8);}
function nxFmtDay(dt){return dt.slice(0,4)+'-'+dt.slice(4,6)+'-'+dt.slice(6,8);}
function nxFmtDt(dt){return nxFmtDay(dt)+(dt.length>=12?' '+dt.slice(8,10)+':'+dt.slice(10,12):'');}
function nxFmtTime(dt){return dt.slice(8,10)+':'+dt.slice(10,12);}
function nxIsDaily(f){return f.meeting===null;}
function nxByNewest(a,b){return b.dt.localeCompare(a.dt)||b.name.localeCompare(a.name);}
/* 会議名ごとにまとめる。名前なし（ad-hoc）と日次ファイルは含めない。sort: 'new'（最新の回が新しい順）| 'abc'（あいうえお順） */
function nxMeetingGroups(files,sort){
  const m=new Map();
  files.filter(f=>f.meeting&&f.meeting!=='ad-hoc').sort(nxByNewest).forEach(f=>{
    if(!m.has(f.meeting))m.set(f.meeting,[]);
    m.get(f.meeting).push(f);
  });
  const keys=[...m.keys()];
  if(sort==='abc')keys.sort((a,b)=>a.localeCompare(b,'ja'));
  return new Map(keys.map(k=>[k,m.get(k)]));
}
function nxBase(path){return (path||'').split(/[\\/]/).pop();}
function nxIsLive(f){return nxState.session?nxBase(nxState.session)===f.name:f.name===nxActive;}
function nxPills(f){
  let s='';
  if(nxIsLive(f))s+='<span class="pill live">'+nxEsc(I18N['nx.live'])+'</span>';
  if(f.has_summary)s+='<span class="pill sum">'+nxEsc(I18N['nx.pill_summary'])+'</span>';
  if(f.has_advice||f.has_analysis)s+='<span class="pill ai">'+nxEsc(I18N['nx.pill_ai'])+'</span>';
  return s;
}
function nxYmd(d){return String(d.getFullYear())+String(d.getMonth()+1).padStart(2,'0')+String(d.getDate()).padStart(2,'0');}
function nxToday(offset){const d=new Date();d.setDate(d.getDate()+offset);return nxYmd(d);}
function nxItemHtml(f,title,sub){
  return '<div class="item'+(f.name===nxState.cur?' act':'')+'" data-f="'+nxEsc(f.name)+'" title="'+nxEsc(f.name)+'">'
    +'<div class="t">'+title+'</div><div class="s">'+sub+nxPills(f)+'</div></div>';
}
function nxDateItem(f){
  if(nxIsDaily(f))return nxItemHtml(f,'🗒 '+nxEsc(I18N[nxDayOf(f.dt)===nxToday(0)?'nx.today_memo':'nx.day_memo']),nxEsc(nxFmtDay(f.dt)));
  return nxItemHtml(f,nxEsc(nxFmtTime(f.dt))+' '+nxEsc(f.meeting==='ad-hoc'?I18N['nx.no_name']:f.meeting),nxEsc(nxFmtDt(f.dt)));
}
function nxDateHtml(){
  if(!nxFiles.length)return '<div class="empty">'+nxEsc(I18N['nx.dates_empty'])+'</div>';
  const days=new Map();
  nxFiles.forEach(f=>{const d=nxDayOf(f.dt);if(!days.has(d))days.set(d,[]);days.get(d).push(f);});
  let html='';
  [...days.keys()].sort().reverse().forEach(d=>{
    const note=d===nxToday(0)?I18N['nx.day_today']:d===nxToday(-1)?I18N['nx.day_yesterday']:'';
    html+='<div class="grp">'+nxEsc(nxFmtDay(d))+nxEsc(note)+'</div>';
    // 日次ファイル（メモ）を先頭に、会議は新しい順
    html+=days.get(d).sort((a,b)=>nxIsDaily(b)-nxIsDaily(a)||nxByNewest(a,b)).map(nxDateItem).join('');
  });
  return html;
}
function nxMeetingTabHtml(){
  const sort=nxStoreGet('nxMtgSort')==='abc'?'abc':'new';
  const groups=nxMeetingGroups(nxFiles,sort);
  const g=nxState.group;
  if(g&&groups.has(g)){
    return '<div class="ghead"><button class="lbtn sm" data-act="back">'+nxEsc(I18N['nx.back_to_list'])+'</button><b>'+nxEsc(g)+'</b>'
      +'<button class="lbtn sm" data-act="rename-group" data-g="'+nxEsc(g)+'" title="'+nxEsc(I18N['nx.rename_group_title'])+'">✏</button>'
      +'<button class="lbtn sm" data-act="cfg" data-g="'+nxEsc(g)+'" title="'+nxEsc(I18N['nx.meeting_settings'])+'">⚙</button></div>'
      +groups.get(g).map(f=>nxItemHtml(f,nxEsc(nxFmtDt(f.dt)),'')).join('');
  }
  if(!groups.size)return '<div class="empty">'+nxEsc(I18N['nx.meetings_empty'])+'</div>';
  return '<div class="sortbar"><span>'+nxEsc(I18N['nx.by_meeting'])+'</span><button class="lbtn sm" data-act="sort">'
    +nxEsc(I18N[sort==='abc'?'nx.sort_abc':'nx.sort_new'])+' ⇅</button></div>'
    +'<button class="lbtn sm mc-all" data-act="cfg">'+nxEsc(I18N['nx.mc_open_all'])+'</button>'
    +[...groups].map(([n,fs])=>'<div class="item" data-g="'+nxEsc(n)+'"><div class="t">'+nxEsc(n)
      +'<span class="cnt">'+nxEsc(nxFmt('nx.times',{n:fs.length}))+'</span></div>'
      +'<div class="s">'+nxEsc(nxFmt('nx.latest',{d:nxFmtDt(fs[0].dt)}))+'</div>'
      +'<span class="acts"><button class="gear" data-act="rename-group" data-g="'+nxEsc(n)+'" title="'+nxEsc(I18N['nx.rename_group_title'])+'">✏</button>'
      +'<button class="gear" data-act="cfg" data-g="'+nxEsc(n)+'" title="'+nxEsc(I18N['nx.meeting_settings'])+'">⚙</button></span></div>').join('');
}
function nxRenderLeft(){
  const tab=nxState.ltab||'date';
  nxEl('nxLtabs').querySelectorAll('button').forEach(b=>b.classList.toggle('act',b.dataset.lt===tab));
  nxEl('nxSearch').style.display=tab==='search'?'':'none';
  const list=nxEl('nxList');
  list.style.display=tab==='search'?'none':'';
  if(tab!=='search'&&nxLoaded)list.innerHTML=tab==='date'?nxDateHtml():nxMeetingTabHtml();
  const f=nxFiles.find(x=>x.name===nxState.cur);
  nxEl('nxFileTitle').textContent=f?f.display:nxState.cur||'';
  nxEl('nxMeetingNameBtn').style.display=f&&!nxIsDaily(f)?'':'none';
}
/* ヘッダの状態表示: 記録中でないファイルを見ているときは、押すと記録中のファイルへ戻る（現行の ★）。
   その日まだ何も話していなくてファイルが無くても開ける（話し始めると、そこに文字が出る）。
   ヘッダは会議中に毎秒描き直して className を作り直すので、印は data 属性に置く */
function nxRenderGoLive(){
  const st=nxEl('nxStatus'),go=!!nxActive&&nxState.cur!==nxActive;
  st.dataset.go=go?'1':'';
  st.title=go?I18N['nx.status_go_title']:'';
  st.tabIndex=go?0:-1;
}
function nxGoLive(){
  if(nxEl('nxStatus').dataset.go==='1')nxOpenLive();
}
function nxOpenLive(){
  if(!nxActive||nxState.cur===nxActive)return;
  if(nxState.ltab==='search')nxState.ltab='date';
  nxOpenFile(nxActive);
}
function nxSetTab(tab){nxState.ltab=tab;nxState.group=null;nxRenderLeft();}
function nxOpenFile(name){
  nxState.cur=name;
  nxSetHash(name);
  nxRenderAll();
}
/* 開くファイルを決める: いま開いているものが残っていればそのまま、無ければ URL ハッシュ、記録中のファイル、先頭の順。
   記録中のファイルは、まだできていなくても開いたままにする */
function nxPickCur(){
  const has=n=>n&&(n===nxActive||nxFiles.some(f=>f.name===n));
  if(has(nxState.cur))return;
  const hf=nxHashFile();
  nxState.cur=has(hf)?hf:has(nxActive)?nxActive:nxFiles.length?nxFiles[0].name:'';
}
async function nxLoadFiles(){
  try{
    const d=await nxApi('/api/files'),info=d.file_info||{};
    nxFiles=(d.files||[]).map(n=>nxFileOf(n,info[n]||{}));
    nxActive=d.active||'';
    const before=nxState.cur,sig=JSON.stringify([nxFiles,nxActive]);
    nxPickCur();
    const changed=sig!==nxFilesSig||before!==nxState.cur||!nxLoaded;
    nxFilesSig=sig;nxLoaded=true;
    if(changed)nxRenderAll();
  }catch(e){}
}

/* --- rename: 会議全体 / この記録 --- */
function nxModal(id,show){nxEl(id).classList.toggle('show',show);}
function nxOpenRenameGroup(name){
  const cnt=(nxMeetingGroups(nxFiles).get(name)||[]).length;
  nxEl('nxRgName').value=name;
  nxEl('nxRgName').dataset.old=name;
  nxEl('nxRgHint').textContent=nxFmt('nx.rename_group_hint',{n:cnt});
  nxModal('nxRgModal',true);
  nxEl('nxRgName').focus();
}
async function nxRenameGroup(name,newName){
  newName=newName.trim();
  if(!newName||newName===name)return;
  let ok=0;
  for(const f of nxMeetingGroups(nxFiles).get(name)||[]){
    try{const d=await nxApi(nxRenameApi,{file:f.name,name:newName});if(d.status==='ok')ok++;}catch(e){}
  }
  if(!ok){nxToast(I18N['nx.rename_failed']);return;}
  nxState.group=newName;
  await nxLoadFiles();
  nxToast(nxFmt('nx.renamed_toast',{name:newName}));
}
function nxOpenRecordName(){
  const f=nxFiles.find(x=>x.name===nxState.cur);
  if(!f||nxIsDaily(f))return;
  const names=[...nxMeetingGroups(nxFiles).keys()].sort((a,b)=>a.localeCompare(b,'ja'));
  const cur=f.meeting==='ad-hoc'?I18N['nx.no_name']:f.meeting;
  nxEl('nxRmSummary').textContent=nxFmt('nx.rec_summary',{d:nxFmtDt(f.dt),n:cur});
  const sel=nxEl('nxRmSel');
  sel.innerHTML=names.map(n=>'<option value="'+nxEsc(n)+'"'+(n===f.meeting?' selected':'')+'>'+nxEsc(n)+'</option>').join('');
  nxEl('nxRmName').value='';
  const mode=names.includes(f.meeting)?'existing':'new';
  nxEl('nxRmModal').querySelectorAll('input[name=nxRm]').forEach(r=>{r.checked=r.value===mode;});
  nxModal('nxRmModal',true);
}
async function nxRenameRecord(file,name){
  try{
    const d=await nxApi(nxRenameApi,{file,name});
    if(d.status!=='ok'){nxToast(d.message||I18N['nx.rename_failed']);return;}
    await nxLoadFiles();
    nxOpenFile(d.new_file||file);
    nxToast(nxFmt('nx.renamed_toast',{name:name||I18N['nx.no_name']}));
  }catch(e){nxToast(I18N['nx.rename_failed']);}
}
function nxApplyRecordName(){
  const existing=nxEl('nxRmModal').querySelector('input[name=nxRm]:checked');
  const name=existing&&existing.value==='existing'?nxEl('nxRmSel').value:nxEl('nxRmName').value.trim();
  nxModal('nxRmModal',false);
  nxRenameRecord(nxState.cur,name);
}

function nxOnListClick(e){
  const act=e.target.closest('[data-act]');
  if(act){
    e.stopPropagation();
    const g=act.dataset.g,a=act.dataset.act;
    if(a==='back'){nxState.group=null;nxRenderLeft();}
    else if(a==='sort'){nxStoreSet('nxMtgSort',nxStoreGet('nxMtgSort')==='abc'?'new':'abc');nxRenderLeft();}
    else if(a==='rename-group')nxOpenRenameGroup(g);
    else if(a==='cfg')nxOpenMeetingSettings(g);
    return;
  }
  const it=e.target.closest('[data-f],[data-g]');
  if(!it)return;
  if(it.dataset.f)nxOpenFile(it.dataset.f);
  else{nxState.group=it.dataset.g;nxRenderLeft();}
}
function nxListInit(){
  nxRenderers.push(nxRenderLeft,nxRenderGoLive);
  nxEl('nxStatus').addEventListener('click',nxGoLive);
  nxEl('nxStatus').addEventListener('keydown',e=>{if(e.key==='Enter')nxGoLive();});
  nxEl('nxLtabs').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>nxSetTab(b.dataset.lt)));
  nxEl('nxList').addEventListener('click',nxOnListClick);
  nxEl('nxMeetingNameBtn').addEventListener('click',nxOpenRecordName);
  nxEl('nxRgCancel').addEventListener('click',()=>nxModal('nxRgModal',false));
  nxEl('nxRgOk').addEventListener('click',()=>{
    const old=nxEl('nxRgName').dataset.old;
    nxModal('nxRgModal',false);
    nxRenameGroup(old,nxEl('nxRgName').value);
  });
  nxEl('nxRmCancel').addEventListener('click',()=>nxModal('nxRmModal',false));
  nxEl('nxRmOk').addEventListener('click',nxApplyRecordName);
  const pick=mode=>()=>nxEl('nxRmModal').querySelectorAll('input[name=nxRm]').forEach(r=>{r.checked=r.value===mode;});
  nxEl('nxRmName').addEventListener('focus',pick('new'));
  nxEl('nxRmSel').addEventListener('focus',pick('existing'));
  nxEl('nxRmSel').addEventListener('change',pick('existing'));
  /* 会議が始まったら会議のファイルへ、終わったら日次のファイルへ移る。デーモンは録音先を切り替えてから
     session ファイルを更新するので、ここで読み直した active は切り替え後のもの */
  nxOn('session',async d=>{const started=!nxState.session&&!!d.content;nxState.session=d.content||null;
    if(started){nxState.rtab='ai';nxState.right=true;}  // 会議が始まったら AI のアドバイスを前に出す（ページを開き直しては切り替えない）
    nxRenderLeft();await nxLoadFiles();nxOpenLive();});
  setInterval(nxLoadFiles,10000);
  nxLoadFiles();
}
nxListInit();
"""
