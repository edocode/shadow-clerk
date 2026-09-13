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
  document.getElementById('consoleRow').style.display=(tab==='console')?'':'none';
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
  const l=document.getElementById('btnConsoleLaunch');
  if(l)l.style.display=running?'none':'';
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

/* 初期プロンプトを送らずに端末だけ出す。前のセッションを /resume で
   拾い直したいときに使う——プロンプトが入ると拾う前に会話が始まる */
async function launchConsole(){
  const btn=document.getElementById('btnConsoleLaunch');
  if(btn){if(btn.disabled)return;btn.disabled=true;}
  const body=JSON.stringify(curFile?{transcript:curFile,prompt:false}:{prompt:false});
  try{const d=await(await fetch('/api/console/start',{method:'POST',
    headers:{'Content-Type':'application/json'},body})).json();
    if(d.status!=='ok')alert(I18N['dash.console_start_failed']||'Failed to start the AI assistant.');
    else switchLogTab('console');
  }catch(e){}
  finally{if(btn)btn.disabled=false;}
}
async function stopConsole(){
  if(!confirm(I18N['dash.console_stop_confirm']||'Stop?'))return;
  try{await fetch('/api/console/stop',{method:'POST',
    headers:{'Content-Type':'application/json'},body:'{}'});}catch(e){}
}

/* キー入力は**必ず打った順に**届ける。1打ごとに fetch を投げっぱなしにすると、
   同時に飛んだ POST がサーバ側で別スレッドに載って追い越す——実測で "hello123"
   が "holle123" になった。前の送信が終わってから次を送る。localhost なので
   1往復は 1ms 程度で、直列にしても打鍵に追いつく */
let _consoleSendQ=Promise.resolve();
function sendConsole(data){
  const next=()=>_postConsole(data);
  _consoleSendQ=_consoleSendQ.then(next,next);   // 失敗しても列は止めない
  return _consoleSendQ;
}
async function _postConsole(data){
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
/* 変換中の文字列が占めるセル数。CJK は 2 セル分の幅を取る。
   端末と同じ数え方(East Asian Wide / Fullwidth)にしておかないと、
   変換中の箱が文字より狭くなって末尾が隠れる */
function _consoleCells(s){
  let n=0;
  for(const ch of s){
    const c=ch.codePointAt(0);
    const wide=c>=0x1100&&(c<=0x115f||c===0x2329||c===0x232a
      ||(c>=0x2e80&&c<=0xa4cf&&c!==0x303f)||(c>=0xac00&&c<=0xd7a3)
      ||(c>=0xf900&&c<=0xfaff)||(c>=0xfe30&&c<=0xfe6f)
      ||(c>=0xff00&&c<=0xff60)||(c>=0xffe0&&c<=0xffe6));
    n+=wide?2:1;
  }
  return n;
}
/* 変換中の文字を見せる。textarea は opacity:0 で重ねてあるので、何もしないと
   確定するまで画面に一文字も出ない。確定前の文字は端末にはまだ送っていない
   (送ると変換のたびに端末側が書き換わる) ので、ここで見せるしかない */
function onConsoleComposing(e){
  const t=e.target;if(!t)return;
  t.classList.add('composing');
  t.style.width=Math.max(2,_consoleCells(e.data||'')+1)+'ch';
}
/* IME で確定したテキストを送る。onConsoleKey は合成中のキーを捨てるだけなので、
   これが無いと日本語がひとつも入らない。keydown で拾える文字ではないため
   compositionend の data を使う */
function onConsoleComposition(e){
  const t=e.data;
  // textarea には変換中の文字が残っている。送ったあと必ず空にする——
  // 残すと次の入力に混ざり、送信済みの文字が二重に届く
  if(e.target){
    e.target.value='';
    e.target.classList.remove('composing');
    e.target.style.width='';
  }
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

/* 提案 と 分析 の仕切り。logResize と同じ流儀で大きさを localStorage に残す */
/* SUM_SPLIT_MIN はどちらのペインにも残す最低の高さ/幅 */
const SUM_SPLIT_MIN=60;
/* 左右に並べ替える幅。入りと戻りをずらして、境目での往復を防ぐ */
const SUM_ROW_ON=660, SUM_ROW_OFF=600;
/* ユーザーが決めた分割位置は**比率**で持つ。px で覚えると、容器が狭まったとき
   Advice だけが元の大きさを保ち、Analysis が最小まで潰れる。0 は未設定 */
let _adviceRatio=0, _adviceRatioW=0;
/* 縦積みと横並びでいじる軸が変わる。判定を 1 か所に集める */
function _sumRow(){const w=document.getElementById('aiWrap');return !!w&&w.classList.contains('row');}
function _sumProp(row){return row?'width':'height';}
function _sumRatio(row){return row?_adviceRatioW:_adviceRatio;}
/* 容器の大きさが変わるたびに、覚えた比率から引き直す。比率は書き換えないので、
   容器が広がれば元の割合に戻る。最低幅は両側に残す——どちらかが 0 になると、
   そこにあるはずの提案や分析が読めなくなる */
function clampSumSplit(){
  const top=document.getElementById('advWrap'),wrap=document.getElementById('aiWrap');
  if(!top||!wrap)return;
  const row=_sumRow(),prop=_sumProp(row);
  const avail=wrap.getBoundingClientRect()[prop];
  if(avail<SUM_SPLIT_MIN*2+10)return;   // 畳んでいる、または測れない
  const cur=parseInt(top.style[prop],10)||Math.round(top.getBoundingClientRect()[prop]);
  const ratio=_sumRatio(row);
  const h=Math.round(Math.max(SUM_SPLIT_MIN,
                              Math.min(avail-SUM_SPLIT_MIN-10,
                                       ratio?avail*ratio:cur)));
  if(h!==cur)top.style[prop]=h+'px';
}
/* 幅で縦積みと横並びを決める。狭いまま左右に割ると 1 ペインが数十文字になり、
   広いまま縦に積むと 1 ペインが数行になる。切り替えたら使わない軸のインラインを
   消す——残っていると縦積みなのに幅まで固定され、分析ペインが痩せたままになる */
function applySumOrientation(){
  const top=document.getElementById('advWrap'),wrap=document.getElementById('aiWrap');
  if(!top||!wrap)return;
  const w=wrap.getBoundingClientRect().width;
  if(!w)return;                          // 非表示。表に出たときに測り直す
  const row=_sumRow(),want=w>=(row?SUM_ROW_OFF:SUM_ROW_ON);
  if(want===row)return;
  wrap.classList.toggle('row',want);
  top.style.width='';top.style.height='';
  // 新しい軸での大きさは clampSumSplit が比率から引き直す。updateSumSplit が
  // この直後に必ず呼ぶので、ここでは軸を替えてインラインを落とすだけでよい
}
/* 向きを決めてから挟む。外から呼ぶのはこれだけ */
function updateSumSplit(){applySumOrientation();clampSumSplit();}
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
  try{applyConsole(JSON.parse(e.data));}catch(ex){}
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
