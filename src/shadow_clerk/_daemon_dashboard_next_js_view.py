"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 表示の切り替え（🪟 メニュー・ペインの開閉・文字の大きさ・ショートカット）と下ドロワー"""
from __future__ import annotations

# 真ん中に出すもの nxState.view: T / TR / R（文字起こしのモジュールが描く）、AI（右ペインを中央の列へ）、
# CON（AI アシスタントの画面を中央に、文字起こしをその右に。くわしく表示だけ）。
# 端末は流用する現行のコンソール（#consoleRow）1 つだけ。nxPlaceConsole が中央・ドロワーの置き場所へ移し、役割を切り替える
_NEXT_JS_VIEW = r"""
/* --- view switch / panes / drawer --- */
const nxViews=[['T','<i class="t"></i>'],['TR','<i class="t"></i><i class="r"></i>'],['R','<i class="r"></i>'],
  ['AI','<i class="a"></i><i class="t n"></i>'],['CON','<i class="c"></i><i class="t n"></i>']];
const nxPaneKeys={left:'Alt+[',right:'Alt+]',bottom:'Alt+\\'};
const nxFontSizes=[['dash.font_s',0.9],['dash.font_m',1],['dash.font_l',1.2]];
let nxFontStep=(()=>{const n=parseInt(nxStoreGet('nxFontStep')||'1',10);return n>=0&&n<nxFontSizes.length?n:1;})();
nxState.dtab='ai';
let nxLogLoaded=false;
function nxIsAdv(){return document.body.classList.contains('adv');}
function nxSetView(v){
  const s=nxState;
  s.view=v;
  if(v==='AI'||v==='CON')s.rtab='ai';
  if(v==='CON')s.right=true;
  nxRenderAll();
}
/* パネルの開閉は表示（真ん中に出すもの）を変えない。AI のときは右のパネルが真ん中に来ているので、右は切り替えない */
function nxPaneFixed(k){return k==='right'&&nxState.view==='AI';}
function nxTogglePane(k){
  if(nxPaneFixed(k))return;
  nxState[k]=!nxState[k];
  nxRenderAll();
}
/* ボタン・メニューも含めて画面全体を CSS zoom で大きくする。AI アシスタントの端末（流用する #consoleRow）は
   逆数で打ち消して元の大きさのまま: 端末には自分の文字の大きさの設定があり、列数の計算や仕切りのドラッグが
   画面の座標をそのまま style に書くので、zoom の中に入れるとずれる */
function nxZoom(){return nxFontSizes[nxFontStep][1];}
function nxApplyFont(){
  const z=nxZoom();
  document.documentElement.style.zoom=String(z);
  nxEl('consoleRow').style.zoom=String(1/z);
}
function nxSetFont(n){
  nxFontStep=n;
  nxStoreSet('nxFontStep',String(n));
  nxApplyFont();
  scheduleConsoleCols();
  nxRenderAll();
}
function nxViewMenuHtml(){
  const s=nxState;
  const tog=(k,adv)=>{
    const fixed=nxPaneFixed(k);
    return '<div class="ptog'+(s[k]&&!fixed?' on':'')+(fixed?' fixed':'')+(adv?' adv-only':'')+'" data-pt="'+k+'"><span class="sw2"></span>'
      +nxEsc(I18N['nx.p_'+k])+(fixed?'<small class="muted">'+nxEsc(I18N['nx.p_right_center'])+'</small>':'')
      +'<span class="spacer"></span><span class="kbd">'+nxEsc(nxPaneKeys[k])+'</span></div>';
  };
  return '<div class="vm-t">'+nxEsc(I18N['nx.vm_center'])+'</div><div class="vgrid">'
    +nxViews.map(([k,th],i)=>'<div class="vopt'+(s.view===k?' act':'')+(k==='CON'?' adv-only':'')+'" data-v="'+k+'">'
      +'<div class="thumb">'+th+'</div>'+nxEsc(I18N['nx.v_'+k])+'<span class="kbd kb">Alt+'+(i+1)+'</span></div>').join('')
    +'</div><div class="vm-t vm-gap">'+nxEsc(I18N['nx.vm_panes'])+'</div>'+tog('left')+tog('right')+tog('bottom',true)
    +(s.translating?'':'<div class="hint vm-hint">'+nxEsc(I18N['nx.vm_tr_hint'])+'</div>')
    +'<div class="vm-t vm-gap">'+nxEsc(I18N['nx.mi_font'])+'</div><div class="fseg">'
    +nxFontSizes.map(([key],i)=>'<button class="'+(i===nxFontStep?'act':'')+'" data-fs="'+i+'">'+nxEsc(I18N[key])+'</button>').join('')+'</div>';
}
/* メニューは position:fixed。ボタンの下に出し、画面の右端・下端からはみ出さないよう寄せる。
   測った座標は zoom 後の画面の値、style に書く値は zoom 前の値なので、zoom で割る */
function nxPlaceViewMenu(){
  const z=nxZoom(),r=nxEl('nxViewBtn').getBoundingClientRect(),m=nxEl('nxViewMenu'),vw=window.innerWidth/z,vh=window.innerHeight/z;
  const left=r.left/z,bottom=r.bottom/z,w=Math.min(360,vw-16);
  m.style.width=w+'px';
  m.style.left=Math.max(8,Math.min(left,vw-w-8))+'px';
  m.style.top=(bottom+6)+'px';
  m.style.maxHeight=Math.max(120,vh-bottom-14)+'px';
}
function nxDrawerStat(){
  const s=nxState.status||{},d=nxState.dtab;
  if(d==='log'||d==='resp')return '';
  return I18N[(d==='talk'?s.talk_console_running:s.console_running)?'nx.d_running':'nx.d_idle'];
}
/* 中央に出しているときは中央、ドロワーを開いて AI / Claude と会議 のタブを選んでいればそこ。どちらでもなければ（ログ・応答）動かさない */
function nxConsoleSpot(){
  const s=nxState;
  if(s.view==='CON')return ['assistant','nxConsoleMain'];
  if(s.bottom&&s.dtab==='talk')return ['talk','nxConsoleTalk'];
  if(s.bottom&&s.dtab==='ai')return ['assistant','nxConsoleAi'];
  return null;
}
let nxConHost='';
function nxPlaceConsole(){
  const spot=nxConsoleSpot();
  if(!spot){nxConHost='';return;}
  const [role,host]=spot,row=nxEl('consoleRow');
  if(row.parentNode!==nxEl(host))nxEl(host).appendChild(row);
  if(role!==_consoleRole||logTab!=='console')selectConsoleRole(role);
  // 出てきた・移ったときは幅を測り直して下端を見せる（ドロワーは開く動きが終わってから）
  if(nxConHost!==host){nxConHost=host;scheduleConsoleCols();setTimeout(scrollConsoleBottom,250);}
}
/* 下ドロワーの高さは上端のつまみのドラッグで変えて覚える。測る座標は zoom 後の画面の値なので zoom で割る */
function nxSetDrawerH(h){nxEl('nxDrawer').style.setProperty('--dh',Math.round(h)+'px');}
function nxDrawerResizeInit(){
  const dr=nxEl('nxDrawer'),saved=parseInt(nxStoreGet('nxDrawerH')||'0',10);
  if(saved>=120)nxSetDrawerH(saved);
  nxEl('nxDrawerGrip').addEventListener('mousedown',e=>{
    e.preventDefault();
    const z=nxZoom(),bottom=nxEl('nxDrawerBody').getBoundingClientRect().bottom;
    let h=0;
    const move=ev=>{h=Math.max(120,Math.min(window.innerHeight*0.8,bottom-ev.clientY))/z;nxSetDrawerH(h);};
    const up=()=>{
      window.removeEventListener('mousemove',move);window.removeEventListener('mouseup',up);
      dr.classList.remove('dragging');
      if(h)nxStoreSet('nxDrawerH',String(Math.round(h)));
      scrollConsoleBottom();
    };
    dr.classList.add('dragging');
    window.addEventListener('mousemove',move);window.addEventListener('mouseup',up);
  });
}
function nxRenderDrawer(){
  const s=nxState,st=s.status||{},con=s.view==='CON';
  nxEl('nxDrawer').classList.toggle('open',s.bottom);
  nxEl('nxDrawerToggle').textContent=s.bottom?'▼':'▲';
  nxEl('nxDrawerTabs').querySelectorAll('button').forEach(b=>b.classList.toggle('act',b.dataset.d===s.dtab));
  nxEl('nxDrawerStat').textContent=nxDrawerStat();
  nxEl('nxDrawerBody').querySelectorAll('[data-d]').forEach(p=>{p.style.display=p.dataset.d===s.dtab?'':'none';});
  nxEl('nxDrawerNoteAi').textContent=con?I18N['nx.d_con_center']:st.console_running?'':I18N['nx.d_ai_off'];
  nxEl('nxDrawerNoteTalk').textContent=con?I18N['nx.d_talk_con']:st.talk_console_running?'':I18N['nx.d_talk_off'];
  nxEl('nxConsoleMain').classList.toggle('idle',!st.console_running);
  nxEl('nxConStart').disabled=!s.cur||nxAiBusy;
  nxEl('nxConMainHead').textContent='🤖 '+I18N['nx.v_CON']+'・'+I18N[st.console_running?'nx.d_running':'nx.d_idle']
    +(st.console_running?'':' — '+I18N['nx.d_ai_off']);
  if(s.bottom&&s.dtab==='log'&&!nxLogLoaded)nxLoadLogs();
}
function nxRenderView(){
  const s=nxState,app=nxEl('nxApp'),aim=s.view==='AI',con=s.view==='CON';
  app.classList.toggle('no-left',!s.left);
  app.classList.toggle('no-right',!s.right);
  app.classList.toggle('aimode',aim);
  nxEl('nxMain').classList.toggle('narrow',aim||con);
  nxEl('nxMain').classList.toggle('aiview',con);
  nxEl('nxViewMenu').innerHTML=nxViewMenuHtml();
  nxRenderDrawer();
  nxPlaceConsole();
}

/* --- 動作ログ（現行 loadLogs と SSE log と同じ） --- */
const nxLogMax=500;
function nxLogLine(line){return '<div class="ll'+(line.includes('ERROR')?' e':line.includes('WARNING')?' w':'')+'">'+nxEsc(line)+'</div>';}
function nxAppendLogs(lines){
  const el=nxEl('nxLogView'),follow=el.scrollTop+el.clientHeight>=el.scrollHeight-30;
  el.insertAdjacentHTML('beforeend',lines.map(nxLogLine).join(''));
  while(el.children.length>nxLogMax)el.firstElementChild.remove();
  if(follow)el.scrollTop=el.scrollHeight;
}
async function nxLoadLogs(){
  nxLogLoaded=true;
  try{
    const d=await nxApi('/api/logs');
    nxEl('nxLogView').innerHTML='';
    nxAppendLogs(d.lines||[]);
    nxEl('nxLogView').scrollTop=nxEl('nxLogView').scrollHeight;
  }catch(e){nxLogLoaded=false;}
}

/* --- shortcuts: Alt+1..5 / Alt+[ ] \ 。入力欄にいるときは使わない --- */
function nxOnViewKey(e){
  if(!e.altKey||e.ctrlKey||e.metaKey)return;
  const t=e.target;
  if(t&&(t.isContentEditable||(t.closest&&t.closest('input,textarea,select,[contenteditable]'))))return;
  const n=/^Digit([1-5])$/.exec(e.code||'')?+e.code.slice(5):+e.key,adv=nxIsAdv();
  if(n>=1&&n<=5){
    if(n===5&&!adv)return;
    e.preventDefault();nxSetView(nxViews[n-1][0]);return;
  }
  const k={'[':'left',']':'right','\\':'bottom'}[e.key];
  if(!k||(k==='bottom'&&!adv))return;
  e.preventDefault();nxTogglePane(k);
}
function nxOnViewMenuClick(e){
  e.stopPropagation();  // 描き直すとクリックした要素が外れ、メニューの外のクリックと見なされて閉じてしまう
  const v=e.target.closest('[data-v]'),p=e.target.closest('[data-pt]'),f=e.target.closest('[data-fs]');
  if(v)nxSetView(v.dataset.v);
  else if(p)nxTogglePane(p.dataset.pt);
  else if(f)nxSetFont(+f.dataset.fs);
}
function nxViewInit(){
  nxRenderers.push(nxRenderView);
  nxApplyFont();
  nxDrawerResizeInit();
  nxEl('nxConStart').addEventListener('click',()=>nxAiStart());
  nxEl('nxViewMenu').addEventListener('click',nxOnViewMenuClick);
  nxEl('nxViewBtn').addEventListener('click',nxPlaceViewMenu);
  window.addEventListener('resize',()=>{if(nxEl('nxViewMenu').classList.contains('open'))nxPlaceViewMenu();});
  nxEl('nxDrawerTabs').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{
    nxState.dtab=b.dataset.d;nxState.bottom=true;nxRenderAll();
  }));
  // かんたん表示に戻したら、くわしく表示だけの AI アシスタントの画面はやめる（ボタンの処理のあとに走るよう親で受ける）
  nxEl('nxModeSeg').addEventListener('click',()=>{if(!nxIsAdv()&&nxState.view==='CON')nxState.view='T';nxRenderAll();});
  document.addEventListener('keydown',nxOnViewKey);
  nxOn('log',d=>{if(nxLogLoaded&&d.line)nxAppendLogs([d.line]);});
}
nxViewInit();
"""
