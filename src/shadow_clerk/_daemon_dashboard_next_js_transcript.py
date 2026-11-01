"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 中央の文字起こし（読み込み・SSE 追記・翻訳列・まとまり・行の選択と操作）"""
from __future__ import annotations

# nxLines は解析できた行だけ（{ts, speaker, cls, text, raw, tr?}）。「--- meeting start ---」などの行は
# nxMarks に {at: 次の行の index, text} で持ち、行の index（= nxSel・nxSelRange の値）をずらさない。
# 翻訳は現行と同じくタイムスタンプ（＋話した人）で行に付ける
_NEXT_JS_TRANSCRIPT = r"""
/* --- transcript: load / SSE / translation / chunks --- */
let nxLines=[];
let nxMarks=[];
let nxSel=new Set();
let nxAnchor=null;
let nxMenu=null;
let nxTxFile=null;
let nxTxLoading=false;
let nxTxGen=0;
let nxTrFile='';
let nxTrMap=new Map();
let nxTrRows=[];
let nxRowsDrift=false;
let nxTrBusy=false;
let nxTrTarget='';
let nxInterim=null;
let nxDelRestore=null;
let nxProv={labels:{},lines:{}};
const nxLineRe=/^\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]\s\[([^\]]+)\]\s(.*)$/;
nxState.view='T';
nxState.gapMin=10;
function nxParseLine(raw){
  const m=nxLineRe.exec(raw);
  if(!m)return null;
  const sp=m[2];
  return {ts:m[1],speaker:sp,cls:sp==='自分'||sp===I18N['speaker.mic']?'me':sp==='Claude'?'claude':'other',text:m[3],raw};
}
/* Windows の transcript は CRLF なので行末の \r を落とす */
function nxSplitDiff(text){return String(text||'').split('\n').map(l=>l.replace(/\r$/,'')).filter(l=>l.trim());}
function nxAddLines(rows){
  rows.forEach(raw=>{const l=nxParseLine(raw);if(l)nxLines.push(l);else nxMarks.push({at:nxLines.length,text:raw});});
}
function nxTrKey(l){return l.ts+'\t'+l.speaker;}
/* nxTrRows は翻訳ファイルの全行（見出し・空行も）の nxTrKey。行でない行は null。検索結果の行番号→行の対応に使う */
function nxAddTr(rows){
  rows.forEach(raw=>{
    const l=nxParseLine(raw);
    nxTrRows.push(l?nxTrKey(l):null);
    if(!l)return;
    const k=nxTrKey(l);
    if(!nxTrMap.has(k))nxTrMap.set(k,[]);
    nxTrMap.get(k).push(l.text);
  });
}
/* 同じ時刻・同じ人の行が複数あれば、翻訳も出てきた順に当てる */
function nxAttachTr(){
  const seen=new Map();
  nxLines.forEach(l=>{
    const k=nxTrKey(l),n=seen.get(k)||0,t=(nxTrMap.get(k)||[])[n];
    seen.set(k,n+1);
    if(t===undefined)delete l.tr;else l.tr=t;
  });
}
function nxTsSec(ts){return Date.parse(ts.replace(' ','T'))/1000;}
function nxHm(l){return l.ts.slice(11,16);}
/* 次の行との差が gapMin 分以上なら区切る */
function nxFindChunks(lines,gapMin){
  const out=[];let from=0;
  lines.forEach((l,i)=>{
    const n=lines[i+1];
    if(!n||nxTsSec(n.ts)-nxTsSec(l.ts)>=gapMin*60){out.push({from,to:i});from=i+1;}
  });
  return out;
}
function nxTxInfo(){return nxFiles.find(f=>f.name===nxTxFile);}
function nxChunks(){const f=nxTxInfo();return f&&nxIsDaily(f)?nxFindChunks(nxLines,nxState.gapMin):[];}
/* translate_start / translate_regenerate に渡す「日付[@会議名]」（現行 _curFileArg と同じ） */
function nxFileArg(name){return (name||'').replace(/^transcript-/,'').replace(/\.txt$/,'');}
/* 会議中の仮登録は行単位 → ラベル単位の順に当てる（現行 spSpan と同じ） */
function nxWho(l){
  const sp=l.speaker,o=nxProv.lines[l.ts+'\t'+sp]??sp,pv=nxProv.labels[o]||o;
  if(pv!==sp)return pv;
  return sp==='自分'?I18N['speaker.mic']:sp==='相手'?I18N['speaker.monitor']:sp;
}

/* --- render --- */
/* /api/translation の translating はどのファイルの翻訳かを問わないので、翻訳先のファイル
   （記録中のファイルか、このページが translate_start / translate_regenerate を送ったファイル）だけ「翻訳中」にする */
function nxTrIsBusy(){return nxTrBusy&&nxState.translating&&!!nxTxFile&&(nxTxFile===nxActive||nxTxFile===nxTrTarget);}
function nxTrCell(l,only){
  if(l.tr!==undefined)return '<span class="trn">'+nxEsc(l.tr)+'</span>';
  const note='<span class="muted notr">'+nxEsc(I18N[nxTrIsBusy()?'nx.tr_busy':'nx.no_tr'])+'</span>';
  return '<span class="trn">'+(only?nxEsc(l.text)+' ':'')+note+'</span>';
}
function nxLineHtml(l,i){
  const v=nxState.view,showTr=v==='TR'||v==='R',only=v==='R';
  return '<div class="ln'+(only?' ro':showTr?' tr':'')+(nxSel.has(i)?' sel':'')+'" data-i="'+i+'"><span class="cb"></span>'
    +'<span class="ts" title="'+nxEsc(l.ts)+'">'+nxEsc(l.ts.slice(11,19))+'</span>'
    +'<span class="who '+l.cls+'" title="'+nxEsc(nxWho(l))+'">'+nxEsc(nxWho(l))+'</span>'
    +(only?'':'<span class="txt">'+nxEsc(l.text)+'</span>')+(showTr?nxTrCell(l,only):'')
    +'<button class="more" data-more="'+i+'" title="'+nxEsc(I18N['nx.line_actions'])+'">⋯</button>'
    +(nxMenu===i?'<div class="lmenu"><div data-lm="copy">'+nxEsc(I18N['nx.copy_line'])+'</div>'
      +'<div data-lm="delete" class="danger">'+nxEsc(I18N['nx.delete_line'])+'</div></div>':'')
    +'</div>';
}
function nxMarksAt(i){return nxMarks.filter(m=>m.at===i).map(m=>'<div class="mk">'+nxEsc(m.text)+'</div>').join('');}
function nxRangeHtml(from,to){
  let h='';
  for(let i=from;i<=to;i++)h+=nxMarksAt(i)+nxLineHtml(nxLines[i],i);
  return h;
}
function nxChunkHead(c,ci){
  return '<div class="chunk"><span>💬</span><span class="ct">'
    +nxEsc(nxFmt('nx.chunk_title',{from:nxHm(nxLines[c.from]),to:nxHm(nxLines[c.to])}))+'</span>'
    +'<span class="muted">'+nxEsc(nxFmt('nx.chunk_count',{n:c.to-c.from+1}))+'</span><span class="spacer"></span>'
    +'<button class="lbtn" data-chunk="'+ci+'">'+nxEsc(I18N['nx.extract_chunk'])+'</button></div>';
}
/* 確定前の文字起こし（相手の声だけ）。選択できない薄い行として最後に出す */
function nxInterimHtml(){
  const it=nxInterim;
  if(!it)return '';
  const v=nxState.view,showTr=v==='TR'||v==='R',only=v==='R',who=nxWho({ts:'',speaker:it.speaker}),
    tr=it.tr!==undefined?nxEsc(it.tr):only?nxEsc(it.text):'';
  return '<div class="ln interim'+(only?' ro':showTr?' tr':'')+'"><span></span><span class="ts">…</span>'
    +'<span class="who other">'+nxEsc(who)+'</span>'+(only?'':'<span class="txt">'+nxEsc(it.text)+'</span>')
    +(showTr?'<span class="trn">'+tr+'</span>':'')+'<span></span></div>';
}
function nxTxHtml(chunks){
  if(nxTxLoading)return '';
  if(!nxLines.length&&!nxInterim)return '<div class="txempty"><div class="ic">🎧</div><h3>'+nxEsc(I18N['nx.tx_empty'])+'</h3></div>';
  const tail=nxMarksAt(nxLines.length)+nxInterimHtml();
  if(!nxLines.length)return tail;
  if(!chunks.length)return nxRangeHtml(0,nxLines.length-1)+tail;
  return chunks.map((c,ci)=>{
    const gap=ci?Math.round((nxTsSec(nxLines[c.from].ts)-nxTsSec(nxLines[chunks[ci-1].to].ts))/60):0;
    return (ci?'<div class="gap"><span>'+nxEsc(nxFmt('nx.chunk_gap',{n:gap}))+'</span></div>':'')
      +nxChunkHead(c,ci)+nxRangeHtml(c.from,c.to);
  }).join('')+tail;
}
/* 見出しの横に、transcript と翻訳をそのまま別タブで開くリンク（旧 UI のファイル名リンク） */
function nxRenderFileOpen(){
  const tx=nxFiles.some(x=>x.name===nxTxFile)?nxTxFile:'',tr=nxTrMap.size?nxTrFile:'',el=nxEl('nxFileOpen'),k=tx+'\t'+tr;
  if(el.dataset.k===k)return;
  el.dataset.k=k;el.innerHTML=nxOpenLink(tx)+nxOpenLink(tr,'nx.open_tr');
}
function nxRenderColHead(){
  const v=nxState.view,show=v==='TR'||v==='R',h=nxEl('nxColHead');
  h.className='colhead'+(show?' show':'')+(v==='R'?' ro':'');
  if(!show){h.innerHTML='';return;}
  const open=nxTrMap.size&&nxTrFile?'<a class="lbtn sm" href="/api/file?name='+encodeURIComponent(nxTrFile)
    +'" target="_blank" rel="noopener" title="'+nxEsc(nxTrFile)+'">'+nxEsc(I18N['nx.open'])+'</a>':'';
  h.innerHTML='<span></span><span>'+nxEsc(I18N['nx.col_time'])+'</span><span>'+nxEsc(I18N['nx.col_who'])+'</span>'
    +(v==='R'?'':'<span>'+nxEsc(I18N['nx.col_orig'])+'</span>')
    +'<span class="trh">'+nxEsc(I18N['nx.col_tr'])
    +'<button class="lbtn sm" data-act="tr-close" title="'+nxEsc(I18N['nx.tr_close_title'])+'">✕ '+nxEsc(I18N['nx.close'])+'</button>'
    +'<span class="spacer"></span>'
    +'<button class="lbtn sm" data-act="tr-regen" title="'+nxEsc(I18N['nx.tr_regen_btn_title'])+'">'+nxEsc(I18N['nx.regen'])+'</button>'
    +open+'</span>';
}
function nxRenderSuggest(chunks){
  const sg=nxEl('nxSuggest'),show=chunks.length>1&&nxStoreGet('nxSugHidden')!=='1';
  sg.style.display=show?'':'none';
  if(!show){sg.innerHTML='';return;}
  sg.classList.toggle('compact',nxState.view==='AI'||nxState.view==='CON');
  const n=chunks.length;
  sg.innerHTML='<span>💡</span><span class="sg-long">'+nxEsc(nxFmt('nx.sg_text',{n}))+'<br><span class="muted">'
    +nxEsc(I18N['nx.sg_tip'])+'</span></span><span class="sg-short">'+nxEsc(nxFmt('nx.sg_short',{n}))+'</span>'
    +'<span class="spacer"></span><button class="lbtn" data-act="split-all"><span class="sg-long">'+nxEsc(I18N['nx.split_all'])
    +'</span><span class="sg-short">'+nxEsc(I18N['nx.split_all_short'])+'</span></button>'
    +'<button class="sg-x" data-act="sg-close" title="'+nxEsc(I18N['nx.sg_close'])+'">✕</button>';
}
function nxRenderMuteBand(){
  const s=nxState,msgs=[];
  if(s.useMic&&s.muteMic)msgs.push(I18N['nx.mute_band_mic']);
  if(s.useMonitor&&s.muteMonitor)msgs.push(I18N['nx.mute_band_monitor']);
  const b=nxEl('nxMuteBand');
  b.textContent=msgs.join(' ');
  b.classList.toggle('show',msgs.length>0);
}
function nxAtBottom(){const tx=nxEl('nxTranscript');return tx.scrollTop+tx.clientHeight>=tx.scrollHeight-30;}
/* follow=true なら下端へ。そうでなければ今のスクロール位置を保つ */
function nxRenderTx(follow){
  const tx=nxEl('nxTranscript'),top=tx.scrollTop,chunks=nxChunks();
  tx.innerHTML=nxTxHtml(chunks);
  tx.scrollTop=follow?tx.scrollHeight:top;
  nxRenderColHead();nxRenderFileOpen();nxRenderSuggest(chunks);nxRenderSelBar();nxRenderMuteBand();
}
function nxRenderTranscript(){
  if((nxState.cur||'')!==nxTxFile)nxLoadTranscript(nxState.cur||'');
  else nxRenderTx(false);
}

/* --- load / SSE --- */
function nxTxReset(){
  nxLines=[];nxMarks=[];nxTrMap=new Map();nxTrRows=[];nxRowsDrift=false;nxTrFile='';nxTrBusy=false;nxInterim=null;nxProv={labels:{},lines:{}};
  nxSel=new Set();nxAnchor=null;nxMenu=null;
}
/* keep=true は同じファイルの読み直し（削除・話した人の変更のあと）。スクロール位置を保つ */
async function nxLoadTranscript(file,keep){
  const g=++nxTxGen;
  nxTxFile=file;
  if(!keep){nxTxReset();nxTxLoading=!!file;nxRenderTx(false);}
  if(!file)return;
  const q='?file='+encodeURIComponent(file),get=p=>nxApi(p+q).catch(()=>({}));
  const [t,r,p]=await Promise.all([get('/api/transcript'),get('/api/translation'),get('/api/speakers/provisional')]);
  if(g!==nxTxGen)return;
  nxTxReset();nxTxLoading=false;
  nxAddLines(t.lines||[]);nxAddTr(r.lines||[]);
  nxTrFile=r.file||'';nxTrBusy=!!r.translating&&!(r.lines||[]).length;
  if(p.status==='ok')nxProv={labels:p.labels||{},lines:p.lines||{}};
  nxAttachTr();
  nxRenderTx(!keep);
}
async function nxLoadProvisional(file){
  try{
    const p=await nxApi('/api/speakers/provisional?file='+encodeURIComponent(file));
    nxProv=p.status==='ok'?{labels:p.labels||{},lines:p.lines||{}}:{labels:{},lines:{}};
  }catch(e){}
  nxRenderTx(false);
}
function nxOnTranscriptSse(d){
  if(!nxTxFile||nxTxLoading||d.file!==nxTxFile)return;
  const follow=nxAtBottom();
  nxInterim=null;nxRowsDrift=true;nxAddLines(nxSplitDiff(d.diff));nxAttachTr();
  nxRenderTx(follow);
}
/* d.file は翻訳ファイル名（transcript-…-ja.txt）。開いているファイルの stem + '-' で照合する */
function nxOnTranslationSse(d){
  if(!nxTxFile||nxTxLoading||!String(d.file||'').startsWith(nxTxFile.replace(/\.txt$/,'-')))return;
  const follow=nxAtBottom();
  nxRowsDrift=true;nxAddTr(nxSplitDiff(d.diff));nxTrFile=d.file;nxTrBusy=false;nxAttachTr();
  nxRenderTx(follow);
}

/* --- selection / line actions --- */
function nxSelIdx(){return [...nxSel].sort((a,b)=>a-b);}
function nxSelRange(){const s=nxSelIdx();return s.length?[s[0],s[s.length-1]]:null;}
function nxRenderSelBar(){
  const idx=nxSelIdx().filter(i=>nxLines[i]);
  nxEl('nxSelBar').classList.toggle('show',idx.length>0);
  if(!idx.length)return;
  const a=idx[0],b=idx[idx.length-1];
  nxEl('nxSelCount').textContent=nxFmt('nx.sel_count',{n:idx.length});
  nxEl('nxSelRange').textContent=nxHm(nxLines[a])+'〜'+nxHm(nxLines[b])+(b-a+1===idx.length?'':I18N['nx.sel_sparse']);
}
function nxClearSel(){nxSel=new Set();nxAnchor=null;nxMenu=null;nxRenderTx(false);}
/* 切り出しモーダルは Task 4（nxOpenExtract）が持つ */
function nxExtract(mode){if(typeof nxOpenExtract==='function')nxOpenExtract(mode);}
function nxCopyLines(idx){
  const fail=()=>nxToast(I18N['nx.copy_failed']);
  try{
    navigator.clipboard.writeText(idx.map(i=>nxLines[i].raw).join('\n'))
      .then(()=>nxToast(nxFmt('nx.copied',{n:idx.length})),fail);
  }catch(e){fail();}
}
function nxOnTxClick(e){
  const lm=e.target.closest('[data-lm]');
  if(lm){
    const i=nxMenu;nxMenu=null;
    if(lm.dataset.lm==='copy'){nxRenderTx(false);nxCopyLines([i]);}
    else{nxDelRestore=nxSel;nxSel=new Set([i]);nxRenderTx(false);nxOpenDelete();}
    return;
  }
  const more=e.target.closest('[data-more]');
  if(more){const i=+more.dataset.more;nxMenu=nxMenu===i?null:i;nxRenderTx(false);return;}
  const ch=e.target.closest('[data-chunk]');
  if(ch){
    const c=nxChunks()[+ch.dataset.chunk];
    if(!c)return;
    nxSel=new Set();for(let k=c.from;k<=c.to;k++)nxSel.add(k);
    nxMenu=null;nxRenderTx(false);nxExtract('extractRange');
    return;
  }
  const ln=e.target.closest('.ln[data-i]');
  if(!ln||e.target.closest('.lmenu'))return;
  const i=+ln.dataset.i;
  if(e.shiftKey&&nxAnchor!==null){for(let k=Math.min(nxAnchor,i);k<=Math.max(nxAnchor,i);k++)nxSel.add(k);}
  else{if(nxSel.has(i))nxSel.delete(i);else nxSel.add(i);nxAnchor=i;}
  nxMenu=null;nxRenderTx(false);
}
function nxOnMainClick(e){
  const sa=e.target.closest('[data-sa]');
  if(sa){
    const a=sa.dataset.sa,idx=nxSelIdx();
    if(a==='clear')nxClearSel();
    else if(a==='copy')nxCopyLines(idx);
    else if(a==='speaker')nxOpenRelabel();
    else if(a==='delete'){nxDelRestore=null;nxOpenDelete();}
    else if(a==='extract')nxExtract('extractRange');
    return;
  }
  const act=e.target.closest('[data-act]');
  if(!act)return;
  const a=act.dataset.act;
  if(a==='tr-regen')nxRegenTranslation();
  else if(a==='tr-close')nxSetView('T');  // 表示を閉じるだけ。翻訳そのものは止めない
  else if(a==='split-all'){nxClearSel();nxExtract('splitAll');}
  else if(a==='sg-close'){nxStoreSet('nxSugHidden','1');nxRenderTx(false);nxToast(I18N['nx.sg_closed']);}
}

/* --- confirm (翻訳・議事録の作り直しで共用) --- */
let nxCfFn=null;
let nxCfNo=null;
/* onCancel はキャンセルで閉じたとき（OK のときは呼ばない） */
function nxConfirm({title,text,ok,onOk,onCancel}){
  nxEl('nxCfTitle').textContent=title;
  nxEl('nxCfText').textContent=text||'';
  nxEl('nxCfOk').textContent=ok;
  nxCfFn=onOk;nxCfNo=onCancel||null;
  nxModal('nxCfModal',true);
}
function nxRegenTranslation(){
  nxConfirm({title:I18N['nx.tr_regen_title'],text:I18N['nx.tr_regen_text'],ok:I18N['nx.regen_ok'],onOk:()=>{
    const arg=nxFileArg(nxTxFile);
    nxCmd('translate_regenerate'+(arg?' '+arg:''));
    nxTrMap=new Map();nxTrRows=[];nxRowsDrift=true;nxTrBusy=true;nxTrTarget=nxTxFile;nxAttachTr();
    nxState.translating=true;nxRenderHeader();nxRenderTx(false);
  }});
}

/* --- delete lines（現行 doBulkDel と同じ本文。翻訳の行はサーバーが一緒に消す） --- */
function nxPreviewHtml(idx){
  const row=i=>{const l=nxLines[i];return '<div><span class="muted">'+nxEsc(nxHm(l))+'</span> <b>'+nxEsc(nxWho(l))+'</b> '+nxEsc(l.text)+'</div>';};
  return idx.length<=3?idx.map(row).join('')
    :row(idx[0])+'<div class="dots">'+nxEsc(nxFmt('nx.dots',{n:idx.length-2}))+'</div>'+row(idx[idx.length-1]);
}
function nxOpenDelete(){
  const idx=nxSelIdx();
  if(!idx.length)return;
  nxEl('nxDelSummary').textContent=nxFmt('nx.del_summary',{n:idx.length});
  nxEl('nxDelPreview').innerHTML=nxPreviewHtml(idx);
  nxModal('nxDelModal',true);
}
async function nxDoDelete(){
  const idx=nxSelIdx(),file=nxTxFile;
  nxDelRestore=null;
  nxModal('nxDelModal',false);
  if(!idx.length)return;
  try{
    const d=await nxApi('/api/transcript/delete',{lines:idx.map(i=>nxLines[i].raw),file});
    if(d.status!=='ok'){nxToast(d.message||I18N['nx.del_failed']);return;}
    nxToast(nxFmt('nx.deleted',{n:idx.length}));
    nxLoadTranscript(file,true);
  }catch(e){nxToast(I18N['nx.del_failed']);}
}

/* --- relabel（現行 saveRelabel の「選んだ行だけ」「2 行の間を全部」と同じ本文。[Claude] の行は付け替えない）。
   「この話者の行を全部」は 👥 のモーダル（現行の話者モーダル）が受け持つ --- */
let nxRl={file:'',items:[],prov:false};
async function nxOpenRelabel(){
  const ls=nxSelIdx().map(i=>nxLines[i]).filter(l=>l&&l.speaker!=='Claude');
  nxRl={file:nxTxFile,items:ls.map(l=>({ts:l.ts,label:l.speaker})),prov:false};
  const n=ls.length;
  nxEl('nxSpkSummary').textContent=n?nxFmt(n===1?'nx.spk_summary_one':'nx.spk_summary',{n,who:nxWho(ls[0])}):'';
  nxEl('nxSpkInfo').textContent='';
  nxEl('nxSpkName').value='';
  nxEl('nxSpkOk').disabled=!n;
  nxEl('nxSpkScopeLinesText').textContent=I18N[n===1?'dash.relabel_scope_one':n===2?'dash.relabel_scope_two':'dash.relabel_scope_lines'];
  nxEl('nxSpkScopeRangeOpt').hidden=new Set(nxRl.items.map(i=>i.ts+'\u0000'+i.label)).size!==2;
  nxEl('nxSpkScopeLines').checked=true;nxEl('nxSpkScopeRange').checked=false;
  const g=nxEl('nxSpkGroup'),p=nxEl('nxSpkPerson');
  g.value='';g.hidden=true;g.dataset.touched='';p.checked=true;p.dataset.touched='';
  nxRlTarget();
  nxModal('nxSpkModal',true);
  let d=null;
  try{d=await nxApi('/api/speakers?file='+encodeURIComponent(nxRl.file));}catch(e){}
  if(!d||d.status!=='ok')return;
  nxRl.prov=!!d.provisional;
  const opts=vs=>(vs||[]).map(v=>'<option value="'+nxEsc(v)+'">').join('');
  nxEl('nxSpkList').innerHTML=opts(d.suggestions);
  nxEl('grpSuggest').innerHTML=opts(d.groups);
  nxEl('nxSpkInfo').textContent=nxRl.prov?I18N['dash.relabel_provisional_hint']
    :d.active?I18N['dash.speakers_active']:d.translating?I18N['dash.speakers_translating']:'';
  nxEl('nxSpkOk').disabled=!n||!nxRl.prov&&!!(d.active||d.translating);
}
/* 範囲は現行 updateRlTarget・サーバーの range_targets と同じ: 自分の行は、端のどちらかが自分の行のときだけ */
function nxRlTarget(){
  const {items}=nxRl;
  let text=I18N['dash.relabel_target_lines'].replace('{count}',items.length);
  if(nxEl('nxSpkScopeRange').checked){
    const [lo,hi]=items.map(i=>i.ts).sort(),self=items.some(i=>i.label==='自分');
    text=I18N['dash.relabel_target_range'].replace('{count}',
      nxLines.filter(l=>l.ts>=lo&&l.ts<=hi&&l.speaker!=='Claude'&&(self||l.speaker!=='自分')).length);
  }
  nxEl('nxSpkTarget').textContent=text;
}
async function nxSaveRelabel(){
  const name=nxEl('nxSpkName').value.trim(),{file,items,prov}=nxRl,g=nxEl('nxSpkGroup'),p=nxEl('nxSpkPerson'),e={name};
  if(!(name||prov)||!items.length)return;
  if(g.dataset.touched==='1'&&!p.checked)e.group=g.value.trim();
  if(p.dataset.touched==='1')e.person=!!p.checked;
  let d;
  try{d=await nxApi('/api/speakers/assign-lines',{file,lines:items,...e,...(nxEl('nxSpkScopeRange').checked?{scope:'range'}:{})});}
  catch(err){d=null;}
  if(!d||d.status!=='ok'){nxToast((d&&d.message)||I18N['nx.spk_failed']);return;}
  nxModal('nxSpkModal',false);
  nxClearSel();
  if(d.message)nxToast(d.message);
  if(d.provisional){nxLoadProvisional(file);return;}
  nxLoadTranscript(file,true);
  await loadSpeakerGroups();
  if(d.has_summary)nxAskRegenSummary(file);
}

/* 途中の文字起こし・翻訳はファイル名を持たない（現行と同じく届いたものを出す）。出すのは記録中のファイルを開いているときだけ */
function nxIsLiveOpen(){return !!nxTxFile&&!nxTxLoading&&nxTxFile===nxActive;}
function nxOnInterim(d,translated){
  if(!nxIsLiveOpen())return;
  const follow=nxAtBottom(),same=nxInterim&&nxInterim.text===d.text;
  nxInterim={speaker:d.speaker,text:d.text,...(translated?{tr:d.translated}:same&&nxInterim.tr!==undefined?{tr:nxInterim.tr}:{})};
  nxRenderTx(follow);
}
function nxTranscriptInit(){
  nxRenderers.push(nxRenderTranscript);
  nxOn('transcript',nxOnTranscriptSse);
  nxOn('translation',nxOnTranslationSse);
  nxOn('interim_transcript',d=>nxOnInterim(d,false));
  nxOn('interim_translation',d=>nxOnInterim(d,true));
  nxOn('interim_clear',()=>{if(nxInterim){nxInterim=null;nxRenderTx(false);}});
  nxOn('provisional_applied',d=>{if(d.message)nxToast(d.message);if(d.file===nxTxFile)nxLoadTranscript(nxTxFile,true);});
  nxEl('nxTranscript').addEventListener('click',nxOnTxClick);
  nxEl('nxMain').addEventListener('click',nxOnMainClick);
  nxEl('nxCfCancel').addEventListener('click',()=>{const f=nxCfNo;nxCfFn=nxCfNo=null;nxModal('nxCfModal',false);if(f)f();});
  nxEl('nxCfOk').addEventListener('click',()=>{const f=nxCfFn;nxCfFn=nxCfNo=null;nxModal('nxCfModal',false);if(f)f();});
  nxEl('nxDelCancel').addEventListener('click',()=>{
    nxModal('nxDelModal',false);
    if(nxDelRestore){nxSel=nxDelRestore;nxDelRestore=null;nxRenderTx(false);}
  });
  nxEl('nxDelOk').addEventListener('click',nxDoDelete);
  nxEl('nxSpkCancel').addEventListener('click',()=>nxModal('nxSpkModal',false));
  nxEl('nxSpkOk').addEventListener('click',nxSaveRelabel);
  nxEl('nxSpkScopeLines').addEventListener('change',nxRlTarget);
  nxEl('nxSpkScopeRange').addEventListener('change',nxRlTarget);
  /* 名前を入れたら、その人のグループ・個人区分を既定にする（現行 onRlNameInput と同じ。_applyNameDefaults は流用する現行の関数） */
  nxEl('nxSpkName').addEventListener('input',()=>_applyNameDefaults(nxEl('nxSpkName').value.trim(),nxEl('nxSpkGroup'),nxEl('nxSpkPerson'),'',true));
  nxEl('nxSpkPerson').addEventListener('change',()=>{const p=nxEl('nxSpkPerson');p.dataset.touched='1';nxEl('nxSpkGroup').hidden=p.checked;});
  nxEl('nxSpkGroup').addEventListener('input',()=>{nxEl('nxSpkGroup').dataset.touched='1';});
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&(nxSel.size||nxMenu!==null)&&!document.querySelector('.modal-bg.show,.modal-overlay.open'))nxClearSel();
  });
}
nxTranscriptInit();
"""
