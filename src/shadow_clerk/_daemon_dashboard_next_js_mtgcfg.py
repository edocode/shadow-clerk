"""Shadow-clerk daemon: /next ダッシュボード JavaScript — 会議ごとの設定モーダル（試作 dashboard-friendly-ui-mtgcfg.js が元）"""
from __future__ import annotations

# API は GET/POST /api/meeting-settings（現行 _daemon_dashboard_js_meeting_settings.py と同じ扱い）。
# 変えられるのは 6 項目だけ。既定（defaults）の編集やルールの並べ替えは API に無いので描かない。
# pend は保存前の変更で、API に送る形（analyze は true / false / "default"）のまま持つ
_NEXT_JS_MTGCFG = r"""
/* --- 会議ごとの設定: 会議をチェックで選び、選んだ会議にまとめて値を設定する --- */
const nxMc={rows:[],sel:new Set(),pend:{},path:'',auto:false,after:null,loadErr:false};
const nxMcFields=[
  ['nx.mc_g_ai',[['analyze','analyze'],['workdir','text']]],
  ['nx.mc_g_publish',[['publish','bool'],['publish_to','dest'],['notion_url','text'],['publish_advice','bool']]],
];
const nxMcTypes=Object.fromEntries(nxMcFields.flatMap(g=>g[1]));
function nxMcOptions(type){
  if(type==='analyze')return [['default',nxFmt('nx.mc_analyze_default',{v:I18N[nxMc.auto?'nx.mc_on':'nx.mc_off']})],
    ['true',I18N['nx.mc_on']],['false',I18N['nx.mc_off']]];
  if(type==='bool')return [['1',I18N['nx.mc_yes']],['0',I18N['nx.mc_no']]];
  return [['artifact',I18N['nx.mc_to_artifact']],['notion',I18N['nx.mc_to_notion']]];
}
/* 値 ⇔ 画面の文字列。analyze の null（会議ごとの指定なし）は "default" と同じ */
function nxMcEnc(k,v){
  const t=nxMcTypes[k];
  return t==='analyze'?(v==null?'default':String(v)):t==='bool'?(v?'1':'0'):(v||'');
}
function nxMcDec(k,s){
  const t=nxMcTypes[k];
  return t==='analyze'?(s==='default'?'default':s==='true'):t==='bool'?s==='1':t==='text'?s.trim():s;
}
function nxMcSelRows(){return [...nxMc.sel].map(n=>nxMc.rows.find(r=>r.name===n)).filter(Boolean);}
/* 選んだ会議での値: 保存前の変更があればそれ、なければ今の値。会議によって違えば same:false */
function nxMcValue(k){
  const encs=nxMcSelRows().map(r=>nxMcEnc(k,r[k])),same=encs.every(v=>v===encs[0]);
  if(k in nxMc.pend)return {v:nxMcEnc(k,nxMc.pend[k]),same:true,changed:true,cur:encs[0],curSame:same};
  return {v:encs[0],same,changed:false,cur:encs[0],curSame:same};
}
/* 今の値と同じなら変更にしない。値が違う会議の文字列項目を空欄にしたときも変えない */
function nxMcEdit(k,raw){
  const v=nxMcDec(k,raw),r=nxMcValue(k);
  delete nxMc.pend[k];
  if(r.curSame?nxMcEnc(k,v)!==r.cur:!(nxMcTypes[k]==='text'&&v===''))nxMc.pend[k]=v;
  nxMcRenderEd();
}
function nxMcVisible(){
  const q=nxEl('nxMcQ').value.trim().toLowerCase(),only=nxEl('nxMcOnly').checked;
  return nxMc.rows.filter(r=>r.name.toLowerCase().includes(q)&&(!only||r.matched!=='(defaults)'));
}
function nxMcNote(r){
  if(r.matched==='(defaults)')return '<span class="muted">'+nxEsc(I18N['nx.mc_uses_defaults'])+'</span>';
  if(!r.shared)return '';
  return '<span class="muted">'+nxEsc(I18N['nx.mc_shared_rule']).split('{rule}').join('<code>'+nxEsc(r.matched)+'</code>')+'</span>';
}
function nxMcRenderList(){
  const vis=nxMcVisible();
  nxEl('nxMcItems').innerHTML=vis.map(r=>{
    const on=nxMc.sel.has(r.name);
    return '<label class="cfg-li mrow'+(on?' act':'')+'"><input type="checkbox" data-pick="'+nxEsc(r.name)+'"'+(on?' checked':'')+'>'
      +'<div><b>'+nxEsc(r.name)+'</b> <span class="muted ts">'+nxEsc(r.last)+'</span>'
      +'<div class="s">'+nxStChips(r).map(c=>'<span class="chip">'+nxEsc(c)+'</span>').join('')+' '+nxMcNote(r)+'</div></div></label>';
  }).join('')||'<div class="hint">'+nxEsc(I18N[nxMc.loadErr?'nx.mc_load_failed':'nx.mc_none_match'])+'</div>';
  nxEl('nxMcAll').checked=vis.length>0&&vis.every(r=>nxMc.sel.has(r.name));
}
function nxMcCtl(k,r){
  const type=nxMcTypes[k],mixed=!r.same;
  if(type==='text'){
    const ph=mixed?I18N['nx.mc_mixed_ph']:k==='workdir'?I18N['nx.mc_workdir_ph']:'https://';
    return '<input data-k="'+k+'" value="'+nxEsc(mixed?'':r.v)+'" placeholder="'+nxEsc(ph)+'">';
  }
  return '<select data-k="'+k+'">'+(mixed?'<option selected disabled>'+nxEsc(I18N['nx.mc_mixed'])+'</option>':'')
    +nxMcOptions(type).map(([o,l])=>'<option value="'+o+'"'+(!mixed&&o===r.v?' selected':'')+'>'+nxEsc(l)+'</option>').join('')+'</select>';
}
function nxMcRenderEd(){
  const names=[...nxMc.sel],ed=nxEl('nxMcEd');
  if(!names.length){
    ed.innerHTML='<h4>'+nxEsc(I18N['nx.mc_pick_title'])+'</h4><div class="hint">'+nxEsc(I18N['nx.mc_pick_hint'])+'</div>';
    return;
  }
  const shared=nxMcSelRows().filter(r=>r.shared).map(r=>r.name);
  let html='<h4>'+nxEsc(names.length===1?names[0]:nxFmt('nx.mc_n_meetings',{n:names.length}))+'</h4><div class="hint">'
    +(names.length>1?nxEsc(nxFmt('nx.mc_bulk',{names:names.join('、')})):'')+nxEsc(I18N['nx.mc_only_changed'])+'</div>'
    +(shared.length?'<div class="hint warn">'+nxEsc(nxFmt('nx.mc_shared_warn',{names:shared.join('、')}))+'</div>':'');
  nxMcFields.forEach(([g,fields])=>{
    html+='<div class="cfg-g">'+nxEsc(I18N[g])+'</div>'+fields.map(([k])=>{
      const r=nxMcValue(k),hint=I18N['nx.mc_'+k+'_hint'];
      return '<div class="cfg-row"><div class="cfg-lab">'+nxEsc(I18N['nx.mc_'+k])+(hint?'<div class="hint">'+nxEsc(hint)+'</div>':'')+'</div>'
        +'<div class="cfg-ctl">'+nxMcCtl(k,r)+'<div class="st-line">'
        +(r.changed?'<span class="st cu">'+nxEsc(nxFmt('nx.mc_will_set',{n:names.length}))+'</span>':'')+'</div></div></div>';
    }).join('');
  });
  ed.innerHTML=html;
}
function nxMcRender(){nxMc.pend={};nxEl('nxMcErr').textContent='';nxMcRenderList();nxMcRenderEd();}
/* 一覧は記録のある会議名（名前なし・日次は除く）。開始モーダルから来た、まだ記録の無い名前も足す */
async function nxMcLoad(extra){
  const groups=nxMeetingGroups(nxFiles),names=[...groups.keys()];
  if(extra&&!groups.has(extra))names.unshift(extra);
  const q=names.map(n=>'meeting='+encodeURIComponent(n)).join('&');
  const [d,auto]=await Promise.all([names.length?nxApi('/api/meeting-settings?'+q).catch(()=>null):null,nxAutoAnalyze()]);
  nxMc.auto=auto;nxMc.path=d&&d.path||'';nxMc.loadErr=names.length>0&&!(d&&d.meetings);
  nxMc.rows=(d&&d.meetings||[]).map(m=>{
    const fs=groups.get(m.name);
    return {...m,last:fs?nxFmtDt(fs[0].dt):I18N['nx.mc_no_record']};
  });
  nxEl('nxMcPath').textContent=nxMc.path?nxFmt('nx.mc_path',{path:nxMc.path}):'';
}
/* after: 閉じたあとに呼ぶ（開始モーダルの「変更」から来たら開始モーダルに戻す） */
async function nxOpenMeetingSettings(name,after){
  nxMc.after=after||null;
  nxMc.sel=new Set(name?[name]:[]);
  nxEl('nxMcQ').value='';nxEl('nxMcOnly').checked=false;
  nxMc.rows=[];nxMc.loadErr=false;nxMcRender();
  nxModal('nxMcModal',true);
  await nxMcLoad(name);
  nxMcRender();
}
function nxMcClose(){
  nxModal('nxMcModal',false);
  const f=nxMc.after;nxMc.after=null;
  if(f)f();
}
/* 公開先が Notion になる会議は https:// の URL が要る（現行と同じ、空欄も不可） */
function nxMcUrlOk(set){
  if(set.notion_url&&!/^https:\/\//.test(set.notion_url))return false;
  if(!('publish_to' in set||'notion_url' in set))return true;
  return nxMcSelRows().every(r=>{
    const to=set.publish_to??r.publish_to,url=('notion_url' in set?set.notion_url:r.notion_url)||'';
    return to!=='notion'||/^https:\/\//.test(url);
  });
}
async function nxMcSave(){
  const names=[...nxMc.sel],set={...nxMc.pend},err=nxEl('nxMcErr');
  if(!names.length||!Object.keys(set).length){nxToast(I18N['nx.mc_nothing']);nxMcClose();return;}
  if(!nxMcUrlOk(set)){err.textContent=I18N['nx.mc_notion_bad'];return;}
  let r=null;
  try{r=await nxApi('/api/meeting-settings',{meetings:names,set});}catch(e){}
  if(!r||r.status!=='ok'){err.textContent=r&&r.message||I18N['nx.mc_save_failed'];return;}
  nxToast(nxFmt('nx.mc_saved',{n:names.length}));
  nxMcClose();
}
function nxMtgCfgInit(){
  nxEl('nxMcQ').addEventListener('input',nxMcRenderList);
  nxEl('nxMcOnly').addEventListener('change',nxMcRenderList);
  nxEl('nxMcAll').addEventListener('change',e=>{
    nxMcVisible().forEach(r=>e.target.checked?nxMc.sel.add(r.name):nxMc.sel.delete(r.name));
    nxMcRender();
  });
  nxEl('nxMcItems').addEventListener('change',e=>{
    const n=e.target.dataset.pick;
    if(n===undefined)return;
    e.target.checked?nxMc.sel.add(n):nxMc.sel.delete(n);
    nxMcRender();
  });
  nxEl('nxMcEd').addEventListener('change',e=>{if(e.target.dataset.k)nxMcEdit(e.target.dataset.k,e.target.value);});
  // 文字の項目の Enter で保存する。change より先に来るので値をここで取り込む。日本語入力の確定の Enter は除く
  nxEl('nxMcEd').addEventListener('keydown',e=>{
    const k=e.target.dataset&&e.target.dataset.k;
    if(e.key!=='Enter'||e.isComposing||nxMcTypes[k]!=='text')return;
    e.preventDefault();nxMcEdit(k,e.target.value);nxMcSave();
  });
  nxEl('nxMcClose').addEventListener('click',nxMcClose);
  nxEl('nxMcCancel').addEventListener('click',nxMcClose);
  nxEl('nxMcSave').addEventListener('click',nxMcSave);
  nxEl('nxMiMtgCfg').addEventListener('click',()=>{nxCloseMenus(null);nxOpenMeetingSettings();});
}
nxMtgCfgInit();
"""
