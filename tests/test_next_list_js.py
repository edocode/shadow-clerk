"""/next 左ペインの会議グループ化・並び・ファイルを開く動作を node で検証する

実行: uv run python tests/test_next_list_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_next_js_list import _NEXT_JS_LIST
from shadow_clerk.i18n import STRINGS

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_FILES = {
    "files": ["transcript-202610311950@acme_sync.txt", "transcript-20261031.txt", "transcript-202610301535.txt",
              "transcript-202610300820@aaa_1on1.txt", "transcript-202610291000@acme_sync.txt", "transcript-20261030.txt"],
    "active": "transcript-202610311950@acme_sync.txt",
    "file_info": {
        "transcript-202610311950@acme_sync.txt": {"label": "2026-10-31 19:50 @acme_sync", "dt": "202610311950", "name": "acme_sync",
                                                  "meeting_group": "acme_sync", "has_summary": True, "has_advice": True},
        "transcript-20261031.txt": {"label": "2026-10-31", "dt": "20261031", "name": None, "meeting_group": None},
        "transcript-202610301535.txt": {"label": "2026-10-30 15:35", "dt": "202610301535", "name": None, "meeting_group": "ad-hoc"},
        "transcript-202610300820@aaa_1on1.txt": {"label": "2026-10-30 08:20 @aaa_1on1", "dt": "202610300820",
                                                   "name": "aaa_1on1", "meeting_group": "aaa_1on1"},
        "transcript-202610291000@acme_sync.txt": {"label": "2026-10-29 10:00 @acme_sync", "dt": "202610291000", "name": "acme_sync",
                                                  "meeting_group": "acme_sync"},
        "transcript-20261030.txt": {"label": "2026-10-30", "dt": "20261030", "name": None, "meeting_group": None},
    },
}

_PRE = "const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";\nconst FILES=" + json.dumps(_FILES) + ";\n" + r"""
const mkEl=()=>({textContent:'',innerHTML:'',className:'',title:'',style:{},dataset:{},value:'',children:[],
  classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
    toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
  handlers:{},addEventListener(t,f){this.handlers[t]=f;},setAttribute(){},getAttribute(){return null;},appendChild(c){this.children.push(c);},
  querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},focus(){},select(){}});
const els={};
const radios=[{value:'existing',checked:false},{value:'new',checked:true}];
const document={getElementById:id=>els[id]||(els[id]=mkEl()),createElement:mkEl,querySelectorAll:()=>[],
  addEventListener(){},body:mkEl(),documentElement:mkEl()};
const store={};
const localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=v;}};
const location={hash:'',pathname:'/next',search:''};
const history={replaceState(a,b,u){location.hash=u.startsWith('#')?u:'';}};
const window={addEventListener(){}};
const timers=[];
const setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length;};
const clearTimeout=()=>{};
const setInterval=()=>0;
const posts=[];
const fetch=async (url,opt)=>{
  if(opt&&opt.method==='POST'){posts.push([url,JSON.parse(opt.body)]);return {json:async()=>({status:'ok',new_file:'transcript-202610311950@x.txt'})};}
  return {json:async()=>JSON.parse(JSON.stringify(FILES))};};
