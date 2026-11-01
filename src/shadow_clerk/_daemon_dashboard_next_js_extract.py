"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 会議として切り出す・沈黙で分ける・🗑（削除・日次ファイルに戻す）"""
from __future__ import annotations

# 切り出しモーダルは nxEx（状態）から #nxExBody を描き直す。名前の入力中は描き直さない（フォーカスを失うため）。
# 作ったファイル名は split-by-silence の files / extract-meeting の file（付け足しなら付け足し先）で受け取る
_NEXT_JS_EXTRACT = r"""
/* --- extract: 会議として切り出す / 沈黙で分ける --- */
const nxExGaps=[1,2,3,5,10,15,20,30];
const nxExMaxGapSec=60,nxExConfirmSec=180,nxExEndSec=180;
let nxEx=null;
let nxExCal=[];
/* server の split-by-silence と同じ判定（秒単位）: minSilence 分以上の沈黙のあと（とファイル先頭）が開始候補 →
   候補中に 1 分を超える間隔で失格 → 候補開始から 3 分続けば会議 → 3 分以上の沈黙で終了 → 最後が候補のままなら捨てる */
function nxSplitSegments(lines,minSilenceMin){
  const out=[],minSec=minSilenceMin*60;
  let state='idle',from=0,start=0,last=null;
  lines.forEach((l,i)=>{
    const t=nxTsSec(l.ts),gap=last===null?Infinity:t-last;
    last=t;
    if(state==='candidate'&&gap<=nxExMaxGapSec){if(t-start>=nxExConfirmSec)state='active';return;}
    if(state==='active'&&gap<nxExEndSec)return;
    if(state==='active')out.push({from,to:i-1});
    state='idle';
    if(gap>=minSec){state='candidate';from=i;start=t;}
  });
  if(state==='active')out.push({from,to:lines.length-1});
  return out;
}
/* 選んだ範囲。server は時刻で範囲を取るので、端と同じ時刻の隣の行も含める */
function nxExRange(){
  const r=nxSelRange();
  if(!r)return null;
  let [a,b]=r;
  while(a>0&&nxLines[a-1].ts===nxLines[a].ts)a--;
  while(b<nxLines.length-1&&nxLines[b+1].ts===nxLines[b].ts)b++;
  return [a,b];
}
function nxExSegs(a,b){return nxSplitSegments(nxLines.slice(a,b+1),nxEx.gap).map(c=>({from:c.from+a,to:c.to+a}));}
function nxExMemo(){
  const f=nxTxInfo();
  return I18N[!f||!nxIsDaily(f)?'nx.this_record':nxDayOf(f.dt)===nxToday(0)?'nx.today_memo':'nx.day_memo'];
}
function nxDayShift(day,n){
  const d=new Date(+day.slice(0,4),+day.slice(4,6)-1,+day.slice(6,8));
  d.setDate(d.getDate()+n);
  return nxYmd(d);
}
function nxMtgName(f){return f.meeting==='ad-hoc'?I18N['nx.no_name']:f.meeting;}
/* 付け足し先: 開いているファイルの日付の前後 1 日の会議ファイル（現行 openExtractModal と同じ） */
function nxExTargets(){
  const f=nxTxInfo(),day=f?nxDayOf(f.dt):'';
  if(!day)return [];
  const near=new Set([day,nxDayShift(day,-1),nxDayShift(day,1)]);
  return nxFiles.filter(x=>!nxIsDaily(x)&&x.name!==nxTxFile&&near.has(nxDayOf(x.dt))).sort(nxByNewest);
}
/* 予定は時刻つき・名前つきのものだけ（終日の予定は日付だけで、どの区間にも当たってしまう） */
/* 時刻 t（ミリ秒）に進行中の、名前のある予定（会議開始モーダルも使う） */
function nxCalAtMs(t){
  return nxExCal.find(e=>e.summary&&String(e.start||'').includes('T')&&Date.parse(e.start)<=t&&t<Date.parse(e.end));
}
function nxExCalAt(ts){return nxCalAtMs(nxTsSec(ts)*1000);}
function nxExHmOf(iso){const d=new Date(iso);return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0');}
async function nxExLoadCal(){
  try{const d=await nxApi('/api/gcal-events');nxExCal=d&&d.enabled&&Array.isArray(d.events)?d.events:[];}catch(e){nxExCal=[];}
}
/* 範囲の先頭が予定の時間帯なら、同じ名前のいつもの会議（空白と _ は同じとみなす）か、予定の名前を入れておく */
function nxExApplyCal(){
  const r=nxExRange(),ev=r&&nxExCalAt(nxLines[r[0]].ts);
  if(!ev)return;
  const key=s=>String(s).trim().replace(/\s+/g,'_'),span=nxExHmOf(ev.start)+'〜'+nxExHmOf(ev.end),
    g=[...nxMeetingGroups(nxFiles).keys()].find(x=>key(x)===key(ev.summary));
  if(g)Object.assign(nxEx,{newType:'group',group:g,hint:nxFmt('nx.ex_cal_group',{name:ev.summary,span})});
  else Object.assign(nxEx,{newType:'newname',name:ev.summary,hint:nxFmt('nx.ex_cal_name',{name:ev.summary,span})});
}

/* --- render --- */
function nxExRadio(attr,val,act,disabled,inner){
  return '<div class="radio'+(disabled?' disabled':'')+(act?' act':'')+'" data-'+attr+'="'+val+'"><input type="radio"'
    +(act?' checked':'')+(disabled?' disabled':'')+'><div>'+inner+'</div></div>';
}
function nxExOpt(v,label,sel){return '<option value="'+nxEsc(v)+'"'+(sel?' selected':'')+'>'+nxEsc(label)+'</option>';}
function nxExGapSel(){
  return '<div class="inl"><select data-ex="gap">'+nxExGaps.map(v=>nxExOpt(v,v,v===nxEx.gap)).join('')+'</select>'
    +nxEsc(I18N['nx.ex_gap_suffix'])+'</div>';
}
function nxExSegsView(a,b){
  const segs=nxExSegs(a,b),rest=b-a+1-segs.reduce((n,c)=>n+c.to-c.from+1,0);
  if(segs.length<2)return {ok:false,html:'<div class="muted">'+nxEsc(I18N[segs.length?'nx.ex_cannot_one':'nx.ex_cannot'])+'</div>'};
  return {ok:true,html:'<div class="muted">'+nxEsc(nxFmt('nx.ex_will',{n:segs.length})+(rest?nxFmt('nx.ex_rest',{n:rest,memo:nxExMemo()}):''))+'</div>'
    +segs.map(c=>{
      const ev=nxExCalAt(nxLines[c.from].ts);
      return '<div class="seg-i">'+nxEsc(nxFmt('nx.ex_seg',{from:nxHm(nxLines[c.from]),to:nxHm(nxLines[c.to]),n:c.to-c.from+1}))
        +(ev?' <span class="muted">📅 '+nxEsc(nxFmt('nx.ex_cal',{name:ev.summary}))+'</span>':'')+'</div>';
    }).join('')};
}
function nxExTargetHtml(){
  const e=nxEx,groups=[...nxMeetingGroups(nxFiles,'abc').keys()],tg=nxExTargets();
  const nt=(v,inner)=>'<label class="opt"><input type="radio" name="nxExn" data-nt="'+v+'"'+(e.newType===v?' checked':'')+'> '+inner+'</label>';
  return '<div class="step">'+nxEsc(I18N['nx.ex_step2'])+'</div>'
    +nxExRadio('tgt','new',e.tgt==='new',false,'<b>'+nxEsc(I18N['nx.ex_tgt_new'])+'</b><div class="sub-opts">'
      +(groups.length?nt('group',nxEsc(I18N['nx.ex_nt_group'])+' <select data-ex="group">'+groups.map(g=>nxExOpt(g,g,g===e.group)).join('')+'</select>'):'')
      +(e.hint?'<div class="hint">'+nxEsc(e.hint)+'</div>':'')
      +nt('newname',nxEsc(I18N['nx.ex_nt_newname'])+' <input data-ex="name" value="'+nxEsc(e.name)+'" placeholder="'+nxEsc(I18N['nx.ex_name_ph'])+'">')
      +nt('adhoc',nxEsc(I18N['nx.ex_nt_adhoc']))+'</div>')
    +nxExRadio('tgt','existing',e.tgt==='existing',!tg.length,'<b>'+nxEsc(I18N['nx.ex_tgt_existing'])+'</b>'
      +(tg.length?'<select data-ex="target">'+tg.map(f=>nxExOpt(f.name,nxFmtDt(f.dt)+' '+nxMtgName(f),f.name===e.target)).join('')+'</select>':'')
      +'<div class="hint">'+nxEsc(I18N['nx.ex_tgt_existing_hint'])+'</div>');
}
function nxRenderExtract(){
  const e=nxEx,r=nxExRange(),memo=nxExMemo();
  if(!r)e.mode='splitAll';
  const all=nxExSegsView(0,nxLines.length-1),rng=r?nxExSegsView(r[0],r[1]):{ok:false,html:''},ext=e.mode==='extractRange';
  const idx=r?Array.from({length:r[1]-r[0]+1},(_,k)=>r[0]+k):[];
  nxEl('nxExBody').innerHTML='<div class="step">'+nxEsc(I18N['nx.ex_step1'])+'</div>'
    +nxExRadio('mode','splitAll',e.mode==='splitAll',false,'<b>'+nxEsc(nxFmt('nx.ex_split_all',{memo}))+'</b>'+nxExGapSel()
      +'<div class="hint adv-only">'+nxEsc(I18N['nx.ex_rule'])+'</div><div class="segs">'+all.html+'</div>')
    +nxExRadio('mode','splitRange',e.mode==='splitRange',!r,'<b>'+nxEsc(I18N['nx.ex_split_range'])+'</b>'+nxExGapSel()
      +'<div class="segs">'+rng.html+'</div>')
    +nxExRadio('mode','extractRange',ext,!r,'<b>'+nxEsc(I18N['nx.ex_extract_range'])+'</b>'
      +(r?'<div class="muted">'+nxEsc(nxFmt('nx.ex_range',{from:nxHm(nxLines[r[0]]),to:nxHm(nxLines[r[1]]),n:idx.length}))+'</div>'
        +'<div class="preview">'+nxPreviewHtml(idx)+'</div>':''))
    +(ext?nxExTargetHtml():'')
    +'<div class="hint foot">'+nxEsc(ext?nxFmt('nx.ex_foot_extract',{memo}):I18N['nx.ex_foot_split'])+'</div>';
  const ok=nxEl('nxExOk');
  ok.textContent=I18N[ext?'nx.ex_create':'nx.ex_split'];
  ok.disabled=e.mode==='splitAll'?!all.ok:e.mode==='splitRange'?!rng.ok:false;
}
function nxExSet(patch){Object.assign(nxEx,patch);nxRenderExtract();}
async function nxOpenExtract(mode){
  if(!nxTxInfo())return;
  const tg=nxExTargets();
  nxEx={file:nxTxFile,mode,gap:1,tgt:'new',newType:'adhoc',group:'',name:'',target:tg.length?tg[0].name:'',hint:''};
  const groups=[...nxMeetingGroups(nxFiles,'abc').keys()];
  if(groups.length)nxEx.group=groups[0];
  await nxExLoadCal();
  nxExApplyCal();
  nxRenderExtract();
  nxModal('nxExModal',true);
}

/* --- run / toast / undo --- */
function nxExBody(){
  const e=nxEx,r=nxExRange(),ts=r?{start_ts:nxLines[r[0]].ts,end_ts:nxLines[r[1]].ts}:null;
  if(e.mode==='splitAll')return ['/api/transcript/split-by-silence',{file:e.file,min_silence_minutes:e.gap}];
  if(!ts)return null;
  if(e.mode==='splitRange')return ['/api/transcript/split-by-silence',{file:e.file,min_silence_minutes:e.gap,...ts}];
  const existing=e.tgt==='existing'&&e.target;
  return ['/api/transcript/extract-meeting',{file:e.file,...ts,target:existing?e.target:'new',
    name:existing?'':e.newType==='group'?e.group:e.newType==='newname'?e.name.trim():''}];
}
async function nxDoExtract(){
  const req=nxExBody(),src=nxEx.file,memo=nxExMemo(),fromDaily=nxIsDaily(nxTxInfo()||{meeting:''});
  nxModal('nxExModal',false);
  if(!req)return;
  const [path,body]=req;
  let d=null;
  try{d=await nxApi(path,body);}catch(e){}
  if(!d||d.status!=='ok'){nxToast((d&&d.message)||I18N['nx.ex_failed']);return;}
  nxClearSel();
  await nxLoadFiles();
  if(nxState.cur===src)nxLoadTranscript(src,true);
  const appended=body.target&&body.target!=='new'?d.file||body.target:null,
    created=appended?[]:(body.target?[d.file]:d.files||[]).filter(Boolean);
  const dst=appended||created[0],f=nxFiles.find(x=>x.name===dst);
  if(!dst){nxToast(d.message||I18N['nx.ex_done']);return;}
  const msg=created.length>1?nxFmt('nx.ex_done_split',{n:created.length})
    :nxFmt(appended?'nx.ex_done_append':'nx.ex_done_new',{name:f?nxMtgName(f):dst});
  const open=[I18N['nx.ex_open'],()=>nxOpenFile(dst)];
  // 元に戻す = 作った会議ファイルを merge-to-daily。付け足し（そのファイルごと戻ってしまう）と、日次でないファイルからの切り出しには出さない
  if(appended||!fromDaily)nxToast(msg,open);
  else nxToast(msg,[I18N['nx.ex_undo'],()=>nxExUndo(src,created,memo)],open);
}
async function nxExUndo(src,created,memo){
  let ok=true;
  for(const file of created){
    try{const d=await nxApi('/api/transcript/merge-to-daily',{file});if(d.status!=='ok')ok=false;}catch(e){ok=false;}
  }
  await nxLoadFiles();
  if(nxState.cur===src)nxLoadTranscript(src,true);
  else if(nxFiles.some(f=>f.name===src))nxOpenFile(src);
  nxToast(ok?nxFmt('nx.ex_undone',{memo}):I18N['nx.ex_undo_failed']);
}

/* --- 入力（#nxExBody に委ねる）。select・入力欄のクリックでは描き直さない（開いた一覧が閉じるため） --- */
function nxExMark(attr,val){
  nxEl('nxExBody').querySelectorAll('[data-'+attr+']').forEach(r=>{
    const on=r.dataset[attr]===val;
    if(r.classList.contains('radio'))r.classList.toggle('act',on);
    const i=r.matches('input')?r:r.querySelector('input[type=radio]');
    if(i)i.checked=on;
  });
}
function nxExPickNt(v){nxEx.newType=v;nxEx.tgt='new';nxExMark('nt',v);nxExMark('tgt','new');}
function nxOnExClick(ev){
  const t=ev.target,nt=t.closest('[data-nt]');
  if(nt){nxEx.newType=nt.dataset.nt;if(nxEx.tgt!=='new')nxExSet({tgt:'new'});return;}
  if(t.closest('select,input:not([type=radio]),label.opt'))return;
  const r=t.closest('[data-mode],[data-tgt]');
  if(!r||r.classList.contains('disabled'))return;
  if(r.dataset.mode)nxExSet({mode:r.dataset.mode});else nxExSet({tgt:r.dataset.tgt});
}
function nxOnExChange(ev){
  const t=ev.target,k=t.dataset.ex;
  if(k==='gap'){
    const r=t.closest('[data-mode]');
    nxExSet({gap:+t.value,...(r&&!r.classList.contains('disabled')?{mode:r.dataset.mode}:{})});
  }else if(k==='group')nxExSet({group:t.value,newType:'group',tgt:'new'});
  else if(k==='target')nxExSet({target:t.value,tgt:'existing'});
}
function nxOnExInput(ev){if(ev.target.dataset.ex==='name'){nxEx.name=ev.target.value;nxExPickNt('newname');}}
/* 入力欄・会議名の一覧にフォーカスしたら、その選択肢を選ぶ（描き直さない） */
function nxOnExFocus(ev){const k=ev.target.dataset&&ev.target.dataset.ex;if(k==='name'||k==='group')nxExPickNt(k==='name'?'newname':'group');}

/* --- 🗑 日次ファイルに戻す / 完全に削除（現行 openFileDelModal と同じ選択肢。日次ファイルは削除だけ） --- */
let nxFd=null;
function nxRenderFileDelBtn(){
  const f=nxFiles.find(x=>x.name===nxState.cur);
  nxEl('nxFileDelBtn').style.display=f?'':'none';
}
function nxRenderFileDel(){
  const d=nxFd,r=(m,inner)=>nxExRadio('fd',m,d.mode===m,false,inner);
  nxEl('nxFdBody').innerHTML='<div class="muted">'+nxEsc(d.label)+'</div>'
    +(d.daily?'':r('merge','<b>'+nxEsc(I18N['nx.fd_merge'])+'</b><div class="hint">'+nxEsc(nxFmt('nx.fd_merge_hint',{d:nxFmtDay(d.dt)}))+'</div>'))
    +r('delete','<b>'+nxEsc(I18N['nx.fd_delete'])+'</b><div class="hint">'+nxEsc(I18N['nx.fd_delete_hint'])+'</div>'
      +(d.mode==='delete'?'<div class="preview">'+d.files.map(n=>'<div>'+nxEsc(n)+'</div>').join('')+'</div>':''));
  const ok=nxEl('nxFdOk');
  ok.textContent=I18N[d.mode==='merge'?'nx.fd_merge_ok':'nx.fd_delete_ok'];
  ok.className='cta'+(d.mode==='delete'?' danger':'');
}
function nxFdSet(mode){nxFd.mode=mode;nxRenderFileDel();}
function nxOpenFileDel(){
  const f=nxFiles.find(x=>x.name===nxState.cur);
  if(!f)return;
  const daily=nxIsDaily(f);
  nxFd={file:f.name,dt:f.dt,daily,mode:daily?'delete':'merge',files:[f.name,...(f.related||[])],
    label:daily?nxFmtDay(f.dt)+' '+I18N['nx.day_memo']:nxFmtDt(f.dt)+' '+nxMtgName(f)};
  nxRenderFileDel();
  nxModal('nxFdModal',true);
}
async function nxDoFileDel(){
  const {file,dt,mode}=nxFd,merge=mode==='merge';
  nxModal('nxFdModal',false);
  let d=null;
  try{d=await nxApi(merge?'/api/transcript/merge-to-daily':'/api/transcript/delete-file',{file});}catch(e){}
  if(!d||d.status!=='ok'){nxToast(I18N[merge?'nx.fd_merge_failed':'nx.fd_delete_failed']);return;}
  await nxLoadFiles();
  const daily=nxFiles.find(f=>nxIsDaily(f)&&nxDayOf(f.dt)===nxDayOf(dt));
  if(merge&&daily)nxOpenFile(daily.name);
  nxToast(I18N[merge?'nx.fd_merged':'nx.fd_deleted']);
}

function nxExtractInit(){
  nxRenderers.push(nxRenderFileDelBtn);
  const b=nxEl('nxExBody');
  b.addEventListener('click',nxOnExClick);
  b.addEventListener('change',nxOnExChange);
  b.addEventListener('input',nxOnExInput);
  b.addEventListener('focusin',nxOnExFocus);
  nxEl('nxExCancel').addEventListener('click',()=>nxModal('nxExModal',false));
  nxEl('nxExOk').addEventListener('click',nxDoExtract);
  nxEl('nxFileDelBtn').addEventListener('click',nxOpenFileDel);
  nxEl('nxFdBody').addEventListener('click',ev=>{const r=ev.target.closest('[data-fd]');if(r&&!nxFd.daily)nxFdSet(r.dataset.fd);});
  nxEl('nxFdCancel').addEventListener('click',()=>nxModal('nxFdModal',false));
  nxEl('nxFdOk').addEventListener('click',nxDoFileDel);
}
nxExtractInit();
"""
