"""Shadow-clerk daemon: /next ダッシュボード CSS（試作 dashboard-friendly-ui-interactive.css が元）"""
from __future__ import annotations

from shadow_clerk._daemon_dashboard_css import _CSS_CONSOLE, _CSS_WELCOME

_DARK = """\
  --bg:#0b0f17; --panel:#111827; --panel2:#0f1520; --line:#1f2937; --border:var(--line); --text:#e5e7eb; --muted:#8b95a5;
  --chip:#1f2937; --accent:#3b82f6; --green:#16a34a; --red:#ef4444; --amber:#f59e0b; --purple:#c084fc;
  --me:#f87171; --other:#60a5fa; --claude:#c084fc; --meet-fg:#fca5a5; --off-fg:#fca5a5;
  --meet-bg:rgba(239,68,68,.15); --off-bg:rgba(239,68,68,.1); --toast-bg:#111; --toast-fg:#fff;
  --warn-fg:#fcd34d; --danger-fg:#f87171; --sel-bg:rgba(59,130,246,.16);
  --th-t:rgba(96,165,250,.35); --th-r:rgba(74,222,128,.35); --th-a:rgba(192,132,252,.35); --con-bg:#05070b; --con-fg:#e5e7eb; --ok:#22c55e;
  --cu-fg:#93c5fd;
"""

_LIGHT = """\
  --bg:#f3f5f8; --panel:#ffffff; --panel2:#f8fafc; --line:#e2e6ec; --text:#1f2933; --muted:#6b7280;
  --chip:#eef1f5; --me:#dc2626; --other:#2563eb; --claude:#9333ea; --meet-fg:#b91c1c; --off-fg:#b91c1c;
  --toast-bg:#1f2933; --toast-fg:#fff; --warn-fg:#92400e; --danger-fg:#dc2626; --cu-fg:#1d4ed8;
"""

