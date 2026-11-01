"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 核（状態・API・SSE・ヘッダ）"""
from __future__ import annotations

# 後続タスクの描画関数は nxRenderers に push する。nxRenderAll がヘッダのあとに順に呼ぶ。
# nxOn で購読した SSE ハンドラーは、再接続して EventSource を作り直しても付け直される
_NEXT_JS_CORE = r"""
/* --- core: state / API / toast --- */
const nxState={session:null,running:true,connected:true,translating:false,
  muteMic:false,muteMonitor:false,useMic:true,useMonitor:true,status:null};
const nxRenderers=[];
const nxHandlers=[];
let nxEs=null;
/* ファイルの中身をそのまま別タブで開くリンク */
function nxOpenLink(name,key){
  return name?'<a class="lbtn sm" href="/api/file?name='+encodeURIComponent(name)+'" target="_blank" rel="noopener" title="'
    +nxEsc(name)+'">'+nxEsc(I18N[key||'nx.open'])+'</a>':'';
}
let nxToastTimer=null;
const nxReconnectMs=3000;
function nxEl(id){return document.getElementById(id);}
function nxStoreGet(key){try{return localStorage.getItem(key);}catch(e){return null;}}
function nxStoreSet(key,val){try{localStorage.setItem(key,val);}catch(e){}}
async function nxApi(path,body){
  const r=await fetch(path,body===undefined?undefined:{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return r.json();
}
/* 成功したら true。失敗はトーストで知らせて false */
async function nxCmd(command){
  try{
    const d=await nxApi('/api/command',{command});
    if(!(d&&d.status==='error'))return true;
  }catch(e){}
  nxToast(I18N['nx.cmd_failed']);
  return false;
}
function nxToast(message,...actions){
  const el=nxEl('nxToast');
  el.textContent='';
  const sp=document.createElement('span');sp.textContent=message;el.appendChild(sp);
  actions.forEach(([label,fn])=>{
    const b=document.createElement('button');b.textContent=label;
    b.addEventListener('click',()=>{el.classList.remove('show');fn();});
    el.appendChild(b);
  });
  el.classList.add('show');
  clearTimeout(nxToastTimer);
  nxToastTimer=setTimeout(()=>el.classList.remove('show'),actions.length?8000:3000);
}

/* --- SSE: 切れたら 3 秒ごとに再接続し、つながったら /api/status を取り直す --- */
function nxOn(eventType,fn){
  const h=e=>{let d;try{d=JSON.parse(e.data);}catch(x){return;}fn(d,e);};
  nxHandlers.push([eventType,h]);
  if(nxEs)nxEs.addEventListener(eventType,h);
}
function nxConnect(){
  const es=new EventSource('/api/events');
  nxEs=es;
  nxHandlers.forEach(([type,h])=>es.addEventListener(type,h));
  es.onopen=()=>{nxState.connected=true;nxFetchStatus();};
  es.onerror=()=>{
    try{es.close();}catch(e){}
    if(nxEs!==es)return;
    nxEs=null;
    nxState.connected=false;nxRenderHeader();
    setTimeout(nxConnect,nxReconnectMs);
  };
}
function nxApplyStatus(d){
  const s=nxState;
  s.status=d;s.running=d.running!==false;s.session=d.session||null;s.translating=!!d.translating;
  s.muteMic=!!d.mute_mic;s.muteMonitor=!!d.mute_monitor;
  s.useMic=d.use_mic!==false;s.useMonitor=d.use_monitor!==false;
}
async function nxFetchStatus(){
  try{nxApplyStatus(await nxApi('/api/status'));nxRenderAll();}catch(e){}
}

/* --- header --- */
function nxSessionInfo(path){
  const m=/transcript-(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(?:@([^.]+))?\.txt$/.exec(path||'');
  if(!m)return {name:'',startMs:null};
  return {name:(m[6]||'').replace(/_/g,' '),startMs:new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5]).getTime()};
}
function nxFmtElapsed(ms){
  const t=Math.max(0,Math.floor(ms/1000)),h=Math.floor(t/3600),m=Math.floor(t%3600/60),s=t%60;
  const p=n=>String(n).padStart(2,'0');
  return h?h+':'+p(m)+':'+p(s):m+':'+p(s);
}
function nxStatusView(){
  const s=nxState;
  if(!s.connected)return ['disconnected',I18N['nx.status_disconnected']];
  if(s.session){
    const {name,startMs}=nxSessionInfo(s.session);
    const parts=[I18N['nx.status_meeting']];
    if(startMs!==null)parts.push(nxFmtElapsed(Date.now()-startMs));
    if(name)parts.push('・'+name);
    return ['meeting',parts.join(' ')];
  }
  return s.running?['idle',I18N['nx.status_idle']]:['stopped',I18N['nx.status_stopped']];
}
function nxRenderDevice(kind,muted,available){
  const btn=nxEl(kind==='mic'?'nxMicBtn':'nxMonitorBtn');
  btn.classList.toggle('unavail',!available);
  btn.classList.toggle('off',available&&muted);
  btn.title=kind==='mic'
    ?(!available?I18N['nx.mic_unavailable']:muted?I18N['nx.unmute_mic_title']:I18N['nx.mute_mic_title'])
    :(!available?I18N['nx.monitor_unavailable']:muted?I18N['nx.unmute_monitor_title']:I18N['nx.mute_monitor_title']);
  btn.setAttribute('aria-pressed',String(available&&muted));
}
function nxRenderHeader(){
  const s=nxState,[cls,text]=nxStatusView();
  nxEl('nxStatus').className='status '+cls;
  nxEl('nxStatusText').textContent=text;
  const mb=nxEl('nxMeetingBtn');
  mb.className='primary'+(s.session?' stop':'');
  mb.textContent=I18N[s.session?'nx.meeting_end':'nx.meeting_start'];
  nxEl('nxTranslateBtn').classList.toggle('on',s.translating);
  nxEl('nxTranslateBtn').setAttribute('aria-pressed',String(s.translating));
  nxRenderDevice('mic',s.muteMic,s.useMic);
  nxRenderDevice('monitor',s.muteMonitor,s.useMonitor);
}
function nxRenderAll(){
  nxRenderHeader();
  nxRenderers.forEach(fn=>fn());
}
function nxToggleMute(kind){
  const s=nxState,key=kind==='mic'?'muteMic':'muteMonitor';
  if(!(kind==='mic'?s.useMic:s.useMonitor))return;
  s[key]=!s[key];
  nxCmd((s[key]?'mute_':'unmute_')+kind);
  nxRenderAll();
}
/* 記録中でないファイルを開いていれば、そのファイルを翻訳する（現行 togTranslate と同じ）。
   nxActive は左ペイン、nxFileArg・nxTrTarget は文字起こしのモジュールにある */
function nxToggleTranslate(){
  const s=nxState;
  s.translating=!s.translating;
  nxCmd(s.translating?'translate_start'+(s.cur&&s.cur!==nxActive?' '+nxFileArg(s.cur):''):'translate_stop');
  nxTrTarget=s.translating?s.cur||'':'';
  if(s.translating&&s.view==='T'){s.view='TR';nxToast(I18N['nx.translate_started_tr']);}
  nxRenderAll();
}
/* 16bit PCM の目安で rms=100 を 0%、rms=20000 を 100% とする対数スケール */
function nxLevelPct(v){
  return !v||v.rms<=100?0:Math.min(100,(Math.log10(v.rms)-2)/2.301*100);
}
function nxSetLevel(kind,v){
  nxEl(kind==='mic'?'nxMicLv':'nxMonitorLv').style.width=nxLevelPct(v).toFixed(0)+'%';
}

/* --- display mode / theme / menus / drawer --- */
function nxSetAdv(on,remember=true){
  document.body.classList.toggle('adv',on);
  nxEl('nxModeSeg').querySelectorAll('button').forEach(b=>b.classList.toggle('act',(b.dataset.adv==='1')===on));
  if(remember)nxStoreSet('nxAdv',on?'1':'0');
}
function nxEffectiveTheme(){
  return document.documentElement.getAttribute('data-theme')
    ||(window.matchMedia&&window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');
}
function nxRenderTheme(){nxEl('nxThemeBtn').textContent=nxEffectiveTheme()==='light'?'☀':'🌙';}
function nxSetTheme(theme){
  document.documentElement.setAttribute('data-theme',theme);
  nxStoreSet('nxTheme',theme);
  nxRenderTheme();
}
function nxCloseMenus(except){
  document.querySelectorAll('.menu.open').forEach(m=>{if(m!==except)m.classList.remove('open');});
}
function nxBindMenu(btnId,menuId){
  nxEl(btnId).addEventListener('click',()=>{
    const m=nxEl(menuId);
    nxCloseMenus(m);
    m.classList.toggle('open');
  });
}
/* 開閉は nxState.bottom。描くのは表示切り替えのモジュール（nxRenderView） */
function nxToggleDrawer(){nxState.bottom=!nxState.bottom;nxRenderAll();}

function nxInit(){
  const saved=nxStoreGet('nxTheme');
  if(saved==='light'||saved==='dark')document.documentElement.setAttribute('data-theme',saved);
  nxRenderTheme();
  nxSetAdv(nxStoreGet('nxAdv')==='1');
  nxEl('nxModeSeg').querySelectorAll('button').forEach(b=>
    b.addEventListener('click',()=>nxSetAdv(b.dataset.adv==='1')));
  nxEl('nxThemeBtn').addEventListener('click',()=>nxSetTheme(nxEffectiveTheme()==='light'?'dark':'light'));
  nxEl('nxMicBtn').addEventListener('click',()=>nxToggleMute('mic'));
  nxEl('nxMonitorBtn').addEventListener('click',()=>nxToggleMute('monitor'));
  nxEl('nxTranslateBtn').addEventListener('click',nxToggleTranslate);
  nxEl('nxDrawerToggle').addEventListener('click',nxToggleDrawer);
  nxBindMenu('nxMoreBtn','nxMoreMenu');
  nxBindMenu('nxViewBtn','nxViewMenu');
  document.addEventListener('click',e=>{if(!e.target.closest('.menu-wrap'))nxCloseMenus(null);});
  nxOn('session',d=>{nxState.session=d.content||null;nxRenderHeader();});
  nxOn('level',d=>{nxSetLevel('mic',d.mic);nxSetLevel('monitor',d.monitor);});
  setInterval(()=>{if(nxState.session)nxRenderHeader();},1000);
  nxRenderAll();
  nxConnect();
}
"""
