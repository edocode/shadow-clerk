"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 右ペイン（議事録・AI のアドバイス）"""
from __future__ import annotations

# nxRt は開いているファイルの議事録・参加者・アドバイス・分析。ファイルが変わったら読み直す。
# AI アシスタントは daemon に 1 つだけ。どの transcript を見ているかは /api/status の console_transcript
# （走っている間だけ値がある）を正とし、console の SSE で状態が変わったら取り直す
_NEXT_JS_RIGHT = r"""
/* --- right pane: summary / AI advice --- */
nxState.right=true;nxState.left=true;nxState.bottom=false;nxState.rtab='sum';
const nxRtEmpty=()=>({file:null,loaded:false,sum:{file:'',content:'',html:''},att:[],adv:{file:'',html:''},ana:{file:'',html:''},
  sumGen:false,hasSum:false});
let nxRt=nxRtEmpty();
let nxRtGen=0;
let nxRtHtml='';
let nxAiBusy=false;
/* 本文中のファイル名をリンクにする（現行 FILE_REF_RE / _fileRefLink と同じ） */
const nxFileRefRe=/(?<![\w-])(?:(transcript|summary|analysis|advice)-(\d{8}(?:\d{4})?(?:@[^\s`'"|\/\\<>()（）「」、。,]+?)?)(?:-[a-z]{2})?\.(?:txt|md)|shot-\d{8}[^\s`'"|\/\\<>()（）「」、。,]*?\.png)/g;
function nxFileRefLink(m){
  const a=document.createElement('a');a.textContent=m[0];
  if(!m[1]){a.href='/api/screenshot?file='+encodeURIComponent(m[0])+'&transcript='+encodeURIComponent(nxState.cur||'');a.target='_blank';a.rel='noopener';return a;}
  // 翻訳 (transcript-…-en.txt) は元の transcript に寄せる
  const f=[m[1]==='transcript'&&m[0],'transcript-'+m[2]+'.txt'].find(c=>c&&nxFiles.some(x=>x.name===c));
  if(!f)return null;
  a.href='#'+encodeURIComponent(f);
  a.addEventListener('click',e=>{
    e.preventDefault();e.stopPropagation();
    if(m[1]!=='transcript')nxState.rtab=m[1]==='summary'?'sum':'ai';
    if(f!==nxState.cur)nxOpenFile(f);else nxRenderAll();
  });
  return a;
}
function nxLinkifyFiles(root){
  if(!root)return;
  const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),nodes=[];
  for(let n=w.nextNode();n;n=w.nextNode())if(!n.parentElement.closest('a')&&n.data.search(nxFileRefRe)>=0)nodes.push(n);
  nodes.forEach(n=>{
    const frag=document.createDocumentFragment();let last=0;
    for(const m of n.data.matchAll(nxFileRefRe)){
      const a=nxFileRefLink(m);if(!a)continue;
      frag.append(n.data.slice(last,m.index),a);last=m.index+m[0].length;
    }
    if(!last)return;
    frag.append(n.data.slice(last));n.replaceWith(frag);
  });
}

/* --- AI アシスタント（1 つだけ） --- */
function nxAssistantFor(){const s=nxState.status;return s&&s.console_running&&s.console_transcript||null;}
function nxFileLabel(name){const f=nxFiles.find(x=>x.name===name);return f?f.display:name;}
async function nxAiStart(){
  const cur=nxState.cur,prev=nxAssistantFor();
  if(!cur||nxAiBusy)return;
  nxAiBusy=true;nxRenderRight();
  try{
    const d=await nxApi('/api/console/start',{transcript:cur});
    if(d.status!=='ok')nxToast(I18N['dash.console_start_failed']);
    else if(prev&&prev!==cur)nxToast(nxFmt('nx.ai_switched',{name:nxFileLabel(prev)}));
  }catch(e){nxToast(I18N['dash.console_start_failed']);}
  nxAiBusy=false;
  await nxFetchStatus();
}
function nxAiStop(){
  nxConfirm({title:I18N['nx.ai_stop_title'],text:I18N['nx.ai_stop_text'],ok:I18N['nx.ai_stop'],onOk:async()=>{
    try{await nxApi('/api/console/stop',{role:'assistant'});nxToast(I18N['nx.ai_stopped_toast']);}
    catch(e){nxToast(I18N['nx.cmd_failed']);}
    nxFetchStatus();
  }});
}
/* console の SSE は画面の差分でも飛ぶ。走っているかが変わったとき・自動起動のときだけ /api/status を取り直す */
function nxOnConsoleSse(d){
  if((d.role||'assistant')!=='assistant'||d.running===undefined)return;
  const s=nxState.status||{};
  if(d.auto||!!d.running!==!!s.console_running)nxFetchStatus();
}
/* 別のページ（現行 UI・音声コマンド）で見る会議が変わることもあるので、console と Claude と会議の項目だけ定期的に揃える */
async function nxPollConsole(){
  try{
    const d=await nxApi('/api/status'),s=nxState.status;
    if(!s||s.console_running!==d.console_running||s.console_transcript!==d.console_transcript
      ||s.talk_console_running!==d.talk_console_running||!(s.talk||{}).active!==!(d.talk||{}).active){nxApplyStatus(d);nxRenderAll();}
  }catch(e){}
}

/* --- load --- */
function nxSameStem(generated,transcript){
  return generated.replace(/^(advice|analysis)-/,'').replace(/\.md$/,'')===transcript.replace(/^transcript-/,'').replace(/\.txt$/,'');
}
async function nxLoadRight(file,keepGen){
  const g=++nxRtGen,gen=keepGen&&nxRt.file===file&&nxRt.sumGen;
  if(nxRt.file!==file)nxRt=nxRtEmpty();
  nxRt.file=file;
  nxRenderRight();
  if(!file)return;
  const q='?file='+encodeURIComponent(file),get=(p,dflt)=>nxApi(p+q).catch(()=>dflt);
  const [s,a,ad,an]=await Promise.all([get('/api/summary',{}),get('/api/attendees',{attendees:[]}),
    get('/api/advice',{}),get('/api/analysis',{})]);
  if(g!==nxRtGen)return;
  const f=nxFiles.find(x=>x.name===file);
  nxRt={file,loaded:true,sum:{file:s.file||'',content:s.content||'',html:s.html||''},att:a.attendees||[],
    adv:{file:ad.file||'',html:ad.html||''},ana:{file:an.file||'',html:an.html||''},
    sumGen:gen&&!s.content,hasSum:!!(f&&f.has_summary)};
  nxRenderRight();
}
/* actions は始めたこと（始められなかったこと）を知らせるトーストに付けるボタン（[文言, 関数]） */
async function nxGenSummary(f,...actions){
  const file=f||nxState.cur;
  if(!file)return;
  try{
    const d=await nxApi('/api/summary',{file});
    if(d.status!=='ok'){nxToast(d.message||I18N['nx.cmd_failed'],...actions);return;}
    if(nxRt.file===file){nxRt.sumGen=true;nxRenderRight();}
    nxToast(I18N['nx.sum_started'],...actions);
  }catch(e){nxToast(I18N['nx.cmd_failed'],...actions);}
}
/* 話した人の名前を変えた後。議事録がある会議だけ、作り直すかを確かめる。
   actions（名前付けの「元に戻す」）は答えた後のトーストに付ける。作り直さないときは msg と一緒に出す */
function nxAskRegenSummary(file,msg,...actions){
  nxConfirm({title:I18N['dash.summary_regen_after_naming'],text:'',ok:I18N['nx.regen_ok'],onOk:()=>nxGenSummary(file,...actions),
    onCancel:actions.length?()=>nxToast(msg||'',...actions):null});
}
/* 画面は HTML なので、元の Markdown を渡す。clipboard API が無い http では textarea で写す */
async function nxCopyText(text){
  try{await navigator.clipboard.writeText(text);return true;}
  catch(e){
    const ta=document.createElement('textarea');
    ta.value=text;ta.style.position='fixed';ta.style.opacity='0';
    document.body.appendChild(ta);ta.select();
    let ok=false;try{ok=document.execCommand('copy');}catch(e2){}
    ta.remove();
    return ok;
  }
}

/* --- render --- */
function nxP(key){return nxEsc(I18N[key]).replace(/\n/g,'<br>');}
function nxEmptyHtml(ic,h,p,btn){
  return '<div class="empty">'+(ic?'<div class="ic">'+ic+'</div>':'<div class="spinner"></div>')+'<h3>'+nxEsc(I18N[h])+'</h3>'
    +'<p>'+nxP(p)+'</p>'+(btn||'')+'</div>';
}
function nxAttHtml(){
  const l=nxRt.att;
  return Array.isArray(l)&&l.length?'<div class="att"><b>'+nxEsc(I18N['dash.attendees'])+'</b><div>'+l.map(nxEsc).join(', ')
    +'</div><small>'+nxEsc(I18N['dash.attendees_note'])+'</small></div>':'';
}
/* 参加者は議事録の先頭の見出しの下に。先頭が見出しでなければ本文の前に */
function nxWithAttendees(html){
  const att=nxAttHtml(),m=/^\s*<h[1-3][^>]*>[\s\S]*?<\/h[1-3]>/.exec(html);
  return m?m[0]+att+html.slice(m[0].length):att+html;
}
function nxSumHtml(){
  const r=nxRt,s=r.sum,f=nxFiles.find(x=>x.name===r.file);
  if(r.sumGen)return nxEmptyHtml('','nx.sum_gen_h','nx.sum_gen_p');
  if(!s.content){
    const btn=k=>'<button class="cta'+(k==='nx.sum_live_btn'?' ghost':'')+'" data-ra="gen">'+nxEsc(I18N[k])+'</button>';
    return nxAttHtml()+(f&&nxState.session&&nxIsLive(f)?nxEmptyHtml('⏳','nx.sum_live_h','nx.sum_live_p',btn('nx.sum_live_btn'))
      :nxEmptyHtml('📝','nx.sum_empty_h','nx.sum_empty_p',btn('nx.sum_make')));
  }
  return '<div class="rtools"><button class="lbtn" data-ra="copy">'+nxEsc(I18N['nx.copy'])+'</button>'
    +'<button class="lbtn" data-ra="reload" title="'+nxEsc(I18N['nx.reload_title'])+'">'+nxEsc(I18N['nx.reload'])+'</button>'
    +'<button class="lbtn" data-ra="regen">'+nxEsc(I18N['nx.regen'])+'</button>'+nxOpenLink(s.file)+'</div>'
    +'<div class="doc">'+(s.html?'<div class="md-body">'+nxWithAttendees(s.html)+'</div>':nxAttHtml()+'<pre class="sumraw">'+nxEsc(s.content)+'</pre>')+'</div>';
}
function nxAiCol(title,tag,g,emptyKey){
  return '<div class="aicol"><div class="secttl"><span>'+nxEsc(I18N[title])+' <span class="muted aitag">'+nxEsc(I18N[tag])+'</span></span>'
    +nxOpenLink(g.file)+'</div><div class="aiscroll"><div class="card">'+(g.html.trim()?'<div class="md-body">'+g.html+'</div>'
    :'<span class="muted">'+nxEsc(I18N[emptyKey])+'</span>')+'</div></div></div>';
}
function nxAiHtml(){
  const cur=nxRt.file,aiFor=nxAssistantFor(),running=!!(nxState.status&&nxState.status.console_running),
    mine=running&&aiFor===cur,other=running&&!mine;
  if(nxAiBusy)return nxEmptyHtml('','nx.ai_busy_h','nx.ai_busy_p');
  const hint=other?'<div class="hint aiother">'+nxEsc(nxFmt('nx.ai_other',{name:aiFor?nxFileLabel(aiFor):I18N['nx.ai_other_unknown']}))+'</div>':'';
  const startBtn=cls=>'<button class="'+cls+'" data-ra="ai-start">'+nxEsc(I18N[other?'nx.ai_switch':cls==='cta'?'nx.ai_start':'nx.ai_resume'])+'</button>';
  if(!mine&&!nxRt.adv.html.trim()&&!nxRt.ana.html.trim())return nxEmptyHtml('💡','nx.ai_empty_h','nx.ai_empty_p',startBtn('cta')+hint);
  const stat=mine?'<div class="astat"><span class="dot"></span>'+nxEsc(I18N['nx.ai_watching'])+'<span class="spacer"></span>'
      +'<button class="lbtn" data-ra="ai-stop">'+nxEsc(I18N['nx.ai_stop'])+'</button></div>'
    :'<div class="astat off"><span class="muted">'+nxEsc(I18N[other?'nx.ai_other_status':'nx.ai_stopped'])+'</span>'
      +'<span class="spacer"></span>'+startBtn('lbtn')+'</div>'+hint;
  return stat+'<div class="aigrid">'+nxAiCol('nx.ai_adv_title','nx.ai_adv_tag',nxRt.adv,'dash.no_advice')
    +'<div class="aisep" title="'+nxEsc(I18N['nx.ai_split_resize'])+'"></div>'+nxAiCol('nx.ai_ana_title','nx.ai_ana_tag',nxRt.ana,'dash.no_analysis')+'</div>';
}
function nxRightHtml(){
  if(!nxState.cur)return '<div class="empty"><p>'+nxEsc(I18N['nx.no_file'])+'</p></div>';
  if(!nxRt.loaded)return '';
  return nxState.rtab==='ai'?nxAiHtml():nxSumHtml();
}
function nxRenderRight(){
  nxEl('nxRtabs').querySelectorAll('button').forEach(b=>b.classList.toggle('act',b.dataset.rt===nxState.rtab));
  const rb=nxEl('nxRightBody'),html=nxRightHtml();
  if(html===nxRtHtml)return;
  const top=rb.scrollTop,colTops=[...rb.querySelectorAll('.aiscroll')].map(c=>c.scrollTop);
  nxRtHtml=html;rb.innerHTML=html;
  rb.classList.toggle('aisplit',!!rb.querySelector('.aigrid'));
  rb.querySelectorAll('.aiscroll').forEach((c,i)=>{c.scrollTop=colTops[i]||0;});
  // AI分析 の 🔊 の例文をクリックで読む（流用する _JS_TEMPLATE_SPEECH の decorateSay。現行も生成物にだけ付ける）
  if(nxState.rtab==='ai')decorateSay(rb);
  nxLinkifyFiles(rb);
  rb.scrollTop=top;
}
function nxRenderRightPane(){
  const cur=nxState.cur||'',f=nxFiles.find(x=>x.name===cur);
  if(cur!==nxRt.file)nxLoadRight(cur);
  // 議事録ができてファイル一覧に has_summary が立ったら読み直す
  else if(f&&f.has_summary&&!nxRt.hasSum&&nxRt.loaded){nxRt.hasSum=true;nxLoadRight(cur,true);}
  else nxRenderRight();
}
function nxOnRightClick(e){
  const b=e.target.closest('[data-ra]');
  if(!b)return;
  const a=b.dataset.ra;
  if(a==='gen')nxGenSummary();
  else if(a==='regen')nxConfirm({title:I18N['nx.sum_regen_title'],text:I18N['nx.sum_regen_text'],ok:I18N['nx.regen_ok'],onOk:nxGenSummary});
  else if(a==='reload')nxLoadRight(nxRt.file,true).then(()=>nxToast(I18N['nx.sum_reloaded']));
  else if(a==='copy')nxCopyText(nxRt.sum.content).then(ok=>nxToast(I18N[ok?'nx.sum_copied':'nx.copy_failed']));
  else if(a==='ai-start')nxAiStart();
  else if(a==='ai-stop')nxAiStop();
}
function nxOnGenerated(kind,d){
  if(!nxRt.file||!nxSameStem(d.file||'',nxRt.file))return;
  nxRt[kind]={file:d.file,html:d.html||''};
  nxRenderRight();
}
/* アドバイスと分析の仕切り。上下に積むとき（右ペイン）と左右に並べるとき（中央）で別々に割合を覚える。
   rbody に CSS 変数で持つので描き直しても残る。割合は同じ座標系どうしの比なので zoom で割らなくてよい */
function nxAiSplitSet(axis,pct){nxEl('nxRightBody').style.setProperty('--ais-'+axis,pct.toFixed(1)+'%');}
function nxAiSplitDrag(e){
  const sep=e.target.closest('.aisep');
  if(!sep||e.button!==0)return;
  e.preventDefault();
  const rb=nxEl('nxRightBody'),axis=getComputedStyle(sep.parentNode).flexDirection==='column'?'v':'h';
  let pct=0;
  const move=ev=>{
    const g=rb.querySelector('.aigrid');if(!g)return;
    const r=g.getBoundingClientRect(),[p,a,len]=axis==='v'?[ev.clientY,r.top,r.height]:[ev.clientX,r.left,r.width];
    pct=Math.max(10,Math.min(90,(p-a)/len*100));nxAiSplitSet(axis,pct);
  };
  const up=()=>{
    window.removeEventListener('mousemove',move);window.removeEventListener('mouseup',up);
    rb.classList.remove('aidrag');document.body.style.cursor='';
    if(pct)nxStoreSet('nxAiSplit'+axis,pct.toFixed(1));
  };
  rb.classList.add('aidrag');document.body.style.cursor=getComputedStyle(sep).cursor;
  window.addEventListener('mousemove',move);window.addEventListener('mouseup',up);
}
function nxRightInit(){
  nxRenderers.push(nxRenderRightPane);
  ['v','h'].forEach(axis=>{const n=parseFloat(nxStoreGet('nxAiSplit'+axis)||'');if(n>=10&&n<=90)nxAiSplitSet(axis,n);});
  nxEl('nxRightBody').addEventListener('mousedown',nxAiSplitDrag);
  nxEl('nxRtabs').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{nxState.rtab=b.dataset.rt;nxRenderRight();}));
  nxEl('nxRightBody').addEventListener('click',nxOnRightClick);
  nxOn('advice',d=>nxOnGenerated('adv',d));
  nxOn('analysis',d=>nxOnGenerated('ana',d));
  nxOn('console',nxOnConsoleSse);
  // 議事録の完了通知（現行と同じ alert、本文に summary-<stem>.md）。開いているファイルの議事録を名指ししたときだけ読み直す
  nxOn('alert',d=>{
    if(d.kind==='command_api_error'){if(d.message)alert(d.message);return;}
    if(d.message)nxToast(d.message);
    const f=nxRt.file,sum=f&&f.replace(/^transcript-/,'summary-').replace(/\.txt$/,'.md');
    if(sum&&(d.message||'').includes(sum))nxLoadRight(f,false);
  });
  setInterval(nxPollConsole,10000);
}
nxRightInit();
"""
