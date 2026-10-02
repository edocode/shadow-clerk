"""AI Console の役割タブの JS を node で検証する

実行: uv run python tests/test_console_role_js.py
"""
from __future__ import annotations
import shutil
import subprocess
import sys

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

from shadow_clerk._daemon_dashboard_js_console_role import _JS_TEMPLATE_CONSOLE_ROLE  # noqa: E402

HARNESS = r"""
let logTab='console',_consoleRunning=null,_consoleLoaded=true,_lastCols=7,applied=[],tabs={};
const I18N={};
function applyConsole(d){applied.push(d.role);}
function switchLogTab(t){logTab=t;}
function updateConsoleStatus(r){}
const document={getElementById:id=>{tabs[id]=tabs[id]||{dataset:{},classList:{toggle(){}}};return tabs[id];}};
""" + _JS_TEMPLATE_CONSOLE_ROLE + r"""
const out={};
onConsoleEvent({role:'talk',running:true,rows:{}});
out.ignored=applied.length;
out.bgTalk=tabs.tabConsoleTalk.dataset.bg;
onConsoleEvent({running:true,rows:{}});
out.appliedDefault=applied.slice();
out.url=consoleUrl('/api/console');
selectConsoleRole('talk');
out.afterSwitch=[_consoleRole,_consoleLoaded,_lastCols,consoleUrl('/api/console'),JSON.parse(consoleBody({data:'x'}))];
onConsoleEvent({role:'talk',running:true,rows:{}});
out.appliedTalk=applied.slice();
syncConsoleRoles({console_running:true,talk_console_running:false});
out.running=Object.assign({},_consoleRoleRunning);
console.log(JSON.stringify(out));
"""

r = subprocess.run(["node", "-e", HARNESS], capture_output=True, text=True, timeout=30)
if r.returncode != 0:
    check("node で実行できる", False, r.stderr[-500:])
    sys.exit(1)
import json  # noqa: E402
out = json.loads(r.stdout.strip().splitlines()[-1])
check("表示していない役割のイベントは描かない", out["ignored"] == 0, repr(out))
check("裏で動いている役割のタブに印", out["bgTalk"] == "1", repr(out))
check("role の無いイベントは assistant", out["appliedDefault"] == [None], repr(out))
check("URL に表示中の役割", out["url"] == "/api/console?role=assistant", out["url"])
check("切り替えで取り直しの状態に戻す", out["afterSwitch"][:3] == ["talk", False, 0], repr(out["afterSwitch"]))
check("切り替え後の URL と body", out["afterSwitch"][3] == "/api/console?role=talk"
      and out["afterSwitch"][4] == {"role": "talk", "data": "x"}, repr(out["afterSwitch"]))
check("切り替え後は talk を描く", out["appliedTalk"] == [None, "talk"], repr(out))
check("status から両方の状態を取る", out["running"] == {"assistant": True, "talk": False}, repr(out))
from shadow_clerk._daemon_dashboard_js_console import _JS_TEMPLATE_CONSOLE as _C  # noqa: E402
_SHOW = _C[_C.index("function showAutoAnalysis("):]
_SHOW = _SHOW[:_SHOW.index("\n}\n") + 3]
HARNESS2 = r"""
let logTab='console',_consoleRunning=null,_consoleLoaded=true,_lastCols=7,applied=[],calls=[];
const I18N={'dash.stop_analysis':'STOP','dash.start_analysis':'START'};
function applyConsole(d){applied.push(d.role||'assistant');}
function switchLogTab(t){logTab=t;}
function updateConsoleStatus(r){}
function togSumPane(){calls.push('tog');}
function switchSumTab(t){calls.push('sum:'+t);}
const els={};
const document={getElementById:id=>{els[id]=els[id]||{dataset:{},textContent:'',title:'',classList:{toggle(){},contains:()=>id==='pnlS'}};return els[id];}};
""" + _JS_TEMPLATE_CONSOLE_ROLE + _SHOW + r"""
const out={};
_consoleRoleRunning.assistant=true;_consoleRole='talk';
updateAnalysisBtn();out.label=els.btnStartAnalysis.textContent;
onConsoleEvent({status_only:true,auto:true,role:'assistant',running:true});
out.talkShown=[_consoleRole,calls.slice(),applied.length];
logTab='logs';
onConsoleEvent({status_only:true,auto:true,role:'assistant',running:true});
out.logsShown=[_consoleRole,applied.length];
calls.length=0;
onConsoleEvent({status_only:true,auto:true,role:'assistant',running:true});
out.once=calls.length;
console.log(JSON.stringify(out));
"""
r2 = subprocess.run(["node", "-e", HARNESS2], capture_output=True, text=True, timeout=30)
if r2.returncode != 0:
    check("node(2) で実行できる", False, r2.stderr[-500:])
    sys.exit(1)
o2 = json.loads(r2.stdout.strip().splitlines()[-1])
check("talk 表示中でも分析ボタンは assistant の状態", o2["label"] == "STOP", repr(o2))
check("talk 表示中の自動起動は S ペインだけ開く", o2["talkShown"] == ["talk", ["tog", "sum:ai"], 0], repr(o2))
check("logs 表示中の自動起動は assistant を選ぶ", o2["logsShown"][0] == "assistant", repr(o2))
check("自動起動の演出は1イベントで1回", o2["once"] == 2, repr(o2))
sys.exit(0 if all(results) else 1)
