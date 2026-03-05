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
  font-size: 12px; line-height: 1.6;
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
  font-size:11px; line-height:1.5; color:var(--muted);
}
.ll { white-space:pre-wrap; word-break:break-word; }
.ll.e { color:var(--red); }
.ll.w { color:var(--yellow); }
.interim {
  color: var(--muted); font-style: italic; opacity: 0.7;
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
.panel.hidden { display:none; }
#logp.collapsed #logc { display:none; }
#logp.collapsed { height:auto; }
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
"""