_NEXT_CSS = (
    ":root {\n" + _DARK + "  color-scheme:dark;\n}\n"
    "@media (prefers-color-scheme: light) {\n:root:not([data-theme=\"dark\"]) {\n" + _LIGHT + "  color-scheme:light;\n}\n}\n"
    ":root[data-theme=\"light\"] {\n" + _LIGHT + "  color-scheme:light;\n}\n"
) + """\
* { box-sizing:border-box; }
html, body { height:100%; }
body { margin:0; display:flex; flex-direction:column; font-family:Inter,"Noto Sans JP",Helvetica,Arial,sans-serif;
  background:var(--bg); color:var(--text); font-size:13px; }
button { font:inherit; color:inherit; cursor:pointer; }
.muted { color:var(--muted); }
.spacer { flex:1; }
body:not(.adv) .adv-only { display:none !important; }

/* header */
header { display:flex; align-items:center; gap:10px; padding:10px 14px; border-bottom:1px solid var(--line);
  background:var(--panel2); flex-wrap:wrap; }
.logo { font-weight:bold; font-size:15px; margin-right:4px; }
.status { min-width:260px; white-space:nowrap; display:flex; align-items:center; gap:8px; padding:5px 12px;
  border-radius:999px; background:var(--chip); font-size:12.5px; }
.status[data-go="1"] { cursor:pointer; }
.status[data-go="1"]:hover { outline:1px solid var(--muted); }
.status[data-go="1"]::after { content:"↩"; opacity:.7; }
.status .dot { width:9px; height:9px; border-radius:50%; background:var(--ok); }
.status.meeting { background:var(--meet-bg); color:var(--meet-fg); }
.status.meeting .dot { background:var(--red); animation:nxblink 1.2s infinite; }
.status.stopped .dot, .status.disconnected .dot { background:var(--muted); }
.status.disconnected { background:rgba(245,158,11,.14); color:var(--amber); }
@keyframes nxblink { 50% { opacity:.3 } }
.primary { white-space:nowrap; background:var(--green); color:#fff; border:1px solid transparent; border-radius:8px; padding:7px 12px; font-weight:bold; }
.primary.stop { background:var(--red); }
.tbtn { white-space:nowrap; display:flex; align-items:center; gap:6px; background:var(--chip);
  border:1px solid var(--line); border-radius:8px; padding:7px 12px; }
.tbtn.on { background:rgba(59,130,246,.18); border-color:var(--accent); }
.tbtn .sw { width:26px; height:14px; border-radius:7px; background:var(--line); position:relative; }
.tbtn .sw::after { content:""; position:absolute; top:2px; left:2px; width:10px; height:10px; border-radius:50%;
  background:var(--muted); transition:.15s; }
.tbtn.on .sw { background:var(--accent); } .tbtn.on .sw::after { left:14px; background:#fff; }
.langq { display:flex; align-items:center; gap:4px; font-size:13px; }
.langq select { background:var(--chip); color:var(--text); border:1px solid var(--line); border-radius:6px; padding:3px 4px; }
.dev { white-space:nowrap; display:flex; align-items:center; gap:6px; background:var(--chip);
  border:1px solid var(--line); border-radius:8px; padding:6px 10px; }
.dev .lv { width:44px; height:6px; border-radius:3px; background:var(--line); overflow:hidden; }
.dev .lv i { display:block; height:100%; background:var(--ok); width:0; transition:width .2s; }
.dev.off { border-color:var(--red); color:var(--off-fg); background:var(--off-bg); }
.dev.off .lv i { width:0 !important; }
.dev.unavail { opacity:.5; cursor:default; }
.ibtn { background:transparent; border:1px solid transparent; border-radius:8px; padding:6px 9px; }
.ibtn:hover { background:var(--chip); }
.seg { display:flex; background:var(--chip); border-radius:999px; padding:2px; font-size:12px; }
.seg button { border:none; background:transparent; border-radius:999px; padding:4px 10px; color:var(--muted); }
.seg button.act { background:var(--accent); color:#fff; }
.menu-wrap { position:relative; }
.menu { position:absolute; right:0; top:40px; width:270px; background:var(--panel); border:1px solid var(--line);
  border-radius:10px; padding:6px; box-shadow:0 10px 30px rgba(0,0,0,.35); z-index:20; display:none; }
.menu.open { display:block; }
.menu:empty { display:none !important; }
.menu .mi { display:flex; gap:10px; padding:8px 10px; border-radius:6px; cursor:pointer; }
.menu .mi:hover { background:var(--chip); }
.menu a.mi { color:inherit; text-decoration:none; }
.menu small { display:block; color:var(--muted); font-size:11px; }
.menu hr { border:none; border-top:1px solid var(--line); margin:4px 0; }
.menu .mi[hidden] { display:none; }
.menu .mi .mi-st { margin-left:auto; font-weight:normal; font-size:12px; color:var(--muted); white-space:nowrap; }
.menu .mi.on .mi-st { color:var(--ok); }
.view-menu { position:fixed; right:auto; width:360px; padding:10px; overflow:auto; }
.vm-t { font-size:11.5px; color:var(--muted); margin:2px 4px 6px; } .vm-gap { margin-top:12px; }
.vm-hint { margin:8px 4px 0; }
.vgrid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.vopt { border:1px solid var(--line); border-radius:8px; padding:8px; cursor:pointer; font-size:12px; }
.vopt:hover { border-color:var(--muted); }
.vopt.act { border-color:var(--accent); background:var(--sel-bg); }
.kbd { font-size:10.5px; border:1px solid var(--line); border-radius:3px; padding:0 4px; color:var(--muted); }
.vopt .kb { float:right; }
.thumb { display:flex; gap:3px; height:38px; margin-bottom:6px; }
.thumb i { flex:1; border-radius:3px; background:var(--chip); border:1px solid var(--line); }
.thumb i.t { background:var(--th-t); } .thumb i.r { background:var(--th-r); } .thumb i.a { background:var(--th-a); flex:1.4; }
.thumb i.c { background:var(--con-bg); flex:1.4; } .thumb i.n { flex:.5; }
.ptog { display:flex; align-items:center; gap:10px; padding:7px 6px; border-radius:6px; cursor:pointer; font-size:12.5px; }
.ptog:hover { background:var(--chip); }
.ptog .sw2 { width:28px; height:16px; border-radius:8px; background:var(--line); position:relative; flex:none; }
.ptog .sw2::after { content:""; position:absolute; top:2px; left:2px; width:12px; height:12px; border-radius:50%;
  background:var(--muted); transition:.15s; }
.ptog.fixed { cursor:default; opacity:.6; } .ptog.fixed:hover { background:none; } .ptog small { margin-left:4px; }
.fseg { display:flex; gap:4px; margin:0 4px; }
.fseg button { flex:1; padding:5px 0; border-radius:6px; border:1px solid var(--line); background:none; color:var(--text); cursor:pointer; }
.fseg button.act { background:var(--accent); border-color:var(--accent); color:#fff; }
.ptog.on .sw2 { background:var(--accent); } .ptog.on .sw2::after { left:14px; background:#fff; }

/* layout */
/* 列は左・中・右の 3 本。閉じたペインの列は 0 幅にし、各ペインの列は明示する（閉じても main が 0 幅の列に落ちない）。
   AI を大きくするときは右ペインが中央の列に来て、文字起こしは右の細い列に移る */
.app { --lw:230px; --rw:380px; flex:1; min-height:0; display:grid; grid-template-columns:var(--lw) minmax(0,1fr) var(--rw);
  transition:grid-template-columns .15s; }
.app.no-left { --lw:0px; } .app.no-right { --rw:0px; } .app.aimode { --rw:340px; }
.app > aside, .app > main, .app > .right { grid-row:1; min-height:0; min-width:0; }
.app > aside { grid-column:1; } .app > main { grid-column:2; } .app > .right { grid-column:3; }
.app.no-left > aside { display:none; } .app.no-right:not(.aimode) > .right { display:none; }
.app.aimode > .right { grid-column:2; border-left:none; border-right:1px solid var(--line); }
.app.aimode > main { grid-column:3; }
.app.aimode .rbody { padding:18px 28px; }
main.narrow .tx { padding-left:10px; padding-right:10px; }
/* 細い列では 時刻・話した人 を 1 段目、本文（と翻訳）を 2 段目に置く */
main.narrow .ln, main.narrow .ln.tr, main.narrow .ln.ro { grid-template-columns:18px 58px minmax(0,1fr) 22px; row-gap:0; }
main.narrow .ln .ts { grid-column:2; grid-row:1; } main.narrow .ln .who { grid-column:3; grid-row:1; }
main.narrow .ln .txt, main.narrow .ln .trn { grid-column:2 / 4; } main.narrow .ln .more { grid-column:4; grid-row:1; }
aside { background:var(--panel); border-right:1px solid var(--line); overflow:auto; padding:8px; }
main { display:flex; flex-direction:column; overflow:hidden; position:relative; min-width:0; }
.mhead { display:flex; align-items:center; flex-wrap:wrap; gap:8px; padding:10px 16px; border-bottom:1px solid var(--line); }
.mbody { flex:1; display:flex; overflow:hidden; min-height:0; }
.txcol { flex:1; display:flex; flex-direction:column; min-width:0; }
.tx { flex:1; overflow:auto; padding:10px 16px 20px; }
.right { background:var(--panel); border-left:1px solid var(--line); display:flex; flex-direction:column; overflow:hidden; }
.rbody { flex:1; overflow:auto; padding:14px 16px; container-type:inline-size; }
/* その他 ▾ →「文字の大きさ」が変えるのは読む面（文字起こし・右ペイン）だけ */
.tx, .rbody { font-size:13px; }
.rtabs { display:flex; border-bottom:1px solid var(--line); }
.rtabs button { flex:1; border:none; background:transparent; padding:10px; color:var(--muted); border-bottom:2px solid transparent; }
.rtabs button.act { color:var(--text); border-bottom-color:var(--accent); }
.empty p { color:var(--muted); font-size:12.5px; margin:0 0 16px; line-height:1.6; }
.right .empty { text-align:center; padding:40px 12px; color:var(--text); font-size:13px; }
.empty .ic { font-size:34px; } .empty h3 { margin:8px 0 4px; font-size:15px; }
.spinner { width:26px; height:26px; border:3px solid var(--line); border-top-color:var(--accent); border-radius:50%;
  animation:nxspin 1s linear infinite; margin:0 auto 10px; }
@keyframes nxspin { to { transform:rotate(360deg) } }
/* 議事録を読み進めてもコピー等を押せるよう、ボタンの行は上に貼り付ける（rbody の余白ぶん外へ広げて下の文を隠す） */
.rtools { display:flex; flex-wrap:wrap; gap:6px; justify-content:flex-end; position:sticky; top:-14px; z-index:1;
  margin:-14px -16px 10px; padding:14px 16px 8px; background:var(--panel); }
.app.aimode .rtools { top:-18px; margin:-18px -28px 10px; padding:18px 28px 8px; }
.lbtn { text-decoration:none; }
.att { border:1px solid var(--line); border-radius:8px; padding:6px 10px; margin:6px 0 10px; font-size:12px; background:var(--panel2); }
.att small { display:block; color:var(--muted); font-size:11px; margin-top:2px; }
.sumraw { white-space:pre-wrap; font:inherit; margin:0; }
.card { border:1px solid var(--line); border-radius:10px; padding:10px 12px; margin-bottom:10px; background:var(--panel2); }
.secttl { font-size:12px; color:var(--muted); margin:14px 0 6px; display:flex; justify-content:space-between; align-items:center; gap:6px; }
.aitag { font-size:10.5px; margin-left:6px; }
.secttl { flex-wrap:wrap; } .secttl > span { flex:1 1 160px; } .secttl .lbtn { max-width:100%; overflow:hidden; text-overflow:ellipsis; }
.astat { display:flex; align-items:center; gap:8px; font-size:12px; padding:8px 10px; border-radius:8px; background:var(--chip); margin-bottom:12px; }
.astat .dot { width:8px; height:8px; border-radius:50%; background:var(--ok); animation:nxblink 1.6s infinite; }
.aiother { margin:-4px 2px 10px; }
.empty .aiother { margin-top:12px; }
/* アドバイスと分析は 2 カラム。ペインの幅が 620px 以下なら上下に積む */
.aigrid { display:grid; grid-template-columns:1fr 1fr; gap:0 24px; align-items:start; }
.aicol { min-width:0; }
.aicol + .aicol { border-left:1px solid var(--line); padding-left:24px; }
@container (max-width:620px) {
  .aigrid { grid-template-columns:1fr; }
  .aicol + .aicol { border-left:none; padding-left:0; border-top:1px solid var(--line); margin-top:8px; }
}
.md-body { overflow-wrap:anywhere; line-height:1.6; }
.md-body h1, .md-body h2, .md-body h3, .md-body h4 { margin:12px 0 4px; font-size:1.05em; color:var(--other); }
.md-body h1 { font-size:1.2em; color:var(--text); } .md-body > :first-child { margin-top:0; }
.md-body p { margin:4px 0; } .md-body ul, .md-body ol { margin:4px 0; padding-left:20px; } .md-body li { margin:2px 0; }
.md-body code { background:var(--chip); padding:1px 4px; border-radius:3px; font-size:.92em; }
.md-body pre { background:var(--chip); padding:6px 8px; border-radius:4px; overflow-x:auto; }
.md-body pre code { background:transparent; padding:0; }
.md-body blockquote { margin:6px 0; padding-left:8px; border-left:3px solid var(--line); color:var(--muted); }
.md-body table { border-collapse:collapse; display:block; overflow-x:auto; max-width:100%; font-size:.92em; margin:6px 0; }
.md-body th, .md-body td { border:1px solid var(--line); padding:2px 6px; white-space:nowrap; }
.md-body a, .rbody a:not(.lbtn) { color:var(--accent); }

/* bottom drawer */
.drawer { background:var(--panel2); border-top:1px solid var(--line); position:relative; }
.drawer .dgrip { display:none; position:absolute; top:-4px; left:0; right:0; height:7px; cursor:ns-resize; z-index:2; }
.drawer.open .dgrip { display:block; } .drawer .dgrip:hover, .drawer.dragging .dgrip { background:var(--accent); opacity:.5; }
.drawer.dragging .db { transition:none; }
.drawer .dh { display:flex; align-items:center; gap:4px; padding:4px 12px; font-size:12px; }
.drawer .dh button { border:none; background:transparent; padding:5px 10px; border-radius:6px; color:var(--muted); }
.drawer .db { height:0; overflow:hidden; transition:height .2s; font-family:ui-monospace,monospace; font-size:12px; color:var(--muted); }
.drawer .dh button.act { color:var(--text); background:var(--chip); }
.drawer.open .db { height:var(--dh,180px); overflow:auto; padding:8px 14px; }
.dpane { height:100%; display:flex; flex-direction:column; } .dcon { flex:1; min-height:0; display:flex; }
/* 流用する端末（#consoleRow）。中身の見た目は現行と共有の _CSS_CONSOLE */
#consoleRow { flex:1; display:flex; min-height:0; min-width:0; --fs:12px; }
.aicon { display:none; flex:1.1; min-width:0; flex-direction:column; border-right:1px solid var(--line); background:var(--bg); }
main.aiview .aicon { display:flex; }
.aicon { position:relative; }
/* 止まっている間は真っ黒な端末の上に、何が出るかと起動のボタンを重ねる */
.conidle { display:none; position:absolute; inset:0; z-index:1; background:var(--con-bg); flex-direction:column; align-items:center;
  justify-content:center; text-align:center; padding:24px; color:var(--con-fg); }
.aicon.idle .conidle { display:flex; } .conidle .ic { font-size:34px; } .conidle h3 { margin:8px 0 6px; font-size:15px; }
.conidle p { max-width:420px; font-size:12.5px; line-height:1.7; opacity:.75; margin:0 0 16px; }
.aicon .ah { font-size:12px; color:var(--muted); padding:6px 12px; border-bottom:1px solid var(--line); }
.md-body .say { cursor:pointer; border-radius:3px; }
.md-body .say:hover { background:var(--bg); }
.dnote:empty { display:none; }
.ll { white-space:pre-wrap; overflow-wrap:anywhere; } .ll.e { color:var(--danger-fg); } .ll.w { color:var(--warn-fg); }
#nxLogView { display:block; overflow:auto; }
#nxRespView { display:block; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--text); }
#nxRespView:empty::before { content:attr(data-empty); color:var(--muted); }
.lg-model { font-family:ui-monospace,monospace; font-size:12.5px; }

/* left pane */
.tabs { display:flex; gap:4px; margin-bottom:8px; }
.tabs button { flex:1; border:none; background:transparent; border-radius:6px; padding:5px 4px; color:var(--muted); }
.tabs button.act { background:var(--chip); color:var(--text); }
.grp { font-size:11px; color:var(--muted); margin:10px 6px 4px; }
.empty { color:var(--muted); font-size:12px; padding:8px; }
.item { position:relative; padding:8px 9px; border-radius:8px; cursor:pointer; margin-bottom:2px; }
.item:hover { background:var(--chip); }
.item.act { background:rgba(59,130,246,.16); }
.item .t { font-size:13px; } .item .s { font-size:11px; color:var(--muted); margin-top:2px; }
.item .cnt { font-size:11px; color:var(--muted); margin-left:4px; }
.item .acts { position:absolute; right:6px; top:7px; display:none; }
.item:hover .acts { display:block; }
.gear { background:transparent; border:none; color:var(--muted); border-radius:4px; padding:1px 5px; }
.gear:hover { background:var(--line); color:var(--text); }
.pill { display:inline-block; font-size:10px; border-radius:999px; padding:1px 7px; margin-left:4px; }
.pill.sum { background:rgba(34,197,94,.15); color:#16a34a; }
.pill.ai { background:rgba(192,132,252,.15); color:#9333ea; }
.pill.live { background:var(--meet-bg); color:var(--meet-fg); }
.lbtn { white-space:nowrap; background:transparent; border:1px solid var(--line); border-radius:6px; padding:4px 8px; font-size:12px; }
.lbtn:hover { background:var(--chip); }
.lbtn.sm { font-size:11.5px; padding:2px 7px; }
.ghead { display:flex; align-items:center; gap:4px; padding:4px 4px 8px; border-bottom:1px solid var(--line); margin-bottom:6px; }
.ghead b { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.sortbar { display:flex; justify-content:space-between; align-items:center; font-size:11px; color:var(--muted); margin:2px 4px 6px; }
.mhead h2 { margin:0; font-size:15px; white-space:nowrap; }

/* search tab */
.sr-form { display:flex; flex-direction:column; gap:6px; margin-bottom:8px; }
.sr-q { display:flex; gap:4px; } .sr-q input { flex:1; min-width:0; }
.sr-types { display:flex; gap:4px; flex-wrap:wrap; }
.sr-t, .sr-dt { background:transparent; border:1px solid var(--line); border-radius:999px; padding:2px 9px; font-size:11.5px; color:var(--muted); }
.sr-t.act { background:var(--sel-bg); border-color:var(--accent); color:var(--text); }
.sr-dt { border-radius:6px; text-align:left; color:var(--text); }
.sr-dates, .sr-quick { display:flex; gap:4px; flex-wrap:wrap; }
.sr-count { font-size:11.5px; color:var(--muted); margin:4px 6px; }
.sr-file { display:flex; gap:6px; align-items:baseline; padding:6px 8px 2px; font-size:12.5px; cursor:pointer; border-radius:6px; }
.sr-file:hover, .sr-hit:hover { background:var(--chip); }
.sr-file .cnt { font-size:11px; color:var(--muted); }
.sr-hit { padding:3px 8px 3px 18px; border-radius:6px; cursor:pointer; font-size:12.5px; }
.sr-meta { font-size:11px; color:var(--muted); } .sr-text { overflow-wrap:anywhere; }
.sr-text mark { background:rgba(245,158,11,.35); color:inherit; border-radius:2px; }
.ln.flash { outline:1px solid var(--accent); background:var(--sel-bg); }

/* transcript */
main { container-type:inline-size; }
.banner { margin:8px 16px 0; padding:8px 12px; border-radius:8px; font-size:12.5px; display:none; }
.banner.show { display:block; }
.banner.warn { background:rgba(245,158,11,.14); color:var(--warn-fg); border:1px solid rgba(245,158,11,.35); }
.colhead { display:none; grid-template-columns:18px 62px 70px 1fr 1fr 28px; gap:8px; font-size:11px; color:var(--muted); padding:6px 16px 0; }
.colhead.show { display:grid; } .colhead.ro { grid-template-columns:18px 62px 70px 1fr 28px; }
/* 行の右端の ⋯ の列までまたいで、ボタンを右端に寄せる */
.trh { display:flex; align-items:center; gap:4px; white-space:nowrap; grid-column:span 2; }
.trh a { color:inherit; text-decoration:none; }
.ln { display:grid; grid-template-columns:18px 62px 70px 1fr 28px; gap:8px; padding:4px 0 4px 4px; line-height:1.6;
  border-radius:6px; cursor:pointer; user-select:none; position:relative; }
.ln.tr { grid-template-columns:18px 62px 70px 1fr 1fr 28px; }
.ln:hover { background:var(--chip); }
.ln .ts { color:var(--muted); font-size:.92em; font-variant-numeric:tabular-nums; }
.ln .who { font-weight:bold; font-size:.96em; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ln .who.me { color:var(--me); } .ln .who.other { color:var(--other); } .ln .who.claude { color:var(--claude); }
.ln .txt, .ln .trn { min-width:0; overflow-wrap:anywhere; }
.ln.tr .trn { color:var(--muted); border-left:2px solid var(--line); padding-left:8px; }
.ln .notr { font-size:.88em; }
.ln .cb { width:14px; height:14px; margin-top:4px; border:1.5px solid var(--muted); border-radius:4px; opacity:.35;
  display:flex; align-items:center; justify-content:center; font-size:10px; color:#fff; }
.ln:hover .cb { opacity:.9; }
.ln.sel { background:var(--sel-bg); }
.ln.sel .cb { opacity:1; background:var(--accent); border-color:var(--accent); }
.ln.sel .cb::after { content:"✓"; }
.ln .more { opacity:0; background:transparent; border:none; color:var(--muted); border-radius:4px; align-self:start; }
.ln:hover .more { opacity:1; }
.ln .more:hover { background:var(--line); }
.lmenu { position:absolute; right:30px; top:22px; background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:4px;
  z-index:5; width:200px; box-shadow:0 8px 24px rgba(0,0,0,.35); cursor:default; }
.lmenu div { padding:6px 10px; border-radius:5px; font-size:12.5px; cursor:pointer; }
.lmenu div:hover { background:var(--chip); }
.lmenu div.danger { color:var(--danger-fg); }
.ln.interim { color:var(--muted); font-style:italic; cursor:default; }
.ln.interim:hover { background:transparent; }
.mk { color:var(--muted); font-size:11px; text-align:center; margin:6px 0; }
.chunk { display:flex; align-items:center; gap:10px; margin:14px 0 4px; padding:7px 10px; border:1px dashed var(--line);
  border-radius:8px; font-size:12px; flex-wrap:wrap; }
.chunk .ct { font-weight:bold; white-space:nowrap; }
.gap { text-align:center; font-size:11px; color:var(--muted); margin:10px 0; position:relative; }
.gap::before { content:""; position:absolute; left:0; right:0; top:50%; border-top:1px dotted var(--line); }
.gap span { position:relative; background:var(--bg); padding:0 10px; }
.suggest { position:relative; margin:8px 16px 0; padding:10px 30px 10px 12px; border-radius:10px; background:rgba(59,130,246,.10);
  border:1px solid rgba(59,130,246,.35); font-size:12.5px; display:flex; gap:10px; align-items:center; }
.suggest .sg-short { display:none; }
.suggest.compact { margin:6px 10px 0; padding:6px 28px 6px 10px; font-size:12px; gap:6px; }
.suggest.compact .sg-long { display:none; } .suggest.compact .sg-short { display:inline; }
@container (max-width:640px) { .suggest .sg-long { display:none; } .suggest .sg-short { display:inline; }
  .suggest { margin:6px 10px 0; padding:6px 28px 6px 10px; font-size:12px; gap:6px; } }
.sg-x { position:absolute; top:6px; right:6px; background:transparent; border:none; color:var(--muted); font-size:12px; border-radius:4px; padding:2px 5px; }
.sg-x:hover { background:var(--chip); color:var(--text); }
.txempty { text-align:center; padding:40px 12px; }
.txempty .ic { font-size:34px; } .txempty h3 { margin:8px 0 4px; font-size:15px; }
.selbar { position:absolute; left:12px; right:12px; bottom:14px; display:none; flex-wrap:wrap; align-items:center; gap:6px;
  background:var(--panel); border:1px solid var(--accent); border-radius:12px; padding:8px 10px 8px 14px;
  box-shadow:0 10px 30px rgba(0,0,0,.45); z-index:6; white-space:nowrap; }
.selbar.show { display:flex; }
.selbar .info { flex:1; min-width:110px; font-size:12.5px; margin-right:6px; }
.selbar .info small { display:block; color:var(--muted); font-size:11px; }
.selbar .sb { background:var(--chip); border:1px solid var(--line); border-radius:8px; padding:6px 10px; font-size:12.5px; }
.selbar .sb.pri { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:bold; }
.selbar .sb.danger { color:var(--danger-fg); }
.preview { background:var(--panel2); border:1px solid var(--line); border-radius:8px; padding:8px 10px; font-size:12px; line-height:1.6; margin-top:8px; }
.preview .dots { color:var(--muted); text-align:center; }

/* modal */
.modal-bg { position:fixed; inset:0; background:rgba(0,0,0,.5); display:none; align-items:center; justify-content:center; z-index:30; }
.modal-bg.show { display:flex; }
.modal { background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px 20px; width:400px; max-width:92vw; }
.modal h3 { margin:0 0 12px; font-size:16px; }
.modal label { display:block; font-size:12px; color:var(--muted); margin:10px 0 4px; }
.modal input:not([type=radio]), .modal select { width:100%; background:var(--panel2); border:1px solid var(--line); color:var(--text);
  border-radius:6px; padding:7px 9px; font:inherit; }
.modal .row { display:flex; justify-content:flex-end; gap:8px; margin-top:16px; }
.modal .radio { display:flex; gap:8px; align-items:flex-start; padding:8px 10px; border:1px solid var(--line); border-radius:8px;
  margin-top:6px; cursor:pointer; color:var(--text); font-size:13px; }
.modal .radio > div { flex:1; } .modal .radio input[type=radio] { margin-top:3px; }
.modal.wide { width:520px; max-height:90vh; overflow:auto; }
.modal .radio.act { border-color:var(--accent); background:var(--chip); }
.modal .radio.disabled { opacity:.4; pointer-events:none; }
.modal .radio[hidden] { display:none; }
.modal .step { font-size:12.5px; font-weight:bold; margin:14px 0 4px; }
.modal .step:first-child { margin-top:0; }
.modal .inl { font-size:12px; color:var(--muted); margin-top:6px; display:flex; align-items:center; gap:6px; }
.modal .inl select { width:auto; padding:2px 6px; }
.modal .segs { margin-top:6px; display:none; font-size:11.5px; }
.modal .radio.act .segs { display:block; }
.modal .seg-i { font-size:12px; padding:3px 8px; border-left:3px solid var(--accent); margin:3px 0; background:var(--panel2); border-radius:0 4px 4px 0; }
.modal .sub-opts { margin-top:6px; }
.modal label.opt { display:flex; align-items:center; gap:6px; color:var(--text); font-size:12.5px; margin:4px 0; white-space:nowrap; }
.modal label.opt select, .modal label.opt input:not([type=radio]) { flex:1; min-width:0; width:auto; padding:3px 6px; }
.modal .radio > div > select { margin-top:6px; }
.modal .hint.foot { margin-top:10px; }
.modal label.chk { display:flex; gap:6px; align-items:center; color:var(--text); font-size:13px; margin-top:14px; }
.modal label.chk input { width:auto; }
.hint { font-size:11.5px; color:var(--muted); margin-top:4px; line-height:1.5; }
.cta { background:var(--accent); color:#fff; border:none; border-radius:8px; padding:8px 16px; font-weight:bold; }
.cta.danger { background:var(--red); }
.cta:disabled { opacity:.5; cursor:default; }
.cta.ghost { background:transparent; border:1px solid var(--line); color:var(--text); font-weight:normal; }

/* 会議ごとの設定 */
.lbtn.mc-all { width:100%; margin:0 0 8px; }
.modal.cfgm { width:min(1000px,94vw); height:min(720px,88vh); max-width:none; display:flex; flex-direction:column; padding:0; }
.cfg-h, .cfg-f { display:flex; align-items:center; gap:8px; padding:12px 18px; border-bottom:1px solid var(--line); }
.modal .cfg-h h3 { margin:0; } .cfg-f { border-bottom:none; border-top:1px solid var(--line); }
.cfg-f .hint { margin:0; } .cfg-f .err { color:var(--danger-fg); font-size:12px; }
.cfg-b { flex:1; display:flex; min-height:0; }
.cfg-list { width:320px; border-right:1px solid var(--line); overflow:auto; padding:10px; }
.cfg-ed { flex:1; overflow:auto; padding:14px 22px; }
.cfg-ed h4 { margin:0 0 8px; font-size:15px; } .cfg-ed > .hint { margin-top:0; } .cfg-ed .hint.warn { color:var(--warn-fg); margin-top:6px; }
.modal .cfg-tools { display:flex; flex-wrap:wrap; gap:4px 12px; font-size:11.5px; color:var(--muted); margin:8px 2px; }
.modal .cfg-tools label, .modal label.cfg-li { display:flex; gap:4px; align-items:center; cursor:pointer; margin:0; white-space:nowrap; }
.modal label.cfg-li { gap:8px; align-items:flex-start; padding:9px 8px; border-radius:8px; margin-bottom:4px; border:1px solid transparent;
  font-size:12.5px; color:var(--text); white-space:normal; }
.cfg-li:hover { background:var(--chip); } .cfg-li.act { border-color:var(--accent); background:var(--sel-bg); }
.cfg-li > div { flex:1; min-width:0; } .cfg-li .ts { font-size:11px; }
.cfg-li .s { font-size:11px; margin-top:3px; color:var(--muted); line-height:1.6; }
.cfg-li code, .cfg-ctl code { background:var(--chip); padding:0 5px; border-radius:3px; }
.chip { display:inline-block; background:var(--chip); border-radius:999px; padding:0 7px; margin:1px 3px 1px 0; color:var(--text);
  font-size:11px; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:top; }
.modal.cfgm input[type=checkbox] { width:auto; flex:none; margin-top:3px; }
.cfg-g { font-size:12px; font-weight:bold; color:var(--other); margin:18px 0 6px; padding-bottom:4px; border-bottom:1px solid var(--line); }
.cfg-row { display:grid; grid-template-columns:220px 1fr; gap:12px; padding:7px 0; align-items:start; }
.cfg-lab { font-size:12.5px; } .cfg-lab .hint { margin-top:2px; }
.cfg-ctl { display:flex; flex-direction:column; gap:5px; font-size:12.5px; }
.st-line { font-size:11px; } .st.cu { color:var(--cu-fg); }
@media (max-width:700px) { .cfg-b { flex-direction:column; } .cfg-list { width:auto; max-height:40%; border-right:none;
  border-bottom:1px solid var(--line); } .cfg-row { grid-template-columns:1fr; gap:4px; } }

/* Claude と会議。#talkModal・#talkPresetModal は流用する現行の JS が open クラスで開閉する */
.tbtn.talk.on { background:rgba(192,132,252,.16); border-color:var(--claude); }
.tbtn.talk.on .sw { background:var(--claude); }
.banner.talk { border:1px solid var(--claude); background:rgba(192,132,252,.10); }
.banner.talk.show { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.banner.talk .lbtn { margin-left:auto; }
#talkModal.open, #talkPresetModal.open { display:flex; }
.modal .inrow { display:flex; gap:6px; } .modal .inrow select { flex:1; min-width:0; } .modal .inrow .cta { white-space:nowrap; }
.modal .radio .inrow { margin-top:6px; }
.modal .hint.warn { color:var(--warn-fg); }
.modal .cta.voice { margin-top:10px; }
.modal .err { color:var(--danger-fg); font-size:12px; margin-top:8px; }
.modal .err:empty { display:none; }
.cta.talk { background:var(--claude); }
details.more summary { cursor:pointer; color:var(--muted); font-size:12px; margin-top:12px; }
/* Help */
#helpModal .nx-help { max-width:820px; max-height:88dvh; border-radius:16px; box-shadow:0 24px 80px #0005; }
#helpModal .modal-head, #helpModal .modal-foot { padding:18px 24px; flex-shrink:0; }
#helpModal h2 { margin:0; font-size:20px; letter-spacing:.02em; }
#helpModal .modal-body { padding:4px 24px 24px; min-height:0; line-height:1.8; }
#helpModal .nx-help-intro { color:var(--muted); margin:12px 0 24px; }
#helpModal h3 { margin:20px 0 12px; font-size:13px; color:var(--muted); font-weight:600; }
.nx-help-steps { list-style:none; counter-reset:help-step; padding:0; margin:0; display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }
.nx-help-steps li { counter-increment:help-step; padding:18px; background:var(--panel2); border:1px solid var(--line); border-radius:12px; }
.nx-help-steps li::before { content:counter(help-step,decimal-leading-zero); color:var(--cu-fg); font-size:12px; font-weight:700; }
#helpModal h4 { font-size:14px; margin:10px 0 8px; }
#helpModal p { font-size:13px; }
.nx-help-steps p { margin:0; color:var(--muted); }
.nx-help-topics { border-top:1px solid var(--line); }
.nx-help-topics details { border-bottom:1px solid var(--line); }
.nx-help-topics summary { cursor:pointer; padding:14px 0; font-weight:600; }
.nx-help-topics details[open] summary { color:var(--cu-fg); }
.nx-help-topics p { margin:0 0 16px; color:var(--muted); }
#helpModal .modal-foot { justify-content:space-between; gap:16px; }
.nx-help-links { display:flex; flex-wrap:wrap; gap:4px 20px; }
#helpModal .modal-foot > button { flex-shrink:0; }
#helpModal .modal-foot a { color:var(--cu-fg); font-size:12px; text-decoration:none; }
#helpModal .modal-foot a:hover { text-decoration:underline; }
#helpModal :focus-visible { outline:2px solid var(--accent); outline-offset:3px; }
@media (max-width:640px) {
  .nx-help-steps { grid-template-columns:1fr; }
  #helpModal .modal-head, #helpModal .modal-foot { padding:14px 18px; }
  #helpModal .modal-body { padding:0 18px 18px; }
}
/* 流用する現行のモーダル（声の設定・ペルソナ編集）。トークンに合わせて現行の見た目を写す */
.modal-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.5); z-index:35; align-items:center; justify-content:center; }
.modal-overlay.open { display:flex; }
.modal-overlay .modal { padding:0; width:92vw; max-height:80vh; display:flex; flex-direction:column; }
.modal-head, .modal-foot { display:flex; align-items:center; gap:8px; padding:12px 16px; }
.modal-head { justify-content:space-between; font-weight:600; border-bottom:1px solid var(--line); }
.modal-foot { justify-content:flex-end; border-top:1px solid var(--line); }
.modal-head button, .modal-foot button, .modal-body > div > button { background:var(--chip); border:1px solid var(--line);
  border-radius:6px; padding:5px 12px; }
.modal-foot button.pri { background:var(--accent); border-color:var(--accent); color:#fff; }
.modal-foot .saved { color:var(--green); margin-right:auto; display:none; }
.modal-body { padding:16px; overflow-y:auto; flex:1; }
.modal-overlay .modal label { margin:0; }
#personaTable, #glossaryTable, #customCmdTable { border-collapse:collapse; }
:is(#personaTable, #glossaryTable, #customCmdTable) :is(th, td) { border:1px solid var(--line); padding:4px 6px; text-align:left;
  font-weight:normal; color:var(--muted); }
:is(#personaTable, #glossaryTable, #customCmdTable) td { padding:0; color:var(--text); }
:is(#personaTable, #glossaryTable, #customCmdTable) td :is(input[type=text], textarea) { border:none; border-radius:0; width:100%;
  padding:5px 6px; background:transparent; color:var(--text); font:inherit; resize:vertical; }
#glossaryTable th select { border:none; background:transparent; padding:2px; }
#personaTable td.pd { text-align:center; } #personaTable td.pd input { width:auto; }
:is(#personaTable, #glossaryTable, #customCmdTable) td.gl-del { width:30px; text-align:center; cursor:pointer; color:var(--muted); }
:is(#personaTable, #glossaryTable, #customCmdTable) td.gl-del:hover { color:var(--danger-fg); }
/* 設定・ようこそ・スキル更新（現行のモーダル）。現行の見た目をトークンで写す */
#cfgModal .modal, #welcomeModal .modal, #skillUpdateModal .modal { max-width:720px; }
.modal-overlay input[type=checkbox] { width:auto; }
.modal-foot button.dan { background:var(--red); border-color:var(--red); color:#fff; }
.modal-body a { color:var(--accent); }
#cfgBody { display:grid; grid-template-columns:140px 1fr; gap:8px 12px; align-items:center; }
#cfgBody label { color:var(--muted); text-align:right; }
#cfgBody textarea { width:100%; min-height:60px; resize:vertical; background:var(--panel2); border:1px solid var(--line);
  color:var(--text); border-radius:6px; padding:5px 8px; font:12px ui-monospace,monospace; }
#cfgBody label.cfg-child-label::before { content:"↳ "; }
#cfgBody .cfg-panel, #cfgBody .cfg-row { display:contents; }
#cfgBody .cfg-panel[hidden], #cfgBody .cfg-row[hidden], #cfgBody .cfg-empty[hidden] { display:none; }
#cfgBody :is(.cfg-section, .cfg-empty, .cfg-skill, .cfg-doc, .cfg-warn) { grid-column:1/-1; }
#cfgBody .cfg-section { font-weight:bold; padding:8px 0 4px; border-bottom:1px solid var(--line); margin-top:4px; }
#cfgBody .cfg-empty { text-align:center; color:var(--muted); font-size:12px; padding:24px 0; }
#cfgBody .cfg-doc { font-size:11px; padding:2px 0 6px; }
.cfg-warn { font-size:11px; padding:6px 8px; background:var(--chip); border-left:3px solid var(--amber); color:var(--muted);
  margin:2px 0 4px; line-height:1.5; }
#cfgPathWarn { margin:0 16px 8px; }
.modal-head .cfg-mode { display:inline-flex; gap:2px; margin-left:auto; margin-right:10px; background:var(--chip); border-radius:999px; padding:2px; }
.modal-head .cfg-mode button { border:none; border-radius:999px; padding:3px 10px; font-size:11px; background:none; color:var(--muted); }
.modal-head .cfg-mode button[aria-pressed="true"] { background:var(--accent); color:#fff; }
.cfg-tabs { display:flex; flex:0 0 auto; gap:2px; padding:0 12px; border-bottom:1px solid var(--line); overflow-x:auto; }
.cfg-tabs button { background:none; border:none; border-bottom:2px solid transparent; padding:8px 10px; font-size:12px;
  color:var(--muted); white-space:nowrap; }
.cfg-tabs button[aria-selected="true"] { color:var(--text); border-bottom-color:var(--accent); }
.cfg-tabs .cfg-count { font-size:10px; margin-left:4px; color:var(--muted); }
.cfg-hint { font-size:11px; color:var(--muted); margin-right:auto; }
.wc-opt { font-size:11px; line-height:1.7; color:var(--muted); margin-top:8px; padding:6px 8px; border-left:2px solid var(--line); }
.wc-dismiss { padding:0 16px 12px; text-align:right; font-size:11px; color:var(--muted); }
.wc-dismiss label { cursor:pointer; display:inline-flex; align-items:center; gap:5px; }
.wc-row { display:flex; align-items:center; gap:8px; padding:5px 0; font-size:12px; }
.wc-row code { color:var(--muted); font-size:11px; overflow-wrap:anywhere; }
.wc-row button { flex-shrink:0; background:var(--chip); border:1px solid var(--line); border-radius:6px; padding:3px 10px; }
.wc-h { font-weight:bold; margin:10px 0 4px; font-size:12px; }
.wc-li { color:var(--muted); font-size:11px; padding:2px 0 2px 10px; }
.voice-row { display:flex; align-items:center; gap:8px; margin:6px 0; }
.voice-row label { width:72px; flex-shrink:0; }
.voice-row input[type=range], .voice-row select { flex:1; }
.voice-row span { width:40px; text-align:right; font-variant-numeric:tabular-nums; }
/* 話者の名前付け・覚えている声（現行のモーダル）。現行の見た目をトークンで写す */
#nxCfModal { z-index:36; }  /* 現行のモーダル（.modal-overlay）から開く確認も、その上に出す */
#speakerModal .modal { max-width:94vw; }
#spkInfo:empty { display:none; }
#speakerModal .modal-body button { background:var(--chip); border:1px solid var(--line); border-radius:6px; padding:3px 10px; font-size:12px; }
#speakerModal .modal-body button.dan { background:var(--red); border-color:var(--red); color:#fff; }
#speakerModal button:disabled { opacity:.5; cursor:default; }
#speakerModal .modal-body input:not([type=checkbox]), #speakerModal .modal-body select { width:140px; flex:none; padding:4px 7px; }
#speakerModal .modal-body input.spk-group { width:110px; }
.spk-row { display:flex; align-items:center; gap:8px; padding:4px 0; font-size:13px; }
.spk-row .spk-label { flex:none; width:64px; font-weight:bold; }
.spk-row .spk-meta { flex:none; width:150px; color:var(--muted); font-size:11px; }
.spk-person { flex:none; font-size:11px; color:var(--muted); white-space:nowrap; display:inline-flex; align-items:center; gap:2px; }
.spk-sub { font-size:12px; margin:14px 0 4px; font-weight:bold; }
.spk-row .spk-example { flex:1; min-width:0; color:var(--muted); overflow:hidden; display:-webkit-box; -webkit-line-clamp:2;
  -webkit-box-orient:vertical; }
.vp-person { flex-wrap:wrap; }
.vp-person .vp-name { flex:none; width:140px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.vp-person .vp-count { flex:none; width:36px; text-align:right; color:var(--muted); }
.vp-share { display:flex; gap:8px; margin:8px 0; }
.vp-clusters { flex-basis:100%; padding-left:16px; }
.vp-clusters:empty { display:none; }
.spk-row.vp-different { background:color-mix(in srgb, var(--amber) 12%, transparent); }
.spk-row.vp-outlier { opacity:.65; }
.vp-kind { flex:none; width:150px; }
.vp-hint { display:block; font-size:10px; color:var(--muted); }
.vp-sources { flex:none; max-width:260px; color:var(--muted); font-size:11px; overflow-wrap:anywhere; }

/* toast */
.toast { position:fixed; left:50%; bottom:60px; transform:translateX(-50%); background:var(--toast-bg); color:var(--toast-fg);
  padding:8px 16px; border-radius:8px; font-size:12.5px; z-index:40; opacity:0; transition:opacity .2s; pointer-events:none; }
.toast.show { opacity:1; }
.toast button { background:transparent; border:1px solid #fff6; color:inherit; border-radius:4px; margin-left:10px;
  padding:1px 8px; pointer-events:auto; }
""" + _CSS_CONSOLE + """\
/* 端末は pyte の色が暗い地向けなので、ライトでも暗い地のまま（--con-bg / --con-fg は _LIGHT で上書きしない） */
#consolec, .aicon { background:var(--con-bg); color:var(--con-fg); }
#consoleInput.composing { background:var(--con-bg); color:var(--con-fg); }
"""

_NEXT_CSS += _CSS_WELCOME
