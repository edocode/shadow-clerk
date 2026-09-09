"""Shadow-clerk daemon: ダッシュボード JavaScript (AI Console)"""

_JS_TEMPLATE_CONSOLE = """\
/* --- AI Console --- */
let logTab='logs';
let _consoleRows={};        // 行番号 -> DOM 要素
let _consoleMaxRow=-1;      // 未作成。0 にすると 0 行目が飛ばされる
let _consoleKeep=-1;        // ここまでを表示する。これより下の空行は畳む
let _consoleTrimmed=-1;     // 前回畳んだときの _consoleMaxRow
const CONSOLE_CURSOR_NEAR=100;  // カーソルが本文からこれ以上離れたら表示を伸ばさない
let _consoleLoaded=false;
let _consoleRunning=null;   // 遷移検出用。初回誤発火を防ぐため未知状態から始める
let _sumSplitRO=null;

/* tab 引数はタブの見た目切り替え。opts.expand=false のときは折りたたみを解除しない
   (ページ初期化時に呼ばれても勝手にログパネルを開かないようにするため) */
function switchLogTab(tab,opts){
  opts=opts||{};
  logTab=tab;
  const lp=document.getElementById('logp');
  if(opts.expand!==false&&lp.classList.contains('collapsed'))togLogs();
  document.getElementById('tabLogs').classList.toggle('active',tab==='logs');
  document.getElementById('tabConsole').classList.toggle('active',tab==='console');
  document.getElementById('logc').style.display=(tab==='logs')?'':'none';
  document.getElementById('consolec').style.display=(tab==='console')?'':'none';
  if(tab==='console'){
    if(!_consoleLoaded)loadConsole();
    focusConsoleInput();
    reportConsoleCols();
    scrollConsoleBottom();
  }
}

/* サーバが送ってくる色名のホワイトリスト。未知の値は class に流さない
   (エスケープではなくホワイトリストにすることで、未知値が CSS クラス空間に漏れない)。
   pyte の呼び名に合わせること——30-37 は brown (yellow ではない)、
   90-97 は bright*。bfightmagenta は pyte 側の綴り誤りだが、そのまま届く */
const _CONSOLE_COLOR_NAMES=['black','red','green','brown','blue','magenta','cyan','white',
  'brightblack','brightred','brightgreen','brightbrown','brightblue','brightmagenta',
  'brightcyan','brightwhite','bfightmagenta'];
/* 256色・24bit色は名前ではなく 6桁の16進で来るのでクラスに落とせない。
   16進であることを厳密に確かめてからインラインで当てる */
const _CONSOLE_HEX=/^[0-9a-f]{6}$/;

/* 色つきの [text, style] ラン列を span に変換する */
function _consoleSpan(text,style){
  if(style==='default')return esc(text);
  const cls=[];let css='';
  style.split(',').forEach(s=>{
    if(s.startsWith('fg:')||s.startsWith('bg:')){
      const fg=s[0]==='f',c=s.slice(3);
      if(_CONSOLE_COLOR_NAMES.includes(c))cls.push((fg?'cfg-':'cbg-')+c);
      else if(_CONSOLE_HEX.test(c))css+=(fg?'color':'background')+':#'+c+';';
    }
    else if(s==='bold'||s==='italic'||s==='underline'||s==='strike'||s==='reverse'||s==='dim')cls.push('cs-'+s);
  });
  if(!cls.length&&!css)return esc(text);
  return '<span'+(cls.length?' class="'+cls.join(' ')+'"':'')
    +(css?' style="'+css+'"':'')+'>'+esc(text)+'</span>';
}

/* 端末は最下部が現在地。開いた直後は必ずそこを見せる。

   applyConsole の追従だけでは足りない。#logp が畳まれている間 #consolec は
   display:none で clientHeight も scrollHeight も 0 なので、そこで scrollTop に
   書いても何も起きず、開いたときに先頭のままになる。 */
function scrollConsoleBottom(){
  const c=document.getElementById('consolec');
  if(c&&c.clientHeight)c.scrollTop=c.scrollHeight;
}

function _consoleRowEl(y){
  let el=_consoleRows[y];
  if(el)return el;
  const c=document.getElementById('consolec');
  // 行は必ず番号順に並べる。飛び番が来ても間を空行で埋めてから挿入する
  for(let i=_consoleMaxRow+1;i<=y;i++){
    if(_consoleRows[i])continue;
    const d=document.createElement('div');d.className='cr';d.dataset.y=String(i);
    c.appendChild(d);_consoleRows[i]=d;
  }
  _consoleMaxRow=Math.max(_consoleMaxRow,y);
  if(!_consoleRows[y]){
    const d=document.createElement('div');d.className='cr';d.dataset.y=String(y);
    c.appendChild(d);_consoleRows[y]=d;
  }
  return _consoleRows[y];
}

function applyConsole(d){
  if(d.status_only){
    updateConsoleStatus(d.running);
    if(d.auto)showAutoAnalysis();
    return;
  }
  const cc=document.getElementById('consolec');
  // 「下端にいたか」は行を足す前に捕まえる。あとで測ると scrollHeight が
  // 既に伸びていて条件が必ず偽になり、出力が増えても追従しなくなる
  const wasBottom=!cc||nearBottom(cc);
  if(d.full){
    // 行だけを消す。innerHTML='' にすると #consolec の子である
    // #consoleInput (IME を受ける textarea) まで消えてしまい、
    // 以後キー入力が一切通らなくなる——full は毎回のロードで来る
    cc.querySelectorAll('.cr').forEach(el=>el.remove());
    _consoleRows={};_consoleMaxRow=-1;_consoleKeep=-1;_consoleTrimmed=-1;
  }
  const rows=d.rows||{};
  Object.keys(rows).map(Number).sort((a,b)=>a-b).forEach(y=>{
    const el=_consoleRowEl(y);
    el.innerHTML=(rows[String(y)]||[]).map(r=>_consoleSpan(r[0],r[1])).join('')||'';
  });
  updateConsoleStatus(d.running);
  _trimConsoleTail(d.cursor?d.cursor[0]:-1);
  _updateConsoleCursor(d.cursor);
  // 下端付近にいたときだけ追従する（Logs ペインと同じ方針）
  if(cc&&wasBottom)cc.scrollTop=cc.scrollHeight;
}

/* キャレット表示。入力待ち(最も多い状態)で画面が死んで見えないよう、
   カーソル位置に薄いブロックを重ねる。等幅フォント + white-space:pre
   なので、実測せず ch 単位で列位置をそのまま表せる */
function _moveConsoleInput(left,top){
  const t=document.getElementById('consoleInput');
  if(t){t.style.left=left;t.style.top=top;}
}
function _updateConsoleCursor(cursor){
  if(!cursor)return;
  const c=document.getElementById('consolec');
  let el=document.getElementById('consoleCursor');
  if(!el){el=document.createElement('div');el.id='consoleCursor';el.className='ccursor';c.appendChild(el);}
  const row=_consoleRowEl(cursor[0]);
  el.style.top=row.offsetTop+'px';
  // #consolec は position:relative の padding box が包含ブロックになるので、
  // left:0 は本文の1列目より padding-left ぶん左にずれる。8px をここに
  // ハードコードせず、実際に効いている CSS の padding-left を読んで補正する
  const left='calc('+getComputedStyle(c).paddingLeft+' + '+cursor[1]+'ch)';
  el.style.left=left;
  // IME の変換候補ウィンドウはフォーカス中の要素の位置に出る。textarea を
  // カーソルに重ねておかないと、画面の隅に候補が出て打ちにくい
  _moveConsoleInput(left,row.offsetTop+'px');
}

/* 入力位置の下に空行が積み上がるのを防ぐ。

   サーバの max_row は cursor.y の高水位で、減らない。TUI が長い出力を出したあと
   cursor up で上の方だけ描き直すと、その下は空になっても max_row は深いままで、
   クライアントは max_row まで .cr (min-height:1.35em) を作り続ける。
   出力が増えるほど空行も増えるのはこのため。

   末尾の空行だけを display:none で畳む。行そのものは消さない——後で同じ行に
   書き戻されることがあるし、消すと番号と DOM の対応が崩れる。
   カーソル行は空でも残す。畳むと打ち込み先が画面から消える。 */
function _trimConsoleTail(cursorY){
  let last=-1;
  for(let y=_consoleMaxRow;y>=0;y--){                 // 通常は 1〜2 回で止まる
    const el=_consoleRows[y];
    if(el&&el.innerHTML!==''){last=y;break;}
  }
  // カーソルが本文から大きく離れているときは、そこまで伸ばさない。grid は
  // 1万行あるので、TUI が深い行へ飛ぶとその間の空行を全部見せることになる。
  const cy=cursorY|0;
  const keep=(cy>=0&&cy<=last+CONSOLE_CURSOR_NEAR)?Math.max(last,cy):last;
  // keep が同じでも、前回以降に行が増えていればその行は素のまま残っている。
  // TUI が消去した深い行も dirty として届くので _consoleRowEl が div を作り、
  // 畳まないと入力行の下に空行として積み上がる
  if(keep===_consoleKeep&&_consoleMaxRow===_consoleTrimmed)return;
  // 変化した範囲だけ触る。毎 tick で 10000 行を舐めない
  const lo=Math.min(keep,_consoleKeep);
  const hi=Math.max(keep,_consoleKeep,_consoleMaxRow);
  for(let y=lo+1;y<=hi;y++){
    const el=_consoleRows[y];
    if(el)el.style.display=(y>keep)?'none':'';
  }
  _consoleKeep=keep;_consoleTrimmed=_consoleMaxRow;
}

function updateConsoleStatus(running){
  const s=document.getElementById('consoleStatus');
  const b=document.getElementById('btnConsoleStop');
  if(s)s.textContent=running?'\\u25cf running':'\\u25cb stopped';
  if(b)b.style.display=running?'':'none';
  // 開始/停止は1つのボタンで受ける
  const t=document.getElementById('btnStartAnalysis');
  if(t){
    t.textContent=running?(I18N['dash.stop_analysis']||'Stop analysis')
                         :(I18N['dash.start_analysis']||'Start analysis');
    t.title=running?(I18N['dash.stop_analysis_title']||'')
                   :(I18N['dash.start_analysis_title']||'');
  }
  // アシスタント再起動時、サーバの grid はリセットされるがクライアントには
  // 消去の合図が来ない。false→true の遷移を検出して snapshot を取り直す
  // 「まだ走っていると分かっていない」→「走っている」の全てで送り直す。
  // false→true に限ると、ページを開いた時点で既に走っている子 (会議開始と
  // 同時の自動起動が典型) には幅が一度も届かない
  if(_consoleRunning!==true&&running===true){
    _lastCols=0;reportConsoleCols();loadConsole();
  }
  _consoleRunning=running;
}

/* 自動で分析が始まったときの見せ方。ユーザーは会議を始めただけで
   分析が走ることを知らないので、生成物とコンソールの両方を開く */
function showAutoAnalysis(){
  const pnl=document.getElementById('pnlS');
  if(pnl&&pnl.classList.contains('collapsed'))togSumPane();
  switchSumTab('ai');
  switchLogTab('console');
}

async function loadConsole(){
  try{const d=await(await fetch('/api/console')).json();
    _consoleLoaded=true;applyConsole(d);
  }catch(e){}
}

async function stopConsole(){
  if(!confirm(I18N['dash.console_stop_confirm']||'Stop?'))return;
  try{await fetch('/api/console/stop',{method:'POST',
    headers:{'Content-Type':'application/json'},body:'{}'});}catch(e){}
}

async function sendConsole(data){
  try{await fetch('/api/console/input',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({data})});}catch(e){}
}

/* キーコードを端末のエスケープシーケンスに直す */
const _CONSOLE_KEYS={
  Enter:'\\r',Tab:'\\t',Backspace:'\\x7f',Escape:'\\x1b',
  ArrowUp:'\\x1b[A',ArrowDown:'\\x1b[B',ArrowRight:'\\x1b[C',ArrowLeft:'\\x1b[D',
  Home:'\\x1b[H',End:'\\x1b[F',PageUp:'\\x1b[5~',PageDown:'\\x1b[6~',Delete:'\\x1b[3~',
};
function onConsoleKey(e){
  if(e.isComposing||e.keyCode===229)return;  // IME 合成中のキーは送らない(229は旧ブラウザ向け)
  if(e.metaKey)return;
  if(e.ctrlKey){
    // Ctrl-C / Ctrl-D などは制御文字に落とす。Ctrl-Shift-C はコピーに通す
    if(e.shiftKey&&(e.key==='C'||e.key==='c'||e.key==='V'||e.key==='v'))return;
    const k=e.key.toLowerCase();
    if(k.length===1&&k>='a'&&k<='z'){
      e.preventDefault();sendConsole(String.fromCharCode(k.charCodeAt(0)-96));return;
    }
    return;
  }
  // Alt は端末では ESC 前置 (Meta)。claude の Alt+Enter による改行がこれで、
  // 素通しすると Enter が「送信」に化けて改行できない。
  // AltGr は altKey と ctrlKey が同時に立つので、それは通常入力として扱う
  if(e.altKey&&!e.ctrlKey){
    const body=_CONSOLE_KEYS[e.key]||(e.key.length===1?e.key:'');
    if(body){e.preventDefault();sendConsole('\x1b'+body);return;}
  }
  const mapped=_CONSOLE_KEYS[e.key];
  if(mapped){e.preventDefault();sendConsole(mapped);return;}
  if(e.key.length===1){e.preventDefault();sendConsole(e.key);}
}
/* サーバの上限(8192文字)を超える貼り付けは、切り捨てずにチャンク分割して順に送る */
const CONSOLE_INPUT_CHUNK=8192;
/* IME で確定したテキストを送る。onConsoleKey は合成中のキーを捨てるだけなので、
   これが無いと日本語がひとつも入らない。keydown で拾える文字ではないため
   compositionend の data を使う */
function onConsoleComposition(e){
  const t=e.data;
  // textarea には変換中の文字が残っている。送ったあと必ず空にする——
  // 残すと次の入力に混ざり、送信済みの文字が二重に届く
  if(e.target)e.target.value='';
  if(t)sendConsole(t);
}
/* 端末の入力は textarea が受ける。#consolec をクリックしたときもそちらへ移す */
function focusConsoleInput(){
  const t=document.getElementById('consoleInput');
  if(t)t.focus({preventScroll:true});
}
async function onConsolePaste(e){
  e.preventDefault();
  const text=(e.clipboardData||window.clipboardData).getData('text');
  if(!text)return;
  for(let i=0;i<text.length;i+=CONSOLE_INPUT_CHUNK){
    await sendConsole(text.slice(i,i+CONSOLE_INPUT_CHUNK));
  }
}

/* 表示幅から列数を割り出して PTY に伝える。行数は触らない。

   **束ねること。** window の resize は掴んで動かしている間ずっと発火するので、
   素で繋ぐと毎フレーム PTY をリサイズして SIGWINCH を送りつけることになる。
   TUI (Ink) はフレームを描いている最中に何度も再レイアウトを強いられ、
   前フレームを消しきらないまま書き直すため、罫線の残骸がセルに残る
   （`ab───cd───` のような崩れ方をする）。あわせて毎回 grid 全体も取り直す。 */
const CONSOLE_RESIZE_DEBOUNCE_MS=250;
let _lastCols=0,_colsTimer=null,_consoleRO=null;
function scheduleConsoleCols(){
  if(_colsTimer)clearTimeout(_colsTimer);
  _colsTimer=setTimeout(()=>{_colsTimer=null;reportConsoleCols();},CONSOLE_RESIZE_DEBOUNCE_MS);
}
async function reportConsoleCols(){
  const c=document.getElementById('consolec');if(!c||!c.clientWidth)return;
  const probe=document.createElement('span');
  probe.style.cssText='position:absolute;visibility:hidden;white-space:pre';
  probe.textContent='0'.repeat(100);c.appendChild(probe);
  const per=probe.getBoundingClientRect().width/100;probe.remove();
  if(!per)return;
  const cols=Math.max(40,Math.min(400,Math.floor((c.clientWidth-16)/per)));
  if(cols===_lastCols)return;
  _lastCols=cols;
  try{await fetch('/api/console/resize',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({cols})});}catch(e){}
  loadConsole();  // 列数が変わると grid 全体が組み直されるので取り直す
}

/* Logs ペインの高さをドラッグで変える。TUI には 180px では狭い */
function initLogResize(){
  const bar=document.getElementById('logResize'),lp=document.getElementById('logp');
  if(!bar||!lp)return;
  let saved=0;
  try{saved=parseInt(localStorage.getItem('logHeight')||'0',10);}catch(e){}
  if(saved>=120)lp.style.height=saved+'px';
  let dragging=false;
  bar.addEventListener('mousedown',e=>{dragging=true;e.preventDefault();});
  window.addEventListener('mousemove',e=>{
    if(!dragging)return;
    const h=Math.max(120,Math.min(window.innerHeight-160,window.innerHeight-e.clientY));
    lp.style.height=h+'px';
  });
  window.addEventListener('mouseup',()=>{
    if(!dragging)return;
    dragging=false;
    try{localStorage.setItem('logHeight',String(parseInt(lp.style.height,10)||180));}catch(e){}
    scheduleConsoleCols();
  });
}

/* 提案(上) と分析(下) の仕切り。logResize と同じ流儀で高さを localStorage に残す */
/* 提案/分析の上下分割。SUM_SPLIT_MIN はどちらのペインにも残す最低の高さ */
const SUM_SPLIT_MIN=60;
let _adviceWant=0;      // ユーザーが決めた高さ。容器に合わせて挟むが、この値自体は動かさない
/* 保存した高さは「保存した時点のペイン高さ」に対する値でしかない。ウィンドウを
   狭めたり下部ペインを広げたりすると容器を超え、下の分析ペインが 0 近くまで
   潰れる（実際 aiWrap 745px に対し advWrap が 923px になっていた）。
   容器の高さが変わるたびに挟み直す。_adviceWant は書き換えないので、
   容器が広がれば元の高さに戻る */
function clampSumSplit(){
  const top=document.getElementById('advWrap'),wrap=document.getElementById('aiWrap');
  if(!top||!wrap)return;
  const avail=wrap.getBoundingClientRect().height;
  if(avail<SUM_SPLIT_MIN*2+10)return;   // 畳んでいる、または測れない
  const cur=parseInt(top.style.height,10)||Math.round(top.getBoundingClientRect().height);
  const h=Math.round(Math.max(SUM_SPLIT_MIN,
                              Math.min(avail-SUM_SPLIT_MIN-10,_adviceWant||cur)));
  if(h!==cur)top.style.height=h+'px';
}
function initSumSplit(){
  const bar=document.getElementById('sumSplit'),top=document.getElementById('advWrap'),
        wrap=document.getElementById('aiWrap');
  if(!bar||!top||!wrap)return;
  try{_adviceWant=parseInt(localStorage.getItem('adviceHeight')||'0',10)||0;}catch(e){}
  if(_adviceWant>=SUM_SPLIT_MIN)top.style.height=_adviceWant+'px';
  clampSumSplit();
  if(window.ResizeObserver){
    _sumSplitRO=new ResizeObserver(()=>clampSumSplit());
    _sumSplitRO.observe(wrap);
  }
  // ResizeObserver は描画に紐づくので背景タブでは動かない。window の resize も繋ぐ
  window.addEventListener('resize',clampSumSplit);
  let dragging=false;
  bar.addEventListener('mousedown',e=>{dragging=true;e.preventDefault();});
  window.addEventListener('mousemove',e=>{
    if(!dragging)return;
    const r=wrap.getBoundingClientRect();
    const h=Math.max(SUM_SPLIT_MIN,
                     Math.min(r.height-SUM_SPLIT_MIN-10,e.clientY-r.top));
    top.style.height=h+'px';
  });
  window.addEventListener('mouseup',()=>{
    if(!dragging)return;
    dragging=false;
    _adviceWant=parseInt(top.style.height,10)||0;
    try{localStorage.setItem('adviceHeight',String(_adviceWant));}catch(e){}
  });
}

es.addEventListener('console',e=>{
  try{applyConsole(JSON.parse(e.data));}catch(ex){}
});
(function initConsole(){
  const c=document.getElementById('consolec'),ti=document.getElementById('consoleInput');
  if(ti){
    // div は編集可能でないので composition イベントが来ない。入力は textarea が受ける
    ti.addEventListener('keydown',onConsoleKey);
    ti.addEventListener('paste',onConsolePaste);
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
  try{cfg=await(await fetch('/api/mtg-config')).json();}catch(e){}
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
  try{const r=await fetch('/api/mtg-config',{method:'POST',
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
