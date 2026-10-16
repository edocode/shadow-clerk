"""Shadow-clerk daemon: ダッシュボード JavaScript (AI Console 右の文字起こしペイン)"""
from __future__ import annotations

_JS_TEMPLATE_CONSOLE_SIDE = """\
/* --- AI コンソール右の文字起こしペイン --- */
// 中身は中央の pnlT / pnlR を DOM ごと移して使う。loadT/loadR や選択・削除の
// 処理を二重に持つと、片方だけ直したときに黙ってずれる。パネルは1か所にしか
// 置けないので、移すのは AI モードの間だけ
const SIDE_MIN=200;
let sideTab='transcript';
let _sideHome=null;          // 戻す先（親と次兄弟）を覚えておく
let _muteHome=null;          // ミュート群の戻す先

function _sidePanels(){
  return {transcript:document.getElementById('pnlT'),
          translation:document.getElementById('pnlR')};
}

function switchSideTab(tab){
  sideTab=tab;
  const p=_sidePanels(), host=document.getElementById('sideHost');
  if(!host)return;
  Object.entries(p).forEach(([k,el])=>{
    if(!el)return;
    document.getElementById(k==='transcript'?'tabSideT':'tabSideR')
      .classList.toggle('active',k===tab);
    el.classList.toggle('hidden',k!==tab);
  });
}

function adoptPanelsIntoSide(){
  const host=document.getElementById('sideHost');if(!host)return;
  const p=_sidePanels();if(!p.transcript||!p.translation)return;
  if(host.contains(p.transcript))return;              // 既に移動済み
  _sideHome={parent:p.transcript.parentNode,before:p.transcript.previousSibling};
  host.appendChild(p.transcript);
  host.appendChild(p.translation);
  // ミュートとレベル計もタブバーへ連れてくる。パネルのヘッダは側ペインでは
  // 隠すので、置いていくと AI モードの間だけマイクを切れなくなる。
  // 複製ではなく移動なのは、togMute の状態表示が二重にならないようにするため
  const mg=document.getElementById('muteGroup'), mh=document.getElementById('sideMuteHost');
  if(mg&&mh){_muteHome={parent:mg.parentNode,before:mg.previousSibling};mh.appendChild(mg);}
  document.getElementById('consoleRow').classList.add('ai-mode');
  switchSideTab(sideTab);
}

function releasePanelsFromSide(){
  const row=document.getElementById('consoleRow');
  if(row)row.classList.remove('ai-mode');
  const host=document.getElementById('sideHost');
  const p=_sidePanels();
  const mg=document.getElementById('muteGroup');
  if(mg&&_muteHome){
    _muteHome.parent.insertBefore(mg,_muteHome.before?_muteHome.before.nextSibling
                                                    :_muteHome.parent.firstChild);
    _muteHome=null;
  }
  if(!host||!p.transcript||!host.contains(p.transcript)||!_sideHome)return;
  const {parent,before}=_sideHome;
  // 元の並び順に戻す。before の直後が pnlT の定位置
  parent.insertBefore(p.transcript,before?before.nextSibling:parent.firstChild);
  parent.insertBefore(p.translation,p.transcript.nextSibling);
  p.transcript.classList.remove('hidden');
  p.translation.classList.remove('hidden');
  _sideHome=null;
}

function togConsoleSide(){
  const row=document.getElementById('consoleRow');if(!row)return;
  const collapsed=row.classList.toggle('side-collapsed');
  const ch=document.getElementById('consoleSideChevron');
  if(ch)ch.innerHTML=collapsed?'&#x25C4;':'&#x25BA;';
  try{localStorage.setItem('consoleSideCollapsed',collapsed?'1':'0');}catch(e){}
  // 列数は #consolec の幅から出して PTY に送っている。幅が変わったら教える
  reportConsoleCols();
}

function initConsoleSide(){
  const row=document.getElementById('consoleRow'),
        bar=document.getElementById('consoleSplit'),
        side=document.getElementById('consoleSide');
  if(!row||!bar||!side)return;
  let w=0;
  try{w=parseInt(localStorage.getItem('consoleSideWidth')||'0',10)||0;}catch(e){}
  if(w>=SIDE_MIN)side.style.width=w+'px';
  let collapsed=false;
  try{collapsed=localStorage.getItem('consoleSideCollapsed')==='1';}catch(e){}
  row.classList.toggle('side-collapsed',collapsed);   // 記憶が無ければ開いたまま
  const ch=document.getElementById('consoleSideChevron');
  if(ch)ch.innerHTML=collapsed?'&#x25C4;':'&#x25BA;';
  switchSideTab(sideTab);
  let dragging=false;
  bar.addEventListener('mousedown',e=>{dragging=true;e.preventDefault();});
  window.addEventListener('mousemove',e=>{
    if(!dragging)return;
    const r=row.getBoundingClientRect();
    side.style.width=Math.max(SIDE_MIN,
      Math.min(r.width-SIDE_MIN-10,r.right-e.clientX))+'px';
  });
  window.addEventListener('mouseup',()=>{
    if(!dragging)return;
    dragging=false;
    const v=parseInt(side.style.width,10)||0;
    try{localStorage.setItem('consoleSideWidth',String(v));}catch(e){}
    // ドラッグ中は送らない。毎フレーム resize を投げると子が描き直し続ける
    reportConsoleCols();
  });
}

function initSumSplit(){
  const bar=document.getElementById('sumSplit'),top=document.getElementById('advWrap'),
        wrap=document.getElementById('aiWrap');
  if(!bar||!top||!wrap)return;
  // 旧バージョンは px を adviceHeight / adviceWidth に入れていた。比率へは
  // 「保存時の容器の大きさ」が無いと換算できないので、読まずに捨てる
  try{_adviceRatio=parseFloat(localStorage.getItem('adviceRatioH')||'0')||0;
      _adviceRatioW=parseFloat(localStorage.getItem('adviceRatioW')||'0')||0;}catch(e){}
  updateSumSplit();
  if(window.ResizeObserver){
    _sumSplitRO=new ResizeObserver(()=>updateSumSplit());
    _sumSplitRO.observe(wrap);
  }
  // ResizeObserver は描画に紐づくので背景タブでは動かない。window の resize も繋ぐ
  window.addEventListener('resize',updateSumSplit);
  let dragging=false;
  bar.addEventListener('mousedown',e=>{dragging=true;e.preventDefault();});
  window.addEventListener('mousemove',e=>{
    if(!dragging)return;
    const row=_sumRow(),prop=_sumProp(row),r=wrap.getBoundingClientRect();
    const pos=row?e.clientX-r.left:e.clientY-r.top;
    top.style[prop]=Math.max(SUM_SPLIT_MIN,
                             Math.min(r[prop]-SUM_SPLIT_MIN-10,pos))+'px';
  });
  window.addEventListener('mouseup',()=>{
    if(!dragging)return;
    dragging=false;
    const row=_sumRow(),prop=_sumProp(row);
    const avail=wrap.getBoundingClientRect()[prop];
    const v=parseInt(top.style[prop],10)||0;
    if(!avail||!v)return;
    const ratio=Math.min(0.95,Math.max(0.05,v/avail));
    if(row)_adviceRatioW=ratio;else _adviceRatio=ratio;
    try{localStorage.setItem(row?'adviceRatioW':'adviceRatioH',ratio.toFixed(4));}catch(e){}
  });
}

es.addEventListener('console',e=>{
  try{onConsoleEvent(JSON.parse(e.data));}catch(ex){}
});
(function initConsole(){
  const c=document.getElementById('consolec'),ti=document.getElementById('consoleInput');
  if(ti){
    // div は編集可能でないので composition イベントが来ない。入力は textarea が受ける
    ti.addEventListener('keydown',onConsoleKey);
    ti.addEventListener('paste',onConsolePaste);
    ti.addEventListener('compositionstart',onConsoleComposing);
    ti.addEventListener('compositionupdate',onConsoleComposing);
    ti.addEventListener('compositionend',onConsoleComposition);
  }
  // **mousedown ではなく click。** mousedown で focus しても、その後に走る
  // ブラウザの既定動作がフォーカスを奪い返す——クリック先の div.cr は
  // フォーカスできず、#consolec にも tabindex が無いので、focus は body へ
  // 落ちる。結果 activeElement は BODY になり、キーを打っても textarea に
  // 届かない。click は既定動作のあとに走るので、こちらなら focus が残る
  if(c){c.addEventListener('click',e=>{
      // 文字を選択したいときは邪魔しない
      if(!window.getSelection||String(window.getSelection())==='')focusConsoleInput();
    });
    c.title=I18N['dash.console_hint']||'';}
  initLogResize();
  initSumSplit();
  initConsoleSide();
  // 右ペインの開閉も同じ理由でここから。updateSumSplit が SUM_SPLIT_MIN を
  // 触るので、panels の初期化で呼ぶと TDZ で例外になり、そこから後ろの
  // loadFiles() やモーダルまで丸ごと動かなくなる。applyPanelMode より先に
  // 置くのは、AI モードのときの強制展開を上書きさせないため
  restorePanes();
  // 前回の T|R|AI をここで適用する。**panels の初期化では早すぎる**——
  // AI は分割の復元を伴い、SUM_SPLIT_MIN はこのファイルの const なので、
  // 先に呼ぶと TDZ で初期化ごと止まる
  applyPanelMode();
  applyFontSize();   // ここも同じ理由で console の初期化から（列の測り直しを伴う）
  switchLogTab('logs',{expand:false});  // 初期化ではタブの見た目だけ整え、折りたたみは変えない
  // AI 分析 (auto_analyze) が有効なときだけ、下部ペインの既定を
  // AI コンソールにする。無効なら従来どおりログのまま——コンソールを
  // 開くと grid 全体を取りに行くので、使わない人には走らせない
  fetch('/api/config').then(r=>r.json()).then(cfg=>{
    if(cfg&&cfg.auto_analyze)switchLogTab('console',{expand:false});
  }).catch(()=>{});
  // ここでは loadConsole() を呼ばない。switchLogTab('console') 内の
  // !_consoleLoaded ガードだけを唯一の起点にする。ページロードのたびに
  // 呼ぶと、大きい grid では ~480KB の応答・セッションロック下での全grid
  // レンダリング・開くとも限らないタブのための1万個の DOM 生成が毎回走る
  // window の resize だけでは幅の変化を拾いきれない（ペインの開閉、
  // 分割バーのドラッグ、タブの表示切り替えでは resize が起きない）。
  // #consolec 自身を見て、幅が変わったら列数を測り直す
  if(c&&window.ResizeObserver){
    let _lastW=0;
    _consoleRO=new ResizeObserver(entries=>{
      const w=entries[0].contentRect.width;
      if(!w||w===_lastW)return;      // 非表示 (0) と高さだけの変化は無視
      _lastW=w;scheduleConsoleCols();
    });
    _consoleRO.observe(c);
  }
  // ResizeObserver は描画に紐づくので、背景タブでは呼ばれない。window の
  // resize は届くため、両方を繋いでおく (実際の resize は _lastCols で重複を防ぐ)
  window.addEventListener('resize',scheduleConsoleCols);
  // 背景で変わった幅は、戻ってきたときに測り直す
  document.addEventListener('visibilitychange',()=>{
    if(document.visibilityState==='visible')scheduleConsoleCols();
  });
})();

/* --- 会議ごとの起動ディレクトリ --- */
let _wdOriginalPattern='';
function _meetingNameOf(file){
  const m=(file||'').match(/^transcript-\\d+@(.+)\\.txt$/);
  return m?m[1]:'';
}
async function openWorkdirModal(file){
  const name=_meetingNameOf(file);
  let cfg={rules:[],default_workdir:'',path:''};
  try{cfg=await(await fetch('/api/meeting-config')).json();}catch(e){}
  // 会議名に当たる既存ルールがあればそれを編集する。無ければ会議名から素案を作る。
  // 素案は編集可能なままにする——表記ゆれをどこまで拾うかは人が決める話なので、
  // 機械が推定したパターンをそのまま保存させない
  let rule=null;
  for(const r of (cfg.rules||[])){
    try{if(new RegExp(r.pattern,'i').test(name)){rule=r;break;}}catch(e){}
  }
  _wdOriginalPattern=rule?rule.pattern:'';
  document.getElementById('wdMeeting').textContent=name||file||'';
  document.getElementById('wdPattern').value=rule?rule.pattern:_escRegex(name);
  document.getElementById('wdPath').value=rule?rule.workdir:'';
  document.getElementById('wdDefault').textContent=
    (I18N['dash.workdir_default']||'Default: {path}').replace('{path}',cfg.default_workdir||'-');
  document.getElementById('wdFile').textContent=
    (I18N['dash.workdir_file']||'Config file: {path}').replace('{path}',cfg.path||'-');
  document.getElementById('wdSaved').style.display='none';
  // 削除できるのは _wdOriginalPattern（読み込み時に一致した既存ルール）だけ。
  // 一致するルールが無い会議には削除するものが無いのでボタンごと隠す
  document.getElementById('wdDeleteBtn').style.display=_wdOriginalPattern?'':'none';
  document.getElementById('workdirModal').classList.add('open');
}
function _escRegex(s){return (s||'').replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&');}
function closeWorkdirModal(){document.getElementById('workdirModal').classList.remove('open');}
async function _postWorkdir(body){
  try{const r=await fetch('/api/meeting-config',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(d.status!=='ok'){alert(d.message||'error');return false;}
    return true;
  }catch(e){return false;}
}
async function saveWorkdir(){
  const pattern=document.getElementById('wdPattern').value.trim();
  const workdir=document.getElementById('wdPath').value.trim();
  if(!pattern)return;
  // リネームを1リクエストにまとめる。旧パターンの削除→新パターンの upsert を
  // 2本の POST に分けると、1本目が通って2本目が失敗した(設定ディレクトリが
  // 書けない、デーモン再起動中)ときに古いルールが消えたまま新しい方が
  // 書かれず、ユーザーがマッピングを黙って失う
  const body={pattern,workdir};
  if(_wdOriginalPattern&&_wdOriginalPattern!==pattern)body.old_pattern=_wdOriginalPattern;
  if(!await _postWorkdir(body))return;
  _wdOriginalPattern=pattern;
  const s=document.getElementById('wdSaved');s.style.display='';
  setTimeout(()=>{s.style.display='none';},1500);
}
async function deleteWorkdirRule(){
  // フィールドの現在値ではなく、モーダルを開いたときに一致した既存ルールを消す。
  // pattern を編集してから削除を押しても、編集後の(設定ファイルに無い)値を
  // 削除対象にして黙って空振りしないようにするため
  const pattern=_wdOriginalPattern;
  if(!pattern)return;
  if(!await _postWorkdir({pattern,delete:true}))return;
  closeWorkdirModal();
}
"""
