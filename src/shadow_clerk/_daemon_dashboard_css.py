"""Shadow-clerk daemon: ダッシュボード CSS"""

# CSS content extracted from _HTML_TEMPLATE (between <style> and </style> tags)
_CSS_TEMPLATE = """\
:root {
  --bg: #0d1117;
  --panel: #161b22;
  --header: #010409;
  --border: #30363d;
  --text: #c9d1d9;
  --muted: #8b949e;
  --accent: #58a6ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --purple: #d2a8ff;
  --self: #79c0ff;
  --other: #ffa657;
  --btn: #21262d;
  --btn-h: #30363d;
  /* 読む面(文字起こし・議事録・コンソール)の基準サイズ。「小中大」で差し替える。
     ヘッダやボタンは動かさない——動かすと折り返して行が増え、読む面が狭くなる */
  --fs: 12px;
}
* { margin:0; padding:0; box-sizing:border-box; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
a:visited { color: var(--purple); }
body {
  background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  height: 100vh; display: flex; flex-direction: column; overflow: hidden;
}
header {
  background: var(--header); border-bottom: 1px solid var(--border);
  padding: 8px 16px; display: flex; align-items: center; gap: 12px;
  flex-shrink: 0; flex-wrap: wrap;
}
select, input[type=text] {
  background: var(--btn); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 5px 8px; font-size: 13px; outline: none;
}
select:focus, input:focus { border-color: var(--accent); }
button {
  background: var(--btn); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 5px 12px; font-size: 13px; cursor: pointer;
}
button:hover { background: var(--btn-h); }
.g { display:flex; gap:6px; align-items:center; }
.pri { background:#238636; border-color:#2ea043; }
.pri:hover { background:#2ea043; }
.dan { background:#da3633; border-color:#f85149; color:#fff; }
.dan:hover { background:#b62324; }
main {
  flex:1; display:flex; gap:1px; background:var(--border); min-height:0;
}
.panel {
  flex:1; background:var(--panel); display:flex; flex-direction:column; min-width:0;
}
.ph {
  padding:8px 12px; border-bottom:1px solid var(--border); font-size:13px;
  font-weight:600; color:var(--muted); flex-shrink:0; display:flex;
  justify-content:space-between; align-items:center;
}
.pc {
  flex:1; overflow-y:auto; padding:8px 12px;
  font-family: 'SF Mono','Monaco','Menlo','Consolas',monospace;
  font-size: var(--fs); line-height: 1.6;
}
.ln { margin-bottom:2px; word-break:break-word; display:flex; align-items:flex-start; }
.ln .ln-text { flex:1; }
.ln-cb { opacity:0; cursor:pointer; margin:3px 4px 0 0; flex-shrink:0; accent-color:var(--blue,#58a6ff); }
.ln:hover .ln-cb { opacity:0.6; }
.ln-cb:checked { opacity:1 !important; }
.sel-actions { display:none; align-items:center; gap:6px; font-size:12px; }
.sel-actions.show { display:flex; }
.sel-count { color:var(--muted); white-space:nowrap; }
.sel-actions button { min-width:auto; padding:2px 6px; font-size:12px; }
.del-lines-list { max-height:30vh; overflow-y:auto; padding:6px 8px; background:var(--bg); border-radius:4px; margin-bottom:12px; white-space:pre-wrap; line-height:1.6; font-size:12px; }
.extract-option { display:flex; align-items:center; gap:8px; padding:8px 0; cursor:pointer; font-size:13px; text-align:left; color:var(--text); }
.extract-option input[type=radio] { width:auto !important; margin:0; flex-shrink:0; }
.extract-option .eo-label { white-space:nowrap; }
.extract-option select { width:auto !important; flex:1; min-width:120px; margin-left:4px; padding:3px 6px; font-size:12px; }
.ts { color:var(--muted); }
.sp-s { color:var(--self); font-weight:600; }
.sp-o { color:var(--other); font-weight:600; }
.mk { color:var(--purple); font-weight:600; }
#logp {
  height:180px; flex-shrink:0; background:var(--panel);
  border-top:1px solid var(--border); display:flex; flex-direction:column;
}
#logc {
  flex:1; overflow-y:auto; padding:4px 12px;
  font-family: 'SF Mono','Monaco','Menlo','Consolas',monospace;
  font-size:calc(var(--fs) - 1px); line-height:1.5; color:var(--muted);
}
.ll { white-space:pre-wrap; word-break:break-word; }
.ll.e { color:var(--red); }
.ll.w { color:var(--yellow); }
.interim {
  color: var(--muted); font-style: italic; opacity: 0.7; font-size: var(--fs);
  border-left: 2px solid var(--yellow); padding-left: 8px; margin-top: 4px;
}
#resp {
  display:none; background:var(--panel); border-bottom:1px solid var(--border);
  padding:8px 12px; font-size:13px; flex-shrink:0; max-height:120px; overflow-y:auto;
}
#resp.show { display:block; }
#resp .rh {
  display:flex; justify-content:space-between; align-items:center;
  color:var(--accent); font-weight:600; margin-bottom:4px;
}
#resp .rb {
  white-space:pre-wrap; word-break:break-word; color:var(--text);
  font-family:'SF Mono','Monaco','Menlo','Consolas',monospace; font-size:12px;
}
.toggle { font-size:12px; opacity:.7; cursor:pointer; padding:2px 6px; border:1px solid var(--border); border-radius:4px; background:transparent; color:var(--muted); }
.toggle:hover { opacity:1; }
.toggle.off { opacity:.4; text-decoration:line-through; }
.toggle.unavail { color:#e44; opacity:1; position:relative; cursor:help; }
.toggle.unavail::after { content:'\U0001f6ab'; position:absolute; top:-2px; right:-4px; font-size:9px; }
.lv{display:inline-block;width:34px;height:6px;border:1px solid var(--border);
    border-radius:3px;overflow:hidden;vertical-align:middle;margin:0 4px 0 1px}
.lv i{display:block;height:100%;width:0;background:var(--green);
      transition:width .25s linear}
/* 警告はコンテナ自体の背景・枠線で示す。無音時は塗り(<i>)の幅が0%になり
   塗りの色を変えても見た目が変わらないため（fix round 1 finding 1）。
   lv-fallback は box-shadow でリングを描くので、border-color/background を
   変える lv-noise/lv-silent と別のプロパティになり、両方成立しても互いを
   隠さない */
.lv.lv-noise{border-color:var(--yellow);background:var(--yellow)}
.lv.lv-silent{border-color:var(--red);background:var(--red)}
.lv.lv-fallback{box-shadow:0 0 0 1px var(--yellow)}
.panel.hidden { display:none; }
.summary-body { white-space:pre-wrap; line-height:1.7; }
.summary-empty { display:flex; flex-direction:column; align-items:center; justify-content:center; height:100%; }
#logp.collapsed #logc, #logp.collapsed #consolec { display:none; }
/* !important が要る。ドラッグでリサイズすると initLogResize が
   style.height をインラインで書くため、素の height:auto では負けて
   「中身は消えるのに箱の高さだけ残る」状態になる。インラインの値は
   残るので、開き直せば元の高さに戻る */
#logp.collapsed { height:auto !important; }
#logResize { height:5px; cursor:ns-resize; background:transparent; flex-shrink:0; }
#logResize:hover { background:var(--accent); }
#logp.collapsed #logResize { display:none; }
#consolec {
  position:relative;
  /* **gutter は常に確保すること。** overflow:auto のままだと、行が増減して
     縦スクロールバーが出入りするたびに clientWidth が 15px 動く。列数はそこから
     算出しているので 344 ⇄ 346 で振れ、そのたび子に SIGWINCH が飛ぶ。TUI は
     自分がいま思っている幅までしか消さないため、広い幅で描いた罫線が残って
     画面が崩れる */
  flex:1; overflow:auto; scrollbar-gutter:stable; padding:4px 8px; background:var(--bg);
  font-family: var(--console-font);
  font-size:var(--fs); line-height:1.35; white-space:pre; outline:none;
}
#consolec:focus-within { box-shadow: inset 0 0 0 1px var(--accent); }
/* IME の入力先。div は編集可能でないため composition イベントが来ず、日本語が
   打てない。xterm.js と同じく、透明な textarea をカーソル位置に置いて受ける
   ——位置を合わせるのは、変換候補ウィンドウがそこに出るようにするため */
#consoleInput { position:absolute; opacity:0; z-index:1; width:1ch; height:1.35em;
  padding:0; margin:0; border:none; outline:none; resize:none; overflow:hidden;
  font:inherit; line-height:inherit; color:transparent; background:transparent; }
/* 変換中だけ textarea を見せる。透明のままだと確定するまで画面に何も出ず、
   打てているのか分からない。下線は「まだ確定していない」という IME の慣習。
   幅は変換中の文字数から JS が入れる——textarea の width:auto は cols 属性の
   既定(20文字)になってしまい、1文字でも広い箱が出る */
#consoleInput.composing {
  opacity:1; color:var(--text); background:var(--bg);
  text-decoration:underline; z-index:2;
}
.cr { min-height:1.35em; }
.ccursor { position:absolute; width:1ch; height:1.35em; background:var(--accent); opacity:.35; pointer-events:none; }
.cs-bold { font-weight:700; }
.cs-italic { font-style:italic; }
.cs-underline { text-decoration:underline; }
.cs-strike { text-decoration:line-through; }
.cs-reverse { filter:invert(1); }
/* SGR 2 (faint)。claude の TUI は入力欄の候補テキストをこれで描くので、
   自分が打った文字とはっきり差が付く濃さにする */
.cs-dim { opacity:.45; }
/* 端末の升目は「ASCII 1 桁 = 1 セル、CJK = 2 セル、罫線/ブロックは 1 セル」で
   ないと崩れる。ところが CJK フォント (Linux の generic monospace は
   Noto Sans Mono CJK) は罫線・ブロック・記号を East Asian Ambiguous として
   全角幅で持つため、pyte が 1 セルとして送った ─ │ █ ▐ ● が 2 セル幅で
   描かれ、ヘッダの AA も枠線も横にずれる。
   そこで ASCII と罫線は Noto Sans Mono (これらを半角で持つ) から取り、
   CJK だけを size-adjust で 2 倍幅に合わせた別ファミリとして重ねる。
   計測値 (12px): ASCII 7.2 / 罫線・ブロック 7.2 / CJK 14.4 */
@font-face {
  font-family:'ConsoleCJK';
  src:local('Noto Sans Mono CJK JP'),local('Noto Sans Mono CJK SC'),
      local('Source Han Mono'),local('IBM Plex Mono JP');
  size-adjust:120%;
  unicode-range:U+1100-11FF,U+2E80-303F,U+3040-30FF,U+3130-318F,U+3190-319F,
    U+31F0-31FF,U+3200-32FF,U+3400-4DBF,U+4E00-9FFF,U+A960-A97F,U+AC00-D7FF,
    U+F900-FAFF,U+FE10-FE1F,U+FE30-FE4F,U+FF00-FFEF;
}
:root{
  /* local() が全て外れる環境 (macOS / Windows) では ConsoleCJK が使われず、
     末尾の monospace に落ちるだけなので従来どおり動く */
  --console-font:'Noto Sans Mono','DejaVu Sans Mono','SF Mono','Menlo','Consolas',
                 'ConsoleCJK',ui-monospace,monospace;
}
/* pyte の色名に合わせる。pyte は 30-37 を black/red/green/brown/blue/magenta/
   cyan/white、90-97 を bright* と呼ぶ (yellow ではなく brown)。旧実装は
   yellow/bright* を知らず、名前が合わない色を全て捨てていたため画面が
   ほぼ白黒になっていた。bfightmagenta は pyte 側の綴り誤り */
.cfg-black{color:#6e7681}.cfg-red{color:#f85149}.cfg-green{color:#3fb950}
.cfg-brown{color:#d29922}.cfg-blue{color:#58a6ff}.cfg-magenta{color:#bc8cff}
.cfg-cyan{color:#39c5cf}.cfg-white{color:#e6edf3}
.cfg-brightblack{color:#8b949e}.cfg-brightred{color:#ff7b72}
.cfg-brightgreen{color:#56d364}.cfg-brightbrown{color:#e3b341}
.cfg-brightblue{color:#79c0ff}.cfg-brightmagenta{color:#d2a8ff}
.cfg-bfightmagenta{color:#d2a8ff}
.cfg-brightcyan{color:#56d4dd}.cfg-brightwhite{color:#ffffff}
.cbg-black{background:#6e7681}.cbg-red{background:#f85149}.cbg-green{background:#3fb950}
.cbg-brown{background:#d29922}.cbg-blue{background:#58a6ff}.cbg-magenta{background:#bc8cff}
.cbg-cyan{background:#39c5cf}.cbg-white{background:#e6edf3}
.cbg-brightblack{background:#8b949e}.cbg-brightred{background:#ff7b72}
.cbg-brightgreen{background:#56d364}.cbg-brightbrown{background:#e3b341}
.cbg-brightblue{background:#79c0ff}.cbg-brightmagenta{background:#d2a8ff}
.cbg-bfightmagenta{background:#d2a8ff}
.cbg-brightcyan{background:#56d4dd}.cbg-brightwhite{background:#ffffff}
#pnlM { position:relative; overflow:visible; flex:0 0 180px; min-width:0; transition:flex-basis .15s; }
#pnlM.collapsed { flex:0 0 0; }
#pnlM.collapsed .lp-tabs, #pnlM.collapsed #datePane,
#pnlM.collapsed #meetingContent, #pnlM.collapsed #searchPane { display:none !important; }
#pnlM .ph { font-size:12px; min-width:0; }
#pnlM .pc { padding:6px 8px; font-family:inherit; }
.lp-tabs { display:flex; border-bottom:1px solid var(--border); flex-shrink:0; }
.lp-tab { flex:1; padding:5px 2px; font-size:11px; border:none; border-radius:0;
  background:transparent; color:var(--muted); border-bottom:2px solid transparent; cursor:pointer;
  white-space:nowrap; }
/* logp のタブはヘッダ内の小さな span にいるので、幅いっぱいに伸ばす必要がない。
   flex:1 のままだと狭く潰されて「AIコン/ソール」のように折り返す */
#logHead .lp-tab { flex:0 0 auto; padding:5px 10px; }
.lp-tab:hover { color:var(--text); background:transparent; }
.lp-tab.active { color:var(--accent); border-bottom-color:var(--accent); background:transparent; }
#meetingContent { display:flex; flex-direction:column; flex:1; min-height:0; overflow:hidden; }
#searchPane { display:flex; flex-direction:column; flex:1; min-height:0; overflow:hidden; }
#searchForm { padding:6px 8px; border-bottom:1px solid var(--border); flex-shrink:0; }
#searchForm input[type=text], #searchForm select { font-size:11px; padding:2px 4px; }
#searchForm label { font-size:10px; display:flex; align-items:center; gap:2px; color:var(--muted); cursor:pointer; white-space:nowrap; }
.sr-item { padding:4px 8px; cursor:pointer; border-radius:3px; margin-bottom:1px;
  display:flex; justify-content:space-between; align-items:center; gap:4px; }
.sr-item:hover { background:var(--btn-h); }
.sr-display { font-size:11px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
.sr-type { font-size:10px; color:var(--muted); flex-shrink:0; }
#meetingChevron {
  position:absolute; right:-14px; top:50%; transform:translateY(-50%);
  z-index:10; width:14px; height:44px;
  background:var(--btn); border:1px solid var(--border);
  border-radius:0 6px 6px 0; cursor:pointer;
  display:flex; align-items:center; justify-content:center;
  color:var(--muted); font-size:10px; padding:0;
}
#meetingChevron:hover { background:var(--btn-h); color:var(--text); }
#pnlS { position:relative; overflow:visible; }
#pnlS.collapsed { flex:0 0 0; }
#pnlS.collapsed .lp-tabs, #pnlS.collapsed #sumWrap,
#pnlS.collapsed #aiWrap { display:none !important; }
/* タブの中身は縦に伸ばす。.pc の overflow-y が効くように min-height:0 を置く */
#sumWrap, #aiWrap { flex:1; display:flex; flex-direction:column; min-height:0; }
/* AI タブは提案(上) と分析(下) を縦に積む。上は高さ指定 + flex-shrink:0 で
   仕切りのドラッグに追従させ、下は残りを埋める */
#advWrap { flex:0 0 auto; height:45%; display:flex; flex-direction:column; min-height:60px; }
#anaWrap { flex:1; display:flex; flex-direction:column; min-height:60px; }
#sumSplit { height:5px; cursor:ns-resize; background:var(--border); flex-shrink:0; }
#sumSplit:hover { background:var(--accent); }
/* 幅が広いときは左右に並べる。縦に積んだままだと 1 ペインあたりの行数が
   足りず、提案も分析も数行しか読めない。切り替えは幅を見て JS が行う。
   height/width のインラインは軸を変えるときに JS が消すので、ここは素の
   値でよい（!important で殴ると、こんどはドラッグが効かなくなる） */
#aiWrap.row { flex-direction:row; }
#aiWrap.row #advWrap { height:auto; width:45%; min-height:0; min-width:60px; }
#aiWrap.row #anaWrap { min-height:0; min-width:60px; }
#aiWrap.row #sumSplit { height:auto; width:5px; cursor:ew-resize; }
/* 生成物 (Markdown → HTML) の体裁。会議中に目で追う画面なので、行間を詰めて
   見出しと箇条書きの階層が一目で分かる程度に留める */
.md-body { word-break:break-word; line-height:1.6; }
.md-body h1, .md-body h2, .md-body h3,
.md-body h4, .md-body h5, .md-body h6 {
  margin:10px 0 4px; font-size:1.08em; color:var(--accent); font-weight:600; }
.md-body h1 { font-size:1.25em; }
.md-body h2 { font-size:1.17em; }
.md-body p { margin:4px 0; }
.md-body ul, .md-body ol { margin:4px 0; padding-left:20px; }
.md-body li { margin:2px 0; }
.md-body code { background:var(--bg); padding:1px 4px; border-radius:3px; font-size:.92em; }
.md-body pre { background:var(--bg); padding:6px 8px; border-radius:4px;
  overflow-x:auto; margin:6px 0; font-size:.92em; }
.md-body pre code { background:transparent; padding:0; }
.md-body blockquote { margin:6px 0; padding-left:8px; border-left:3px solid var(--border);
  color:var(--muted); }
.md-body hr { border:none; border-top:1px solid var(--border); margin:8px 0; }
.md-body a { color:var(--blue,#58a6ff); }
.md-body strong { color:var(--text); }
/* ペインは画面の一部しか使えないので、広いテーブルは横スクロールに逃がす */
.md-body table { border-collapse:collapse; margin:6px 0; display:block;
  overflow-x:auto; max-width:100%; font-size:.92em; }
.md-body th, .md-body td { border:1px solid var(--border); padding:2px 6px;
  white-space:nowrap; }
.md-body th { background:var(--bg); font-weight:600; }
.md-body s { color:var(--muted); }
#sumChevron {
  position:absolute; left:-14px; top:50%; transform:translateY(-50%);
  z-index:10; width:14px; height:44px;
  background:var(--btn); border:1px solid var(--border);
  border-radius:6px 0 0 6px; cursor:pointer;
  display:flex; align-items:center; justify-content:center;
  color:var(--muted); font-size:10px; padding:0;
}
#sumChevron:hover { background:var(--btn-h); color:var(--text); }
.mg-item {
  padding:7px 8px; cursor:pointer; border-radius:4px;
  margin-bottom:2px; display:flex; justify-content:space-between; align-items:center;
}
.mg-item:hover { background:var(--btn-h); }
.mg-name { font-weight:600; font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; flex:1; }
.mg-cnt { font-size:11px; color:var(--muted); flex-shrink:0; margin-left:4px; }
.mg-file {
  padding:5px 8px; cursor:pointer; font-size:11px; border-radius:4px;
  margin-bottom:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  color:var(--muted); display:flex; align-items:center; gap:3px;
}
.mg-file-label { flex:1; overflow:hidden; text-overflow:ellipsis; }
.badge-t, .badge-s, .badge-a {
  font-size:9px; font-weight:700; padding:0 3px; border-radius:3px; flex-shrink:0; line-height:15px;
}
.badge-t { color:var(--accent); border:1px solid var(--accent); }
.badge-s { color:var(--green); border:1px solid var(--green); }
.badge-a { color:var(--purple); border:1px solid var(--purple); }
.mg-file:hover { background:var(--btn-h); color:var(--text); }
.mg-file.active { color:var(--accent); background:rgba(88,166,255,.1); }
.modal-overlay {
  display:none; position:fixed; inset:0; background:rgba(0,0,0,.6);
  z-index:100; justify-content:center; align-items:center;
}
.modal-overlay.open { display:flex; }
.modal {
  background:var(--panel); border:1px solid var(--border); border-radius:12px;
  width:676px; max-height:80vh; display:flex; flex-direction:column;
}
.modal-head {
  padding:12px 16px; border-bottom:1px solid var(--border);
  font-weight:600; display:flex; justify-content:space-between; align-items:center;
}
.modal-body {
  padding:16px; overflow-y:auto; flex:1;
  display:grid; grid-template-columns:140px 1fr; gap:8px 12px; align-items:center;
  font-size:13px;
}
.modal-body label { color:var(--muted); text-align:right; }
.modal-body input, .modal-body select, .modal-body textarea {
  background:var(--btn); color:var(--text); border:1px solid var(--border);
  border-radius:6px; padding:5px 8px; font-size:13px; width:100%; outline:none;
  font-family:inherit;
}
.modal-body input:focus, .modal-body select:focus, .modal-body textarea:focus {
  border-color:var(--accent);
}
.modal-body textarea { resize:vertical; min-height:60px; font-family:monospace; font-size:12px; }
.modal-body .cfg-section { grid-column:1/-1; font-weight:bold; font-size:13px; padding:8px 0 4px; border-bottom:1px solid var(--border); margin-top:4px; color:var(--text); }
.modal-body .cfg-section:first-child { margin-top:0; }
/* 設定フォーム以外の本文。.modal-body は 140px+1fr の grid なので、
   素の要素を並べると左右のセルに振り分けられて崩れる */
.modal-body.flow { display:block; }
.wc-row { display:flex; align-items:center; gap:8px; padding:5px 0; font-size:12px; }
.wc-row code { color:var(--muted); font-size:11px; overflow-wrap:anywhere; }
.wc-row button { flex-shrink:0; }
.wc-h { font-weight:bold; margin:10px 0 4px; font-size:12px; }
.wc-li { color:var(--muted); font-size:11px; padding:2px 0 2px 10px; }
.modal-body .cfg-warn, #cfgPathWarn { grid-column:1/-1; font-size:11px; padding:6px 8px; background:rgba(255,179,71,0.12); border-left:3px solid #ffb347; color:var(--muted); margin:2px 0 4px; line-height:1.5; }
#glossaryTable th, #glossaryTable td {
  border:1px solid var(--border); padding:4px 6px;
}
#glossaryTable th {
  background:var(--bg); color:var(--muted); font-weight:600; font-size:12px;
  text-align:left; position:sticky; top:0; padding:2px 4px;
}
#glossaryTable th select { width:100%; }
#glossaryTable td { padding:0; }
#glossaryTable td input {
  border:none; border-radius:0; width:100%; padding:5px 6px; font-size:13px;
  background:transparent; color:var(--text); outline:none;
}
#glossaryTable td input:focus { background:rgba(100,100,255,0.08); }
#glossaryTable td.gl-del { width:30px; text-align:center; cursor:pointer; color:var(--muted); }
#glossaryTable td.gl-del:hover { color:var(--red,#e55); }
#customCmdTable th, #customCmdTable td {
  border:1px solid var(--border); padding:4px 6px;
}
#customCmdTable th {
  background:var(--bg); color:var(--muted); font-weight:600; font-size:12px;
  text-align:left; position:sticky; top:0; padding:4px 6px;
}
#customCmdTable td { padding:0; }
#customCmdTable td input {
  border:none; border-radius:0; width:100%; padding:5px 6px; font-size:13px;
  background:transparent; color:var(--text); outline:none;
}
#customCmdTable td input:focus { background:rgba(100,100,255,0.08); }
#customCmdTable td.gl-del { width:30px; text-align:center; cursor:pointer; color:var(--muted); }
#customCmdTable td.gl-del:hover { color:var(--red,#e55); }
.modal-foot {
  padding:12px 16px; border-top:1px solid var(--border);
  display:flex; justify-content:flex-end; gap:8px;
}
.modal-foot .saved { color:var(--green); font-size:13px; margin-right:auto; display:none; }
.mg-wd { opacity:0; border:none; background:transparent; color:var(--muted);
  font-size:11px; padding:0 2px; cursor:pointer; flex-shrink:0; min-width:auto; }
.mg-file:hover .mg-wd { opacity:0.7; }
.mg-wd:hover { opacity:1 !important; color:var(--text); background:transparent; }
"""