const tick=()=>new Promise(r=>setImmediate(r));
const nxRenderers=[];
const nxState={session:null};
function nxEl(id){return document.getElementById(id);}
function nxStoreGet(k){return localStorage.getItem(k);}
function nxStoreSet(k,v){localStorage.setItem(k,v);}
async function nxApi(path,body){const r=await fetch(path,body===undefined?undefined:{method:'POST',body:JSON.stringify(body)});return r.json();}
const sse={};
function nxOn(name,f){sse[name]=f;}
function nxToast(m){toasts.push(m);}
const toasts=[];
let renderCount=0;
function nxRenderAll(){renderCount++;nxRenderers.forEach(f=>f());}
"""

_BODY = r"""
(async()=>{
const out={};
await tick();await tick();
const files=nxFiles;
out.nFiles=files.length;
out.first=files[0];
const g=nxMeetingGroups(files);
out.groupKeys=[...g.keys()];
out.groupFiles=[...g.get('acme_sync').map(f=>f.name)];
out.abcKeys=[...nxMeetingGroups(files,'abc').keys()];
out.cur=nxState.cur;
out.hashOnLoad=location.hash;
nxOpenFile('transcript-20261030.txt');
out.cur2=nxState.cur;out.hash2=location.hash;out.renders=renderCount;
// 状態表示: 記録中でないファイルを見ているときだけ押せて、検索タブからは日付タブへ戻って記録中を開く
nxState.ltab='search';nxRenderAll();
out.goOn=nxEl('nxStatus').dataset.go;out.goTitle=nxEl('nxStatus').title;
nxEl('nxStatus').handlers.click();
out.goCur=nxState.cur;out.goTab=nxState.ltab;out.goAfter=nxEl('nxStatus').dataset.go;
nxEl('nxStatus').handlers.click();
out.goCurNoop=nxState.cur;
nxOpenFile('transcript-20261030.txt');
// その日まだ話していなくて記録中のファイルが無くても、押せて開き、一覧を読み直しても開いたまま
const realActive=FILES.active;FILES.active='transcript-20261101.txt';
await nxLoadFiles();
out.goNoFile=nxEl('nxStatus').dataset.go;
nxEl('nxStatus').handlers.click();await nxLoadFiles();
out.noFileCur=[nxState.cur,nxEl('nxFileTitle').textContent];
FILES.active=realActive;await nxLoadFiles();
nxOpenFile('transcript-20261030.txt');
const dh=nxDateHtml();
out.dateHasLive=dh.includes(I18N['nx.live']);
out.dateHasSummary=dh.includes(I18N['nx.pill_summary'])&&dh.includes(I18N['nx.pill_ai']);
out.dateOrder=[...dh.matchAll(/data-f="([^"]+)"/g)].map(m=>m[1]);
out.dateNoAdhocName=!dh.includes('>ad-hoc<');
nxState.ltab='mtg';
const mh=nxMeetingTabHtml();
out.mtgHasCounts=mh.includes('2'+I18N['nx.times'].replace('{n}','').trim())||mh.includes(I18N['nx.times'].replace('{n}','2'));
out.mtgNoAdhoc=!mh.includes('ad-hoc');
// 会議名を変える（グループ）と記録の会議名
nxState.cur='transcript-202610311950@acme_sync.txt';
await nxRenameGroup('acme_sync','acme_weekly');
out.groupPosts=posts.map(p=>JSON.stringify(p));
posts.length=0;
await nxRenameRecord('transcript-202610301535.txt','');
await nxRenameRecord('transcript-202610301535.txt','alice');
out.recPosts=posts.map(p=>JSON.stringify(p));
out.curAfter=nxState.cur;
// 記録の会議名: 「新しい会議名」が選ばれた状態でプルダウンから選ぶと、その会議名で送られる
posts.length=0;
nxEl('nxRmModal').querySelectorAll=()=>radios;
nxEl('nxRmModal').querySelector=()=>radios.find(r=>r.checked)||null;
nxEl('nxRmSel').value='acme_sync';nxEl('nxRmName').value='';
nxEl('nxRmSel').handlers.change();
out.radioAfterSelect=radios.find(r=>r.checked).value;
nxState.cur='transcript-202610301535.txt';
nxApplyRecordName();await tick();await tick();
out.applyPost=posts.map(p=>JSON.stringify(p));
radios[0].checked=false;radios[1].checked=true;
nxEl('nxRmName').value='typed';nxEl('nxRmName').handlers.focus();
out.radioAfterFocus=radios.find(r=>r.checked).value;
// 会議が始まると別のファイルを見ていても会議のファイルへ、終わると日次のファイルへ移る。検索タブは日付タブへ戻る
nxOpenFile('transcript-20261030.txt');nxState.ltab='search';
FILES.active='transcript-202610311950@acme_sync.txt';
await sse.session({content:'/data/transcript-202610311950@acme_sync.txt'});
out.sessionStart=[nxState.cur,nxState.ltab,nxState.session];
FILES.active='transcript-20261031.txt';
await sse.session({content:''});
out.sessionEnd=[nxState.cur,nxState.session];
console.log(JSON.stringify(out));
})();
"""


def main() -> None:
    r = subprocess.run(["node", "-e", _PRE + _NEXT_JS_LIST + _BODY],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-800:])
        sys.exit(1)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    check("nxFiles は /api/files の全ファイルで {name, display, meeting, dt} を持つ",
          out["nFiles"] == 6 and out["first"]["name"] == "transcript-202610311950@acme_sync.txt"
          and out["first"]["display"] == "2026-10-31 19:50 @acme_sync" and out["first"]["meeting"] == "acme_sync"
          and out["first"]["dt"] == "202610311950", repr(out["first"]))
    check("会議グループは日次と ad-hoc を除き、新しい順（最新の回が先）",
          out["groupKeys"] == ["acme_sync", "aaa_1on1"], repr(out["groupKeys"]))
    check("グループ内は新しい順", out["groupFiles"] == ["transcript-202610311950@acme_sync.txt", "transcript-202610291000@acme_sync.txt"],
          repr(out["groupFiles"]))
    check("あいうえお順は localeCompare ja", out["abcKeys"] == ["aaa_1on1", "acme_sync"], repr(out["abcKeys"]))
    check("最初は記録中のファイルを開く", out["cur"] == "transcript-202610311950@acme_sync.txt", repr(out["cur"]))
    check("nxOpenFile は cur・URL ハッシュ・再描画", out["cur2"] == "transcript-20261030.txt"
          and out["hash2"] == "#transcript-20261030.txt" and out["renders"] >= 2, repr((out["cur2"], out["hash2"], out["renders"])))
    check("状態表示: 記録中でないファイルを見ていると押せる", out["goOn"] == "1"
          and out["goTitle"] == STRINGS["ja"]["nx.status_go_title"], repr((out["goOn"], out["goTitle"])))
    check("状態表示を押すと記録中を開き、検索タブは日付タブに戻る",
          out["goCur"] == "transcript-202610311950@acme_sync.txt" and out["goTab"] == "date" and out["goAfter"] == ""
          and out["goCurNoop"] == out["goCur"], repr((out["goCur"], out["goTab"], out["goAfter"])))
    check("記録中のファイルがまだ無くても押せて開き、開いたまま", out["goNoFile"] == "1"
          and out["noFileCur"] == ["transcript-20261101.txt", "transcript-20261101.txt"], repr((out["goNoFile"], out["noFileCur"])))
    check("日付タブ: 記録中の印と議事録・AI の印", out["dateHasLive"] and out["dateHasSummary"])
    check("日付タブ: 新しい日から並ぶ", out["dateOrder"][0] == "transcript-20261031.txt"
          or out["dateOrder"][0].startswith("transcript-2026103119"), repr(out["dateOrder"][:3]))
    check("会議タブ: 回数が出て ad-hoc は出ない", out["mtgHasCounts"] and out["mtgNoAdhoc"])
    check("会議名の変更は会議の全回に 1 件ずつ {file,name} を送る",
          out["groupPosts"] == [
              '["/api/transcript/rename-meeting",{"file":"transcript-202610311950@acme_sync.txt","name":"acme_weekly"}]',
              '["/api/transcript/rename-meeting",{"file":"transcript-202610291000@acme_sync.txt","name":"acme_weekly"}]'],
          repr(out["groupPosts"]))
    check("記録の会議名は {file,name}（空欄は名前なし）", out["recPosts"] == [
        '["/api/transcript/rename-meeting",{"file":"transcript-202610301535.txt","name":""}]',
        '["/api/transcript/rename-meeting",{"file":"transcript-202610301535.txt","name":"alice"}]'], repr(out["recPosts"]))
    check("プルダウンを選ぶと既存の会議が選択され、適用で選んだ会議名が送られる", out["radioAfterSelect"] == "existing"
          and out["applyPost"] == ['["/api/transcript/rename-meeting",{"file":"transcript-202610301535.txt","name":"acme_sync"}]'],
          repr((out["radioAfterSelect"], out["applyPost"])))
    check("入力欄にフォーカスすると新しい会議名が選択される", out["radioAfterFocus"] == "new")
    check("会議が始まると会議のファイルへ移り、検索タブは日付タブへ戻る", out["sessionStart"] == [
        "transcript-202610311950@acme_sync.txt", "date", "/data/transcript-202610311950@acme_sync.txt"], repr(out["sessionStart"]))
    check("会議が終わると日次のファイルへ戻る", out["sessionEnd"] == ["transcript-20261031.txt", None], repr(out["sessionEnd"]))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
