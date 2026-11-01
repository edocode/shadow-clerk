"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 左ペイン「検索」タブ（/api/search。#nxSearch に描く）"""
from __future__ import annotations

# 結果の line はファイル全体の行番号 (1 始まり、見出し・空行を含む)。nxMarks の位置を引いて .ln（data-i）に当てる（nxSrTarget）。
# line 0 は日付だけの検索（ファイル単位）。サーバーは 200 件で打ち切る
_NEXT_JS_SEARCH = r"""
/* --- left pane: search --- */
const nxSrLimit=200;
const nxSrTypes=['all','transcript','translation','summary'];
const nxSq={q:'',type:'all',y:'',m:'',d:'',h:'',dateOpen:false,results:null,loading:false,failed:false};
let nxSrGen=0;
function nxSearchQuery(sq){
  const q=sq.q.trim(),p=new URLSearchParams();
  if(!q&&!(sq.y||sq.m||sq.d||sq.h))return null;
  [['year',sq.y],['month',sq.m],['day',sq.d],['hour',sq.h]].forEach(([k,v])=>{if(v)p.set(k,v);});
  if(q)p.set('query',q);
  p.set('type',sq.type);
  return p.toString();
}
/* 先にエスケープしてから <mark> で囲む。大文字小文字を無視（サーバーと同じ）して元の綴りを保つ */
function nxMarkHtml(text,q){
  text=String(text);q=q.trim();
  if(!q)return nxEsc(text);
  const lo=text.toLowerCase(),lq=q.toLowerCase();
  let out='',i=0,j;
  while((j=lo.indexOf(lq,i))>=0){out+=nxEsc(text.slice(i,j))+'<mark>'+nxEsc(text.slice(j,j+q.length))+'</mark>';i=j+q.length;}
  return out+nxEsc(text.slice(i));
}
function nxSearchGroups(rs){
  const m=new Map();
  rs.forEach(r=>{if(!m.has(r.file))m.set(r.file,{file:r.file,display:r.display.replace(/ L\d+$/,''),hits:[]});m.get(r.file).hits.push(r);});
  return [...m.values()];
}
async function nxSearchRun(){
  const qs=nxSearchQuery(nxSq),g=++nxSrGen;
  nxSq.failed=false;
  if(qs===null){nxSq.results=null;nxSq.loading=false;nxRenderSearch();return;}
  nxSq.loading=true;nxRenderSearch();
  try{
    const d=await nxApi('/api/search?'+qs);
    if(g!==nxSrGen)return;
    nxSq.results=d.results||[];
  }catch(e){
    if(g!==nxSrGen)return;
    nxSq.results=null;nxSq.failed=true;
  }
  nxSq.loading=false;nxRenderSearch();
}
function nxSrDateText(){
  const s=nxSq,parts=[s.y&&nxFmt('nx.sr_fy',{n:s.y}),s.m&&nxFmt('nx.sr_fm',{n:+s.m}),s.d&&nxFmt('nx.sr_fd',{n:+s.d}),s.h&&nxFmt('nx.sr_fh',{n:+s.h})];
  return parts.filter(Boolean).join('');
}
function nxSrSelect(k,label,vals){
  return '<select data-sd="'+k+'"><option value="">'+nxEsc(label)+'</option>'
    +vals.map(v=>'<option value="'+v+'"'+(nxSq[k]===v?' selected':'')+'>'+(+v)+'</option>').join('')+'</select>';
}
function nxSrYears(){
  const ys=new Set(nxFiles.map(f=>f.dt.slice(0,4)));
  ys.add(String(new Date().getFullYear()));
  return [...ys].sort().reverse();
}
const nxPad2=n=>String(n).padStart(2,'0');
function nxSrFormHtml(){
  const s=nxSq,dated=s.y||s.m||s.d||s.h,rng=(n,from)=>Array.from({length:n},(_,i)=>nxPad2(i+from));
  return '<div class="sr-form"><div class="sr-q"><input id="nxSrQ" placeholder="'+nxEsc(I18N['nx.sr_ph'])+'" value="'+nxEsc(s.q)+'">'
    +'<button class="lbtn" data-sr="go">'+nxEsc(I18N['nx.sr_go'])+'</button></div>'
    +'<div class="sr-types">'+nxSrTypes.map(t=>'<button class="sr-t'+(s.type===t?' act':'')+'" data-st="'+t+'">'+nxEsc(I18N['nx.sr_t_'+t])+'</button>').join('')+'</div>'
    +'<button class="sr-dt" data-sr="date">📅 '+nxEsc(I18N['nx.sr_date'])+(dated?'：'+nxEsc(nxSrDateText()):'')+' '+(s.dateOpen?'▴':'▾')+'</button>'
    +(s.dateOpen?'<div class="sr-dates">'+nxSrSelect('y',I18N['nx.sr_y'],nxSrYears())+nxSrSelect('m',I18N['nx.sr_m'],rng(12,1))
      +nxSrSelect('d',I18N['nx.sr_d'],rng(31,1))+nxSrSelect('h',I18N['nx.sr_h'],rng(24,0))+'</div>'
      +'<div class="sr-quick"><button class="lbtn sm" data-sq="today">'+nxEsc(I18N['nx.sr_today'])+'</button>'
      +'<button class="lbtn sm" data-sq="month">'+nxEsc(I18N['nx.sr_month'])+'</button>'
      +(dated?'<button class="lbtn sm" data-sq="clear">'+nxEsc(I18N['nx.sr_clear'])+'</button>':'')+'</div>'
      +'<div class="hint">'+nxEsc(I18N['nx.sr_date_hint'])+'</div>':'')+'</div>';
}
function nxSrHitHtml(r,k){
  const pill=r.type==='summary'?'<span class="pill sum">'+nxEsc(I18N['nx.pill_summary'])+'</span>'
    :r.type==='translation'?'<span class="pill">'+nxEsc(I18N['nx.sr_pill_tr'])+'</span>':'';
  return '<div class="sr-hit" data-k="'+k+'"><div class="sr-meta">'+pill+'<span class="adv-only muted">L'+Number(r.line)+'</span></div>'
    +'<div class="sr-text">'+nxMarkHtml(r.text,nxSq.q)+'</div></div>';
}
function nxSearchHtml(){
  const s=nxSq,r=s.results;
  let html=nxSrFormHtml();
  const hint=k=>html+'<div class="empty">'+nxEsc(I18N[k])+'</div>';
  if(s.loading)return hint('nx.sr_loading');
  if(s.failed)return hint('nx.sr_error');
  if(!r)return hint('nx.sr_intro');
  if(!r.length)return hint('nx.sr_none');
  html+='<div class="sr-count">'+nxEsc(r.length>=nxSrLimit?nxFmt('nx.sr_cap',{n:nxSrLimit}):nxFmt('nx.sr_count',{n:r.length}))+'</div>';
  nxSearchGroups(r).forEach(g=>{
    html+='<div class="sr-file" data-k="'+r.indexOf(g.hits[0])+'"><b>'+nxEsc(g.display)+'</b>'
      +(g.hits[0].line>0?'<span class="cnt">'+g.hits.length+'</span>':'')+'</div>';
    g.hits.filter(h=>h.line>0).forEach(h=>{html+=nxSrHitHtml(h,r.indexOf(h));});
  });
  return html;
}
function nxRenderSearch(){nxEl('nxSearch').innerHTML=nxSearchHtml();}

/* 開く: ファイルを開き、行へ移動して光らせる。読み込みは非同期なので、行が描かれるまで待つ */
/* サーバーの line はファイル全体の 1 始まりの行番号（見出し・空行も数える）。nxLines は日付行だけなので、
   nxMarks（{at, text}。j 番目は生の行 at+j にいる）で対応づける。{idx, flash}。flash=false は近くへ動くだけ。null は動かない */
function nxSrTarget(line,text,type){
  if(nxRowsDrift||line<1)return null;
  const r=line-1;
  if(type==='translation'){
    const k=nxTrRows[r];
    if(!k)return null;
    const n=nxTrRows.slice(0,r).filter(x=>x===k).length,want=(nxParseLine(text)||{}).text,texts=nxTrMap.get(k)||[];
    if(want===undefined||(texts[n]||'').trim()!==want.trim())return null;
    let seen=0;
    for(let i=0;i<nxLines.length;i++)if(nxTrKey(nxLines[i])===k&&seen++===n)return {idx:i,flash:true};
    return null;
  }
  let before=0,isMark=false;
  nxMarks.forEach((m,j)=>{const pos=m.at+j;if(pos<r)before++;else if(pos===r)isMark=true;});
  const idx=r-before;
  if(!nxLines.length)return null;
  return isMark||idx>=nxLines.length?{idx:Math.min(idx,nxLines.length-1),flash:false}:{idx,flash:true};
}
function nxSrReveal(file,line,text,type,tries){
  setTimeout(()=>{
    const ready=nxTxFile===file&&!nxTxLoading,t=ready?nxSrTarget(line,text,type):null;
    const ln=t?nxEl('nxTranscript').querySelector('.ln[data-i="'+t.idx+'"]'):null;
    if(ln){
      ln.scrollIntoView({block:'center'});
      if(t.flash){ln.classList.add('flash');setTimeout(()=>ln.classList.remove('flash'),2000);}
    }else if((!ready||t)&&tries<50)nxSrReveal(file,line,text,type,tries+1);
  },100);
}
function nxSearchOpen(file,line,type,text){
  if(type==='summary'){nxState.right=true;nxState.rtab='sum';}
  else if(type==='translation'&&nxState.view==='T')nxSetView('TR');
  const drifted=nxTxFile===file&&nxRowsDrift;
  nxOpenFile(file);
  if(drifted)nxLoadTranscript(file);  // 追記でずれた行の位置を読み直してから当てる
  if(line>0&&type!=='summary')nxSrReveal(file,line,text||'',type,0);
}
function nxSrSync(){const i=nxEl('nxSrQ');if(i&&typeof i.value==='string')nxSq.q=i.value;}
function nxOnSearchClick(e){
  const t=e.target.closest('[data-sr],[data-st],[data-sq],[data-k]');
  if(!t)return;
  nxSrSync();
  if(t.dataset.sr==='go')nxSearchRun();
  else if(t.dataset.sr==='date'){nxSq.dateOpen=!nxSq.dateOpen;nxRenderSearch();}
  else if(t.dataset.st){nxSq.type=t.dataset.st;nxSearchRun();}
  else if(t.dataset.sq){
    const k=t.dataset.sq,now=new Date();
    Object.assign(nxSq,k==='clear'?{y:'',m:'',d:'',h:''}
      :{y:String(now.getFullYear()),m:nxPad2(now.getMonth()+1),d:k==='today'?nxPad2(now.getDate()):'',h:''});
    nxSearchRun();
  }else if(t.dataset.k!==undefined){
    const r=nxSq.results[+t.dataset.k];
    if(r)nxSearchOpen(r.file,r.line,r.type,r.text);
  }
}
function nxSearchInit(){
  const box=nxEl('nxSearch');
  box.addEventListener('click',nxOnSearchClick);
  box.addEventListener('change',e=>{
    const sd=e.target.dataset&&e.target.dataset.sd;
    if(sd){nxSrSync();nxSq[sd]=e.target.value;nxSearchRun();}
  });
  box.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.id==='nxSrQ'){nxSrSync();nxSearchRun();}});
  nxRenderSearch();
}
nxSearchInit();
"""
