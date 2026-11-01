"""/next の SSE 再接続とヘッダの状態表示を node で検証する

実行: uv run python tests/test_next_core_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_next_js_core import _NEXT_JS_CORE
from shadow_clerk.i18n import STRINGS

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_PRE = "const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";\n" + r"""
const mkEl=()=>({textContent:'',className:'',title:'',style:{},dataset:{},children:[],
  classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
    toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
  addEventListener(){},setAttribute(){},getAttribute(){return null;},appendChild(c){this.children.push(c);},
  querySelectorAll(){return [];},closest(){return null;}});
const els={};
const document={getElementById:id=>els[id]||(els[id]=mkEl()),createElement:mkEl,querySelectorAll:()=>[],
  addEventListener(){},body:mkEl(),documentElement:mkEl()};
const localStorage={getItem(){return null;},setItem(){}};
const window={};
const timers=[];
const setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;};
const clearTimeout=()=>{};
const setInterval=()=>0;
const fetches=[];
const fetch=async url=>{fetches.push(url);return {json:async()=>({running:true,session:null,translating:false,
  mute_mic:false,mute_monitor:false,use_mic:true,use_monitor:true})};};
const instances=[];
class EventSource{constructor(url){this.url=url;this.closed=false;instances.push(this);}
  addEventListener(){}close(){this.closed=true;}}
const statusText=()=>els.nxStatusText.textContent;
const tick=()=>new Promise(r=>setImmediate(r));
"""

_BODY = r"""
(async()=>{
const out={};
nxInit();
out.instances0=instances.length;
instances[0].onopen();await tick();
out.fetchesAfterOpen=fetches.length;
out.statusIdle=statusText();
instances[0].onerror();
out.statusDown=statusText();
out.statusDownClass=els.nxStatus.className;
out.timer=timers.map(t=>t.ms);
out.closed=instances[0].closed;
timers.shift().fn();
out.instances1=instances.length;
const before=fetches.length;
instances[1].onopen();await tick();
out.refetched=fetches.length-before;
out.fetchedUrl=fetches[fetches.length-1];
out.statusBack=statusText();
instances[1].onerror();
out.statusDown2=statusText();
console.log(JSON.stringify(out));
})();
"""


def main() -> None:
    r = subprocess.run(["node", "-e", _PRE + _NEXT_JS_CORE + _BODY], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-500:])
        sys.exit(1)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    ja = STRINGS["ja"]
    check("起動時に EventSource を 1 本つなぐ", out["instances0"] == 1, repr(out["instances0"]))
    check("つながったら /api/status を 1 回取る", out["fetchesAfterOpen"] == 1 and out["statusIdle"] == ja["nx.status_idle"],
          repr((out["fetchesAfterOpen"], out["statusIdle"])))
    check("onerror でヘッダが「接続が切れています」になる",
          out["statusDown"] == ja["nx.status_disconnected"] and "disconnected" in out["statusDownClass"], repr(out["statusDown"]))
    check("古い EventSource を閉じ、3 秒後に再接続を予約する", out["closed"] and out["timer"] == [3000], repr(out["timer"]))
    check("再接続で新しい EventSource を作る", out["instances1"] == 2, repr(out["instances1"]))
    check("再接続後に /api/status を 1 回だけ取り直す",
          out["refetched"] == 1 and out["fetchedUrl"] == "/api/status", repr((out["refetched"], out["fetchedUrl"])))
    check("取り直したら状態表示が戻る", out["statusBack"] == ja["nx.status_idle"], repr(out["statusBack"]))
    check("再び切れたらまた「接続が切れています」", out["statusDown2"] == ja["nx.status_disconnected"], repr(out["statusDown2"]))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
