"""/next の会議ごとの設定モーダルを node で検証する

- 一覧は会議名ごと（名前なし・日次は除く）。絞り込み・表示中をすべて選ぶ・個別の設定がある会議だけ（matched !== "(defaults)"）
- 複数選択で値が違う項目は「（会議によって違う）」。空欄の文字列項目（値が違う会議の作業フォルダなど）は送らない
- 変えた項目だけを set に入れ、POST /api/meeting-settings {meetings, set} を 1 回だけ送る。analyze は true / false / "default"
- shared の会議には注意書き。notion_url は https のみ。保存できなければ閉じない
- 設定を取れなければその旨を出す。文字の項目で Enter を押すと保存する（日本語入力の確定は除く）
- 入口: 会議タブのボタン・各会議の ⚙・その他メニュー・開始モーダルの「変更」（保存後は開始モーダルに戻って設定を取り直す）

実行: uv run python tests/test_next_mtgcfg_js.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_next_js_core import _NEXT_JS_CORE
from shadow_clerk._daemon_dashboard_next_js_extract import _NEXT_JS_EXTRACT
from shadow_clerk._daemon_dashboard_next_js_list import _NEXT_JS_LIST
from shadow_clerk._daemon_dashboard_next_js_mtgcfg import _NEXT_JS_MTGCFG
from shadow_clerk._daemon_dashboard_next_js_start import _NEXT_JS_START
from shadow_clerk._daemon_dashboard_next_js_transcript import _NEXT_JS_TRANSCRIPT
from shadow_clerk.i18n import STRINGS

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_FILES = {
    "transcript-202610301000@週次定例.txt": {"meeting_group": "週次定例", "dt": "202610301000"},
    "transcript-202610231000@週次定例.txt": {"meeting_group": "週次定例", "dt": "202610231000"},
    "transcript-202610291400@acme 社 打ち合わせ.txt": {"meeting_group": "acme 社 打ち合わせ", "dt": "202610291400"},
    "transcript-202610281500@acme 契約レビュー.txt": {"meeting_group": "acme 契約レビュー", "dt": "202610281500"},
    "transcript-202610271100@1on1.txt": {"meeting_group": "1on1", "dt": "202610271100"},
    "transcript-202610261000.txt": {"meeting_group": "ad-hoc", "dt": "202610261000"},
    "transcript-20261025.txt": {"dt": "20261025"},
}

_PRE = "const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";\nconst FILES=" + json.dumps(
    _FILES, ensure_ascii=False) + ";\n" + r"""
const mkEl=()=>({textContent:'',innerHTML:'',className:'',title:'',style:{},dataset:{},value:'',checked:false,disabled:false,
  children:[],options:[],
  classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
    toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
  handlers:{},addEventListener(t,f){(this.handlers[t]=this.handlers[t]||[]).push(f);},setAttribute(){},getAttribute(){return null;},
  appendChild(c){this.children.push(c);},querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},
  focus(){},select(){},remove(){}});
const els={};
const document={getElementById:id=>els[id]||(els[id]=mkEl()),createElement:mkEl,querySelectorAll:()=>[],querySelector:()=>null,
  addEventListener(){},body:mkEl(),documentElement:mkEl()};
const localStorage={getItem(){return null;},setItem(){}};
const location={hash:'',pathname:'/next',search:''};
const history={replaceState(){}};
const window={addEventListener(){},innerWidth:1000,innerHeight:700};
const timers=[];
const setTimeout=f=>{timers.push(f);return timers.length;};
const clearTimeout=()=>{};
const setInterval=()=>0;
const posts=[],gets=[];
const BASE={matched:'(defaults)',shared:false,analyze:null,publish:true,workdir:'',publish_to:'artifact',notion_url:'',publish_advice:false};
const MOCK={auto:true,saveResp:{status:'ok',path:'/x/meeting.yaml'},rules:{
  '週次定例':{matched:'^週次定例$',analyze:true,workdir:'/w'},
  'acme 社 打ち合わせ':{matched:'acme',shared:true,publish:false,workdir:'/a'},
  'acme 契約レビュー':{matched:'acme',shared:true,publish:false,workdir:'/a'},
}};
const fetch=async (url,opt)=>{
  const ok=v=>({json:async()=>JSON.parse(JSON.stringify(v))});
  if(opt&&opt.method==='POST'){
    const b=JSON.parse(opt.body);posts.push([url,b]);
    if(url==='/api/meeting-settings')return ok(MOCK.saveResp);
    return ok({status:'ok'});
  }
  gets.push(url);
  if(url.startsWith('/api/status'))return ok({running:true,session:null,language:'ja'});
  if(url.startsWith('/api/config'))return ok({auto_analyze:MOCK.auto});
  if(url.startsWith('/api/gcal-events'))return ok({enabled:true,events:[]});
  if(url.startsWith('/api/meeting-settings')){
    if(MOCK.failGet)throw new Error('down');
    const names=(url.split('?')[1]||'').split('&').filter(p=>p.startsWith('meeting=')).map(p=>decodeURIComponent(p.slice(8)));
    return ok({status:'ok',path:'/x/meeting.yaml',meetings:names.map(name=>({name,...BASE,...(MOCK.rules[name]||{})}))});
  }
  if(url.startsWith('/api/files'))return ok({files:Object.keys(FILES),active:'',file_info:FILES});
  return ok({lines:[]});
};
class EventSource{constructor(){this.h={};}addEventListener(t,f){(this.h[t]=this.h[t]||[]).push(f);}close(){}}
const tick=()=>new Promise(r=>setImmediate(r));
const settle=async()=>{for(let i=0;i<10;i++)await tick();};
const fire=async(id,type,target)=>{(els[id].handlers[type]||[]).forEach(f=>f({target:target||els[id],preventDefault(){},stopPropagation(){}}));
  await settle();};
const click=id=>fire(id,'click');
const pick=(name,on)=>fire('nxMcItems','change',{dataset:{pick:name},checked:on});
const edit=(k,value)=>fire('nxMcEd','change',{dataset:{k},value});
const shown=id=>els[id].classList.contains('show');
const toast=()=>els.nxToast.children.slice(-1).map(c=>c.textContent)[0]||'';
"""

_BODY = r"""
(async()=>{
const out={};
nxInit();nxEs.onopen&&nxEs.onopen();await settle();
const snap=()=>({items:els.nxMcItems.innerHTML,ed:els.nxMcEd.innerHTML,err:els.nxMcErr.textContent,shown:shown('nxMcModal'),
  all:els.nxMcAll.checked,path:els.nxMcPath.textContent});

/* その他メニューから開く: 選択なし */
gets.length=0;await click('nxMiMtgCfg');
out.open={...snap(),gets:gets.filter(u=>u.startsWith('/api/meeting-settings'))};

/* 2 件選ぶ: 週次定例（個別）と acme 社 打ち合わせ（共通の設定） */
await pick('週次定例',true);await pick('acme 社 打ち合わせ',true);
out.two=snap();
/* 変える: analyze を既定に、Advice を公開、作業フォルダは空欄（違う値なので送らない）、公開先は同じ値のまま */
await edit('analyze','default');await edit('publish_advice','1');await edit('workdir','');await edit('publish_to','artifact');
out.twoEdited=snap();
posts.length=0;await click('nxMcSave');
out.twoSave={posts:posts.slice(),shown:shown('nxMcModal'),toast:toast()};

/* 1 件・同じ値を選び直しただけなら送らない */
await click('nxMiMtgCfg');await pick('1on1',true);await edit('publish','1');
posts.length=0;await click('nxMcSave');out.noChange={posts:posts.slice(),toast:toast(),shown:shown('nxMcModal')};

/* 1 件: 作業フォルダを空にするのは変更（その会議の値は 1 つ） */
await click('nxMiMtgCfg');await pick('週次定例',true);await edit('workdir','  ');
posts.length=0;await click('nxMcSave');out.clearWd=posts.slice();

/* Notion: https 以外は送らない */
await click('nxMiMtgCfg');await pick('1on1',true);await edit('publish_to','notion');
posts.length=0;await click('nxMcSave');out.notionEmpty={posts:posts.slice(),err:els.nxMcErr.textContent,shown:shown('nxMcModal')};
await edit('notion_url','http://www.notion.so/acme/x');
posts.length=0;await click('nxMcSave');out.notionHttp={posts:posts.slice(),err:els.nxMcErr.textContent};
await edit('notion_url','https://www.notion.so/acme/x');
posts.length=0;await click('nxMcSave');out.notionOk=posts.slice();

/* 保存に失敗したら閉じない */
await click('nxMiMtgCfg');await pick('1on1',true);await edit('publish','0');MOCK.saveResp={status:'error',message:'boom'};
posts.length=0;await click('nxMcSave');out.fail={posts:posts.length,shown:shown('nxMcModal'),err:els.nxMcErr.textContent};
MOCK.saveResp={status:'ok',path:'/x/meeting.yaml'};
/* 選び直すと保存前の変更は消える */
await pick('週次定例',true);posts.length=0;await click('nxMcSave');out.resetPend=posts.slice();

/* 絞り込み・表示中をすべて選ぶ・個別の設定がある会議だけ */
await click('nxMiMtgCfg');
els.nxMcQ.value='ACME';await fire('nxMcQ','input');out.filtered=els.nxMcItems.innerHTML;
els.nxMcAll.checked=true;await fire('nxMcAll','change');out.allSel=[...nxMc.sel];out.allChecked=els.nxMcAll.checked;
els.nxMcQ.value='';await fire('nxMcQ','input');out.allCheckedAfter=els.nxMcAll.checked;
els.nxMcOnly.checked=true;await fire('nxMcOnly','change');out.only=els.nxMcItems.innerHTML;
nxModal('nxMcModal',false);

/* 既定の表示に全体の設定値（オフ） */
MOCK.auto=false;await click('nxMiMtgCfg');await pick('1on1',true);out.autoOff=els.nxMcEd.innerHTML;nxModal('nxMcModal',false);MOCK.auto=true;

/* 会議タブ: 「会議ごとの設定」ボタンと各会議の ⚙ */
out.tabHtml=nxMeetingTabHtml();
const actTarget=ds=>({closest:s=>s==='[data-act]'?{dataset:ds}:null});
nxOnListClick({target:actTarget({act:'cfg'}),stopPropagation(){}});await settle();
out.tabAll={shown:shown('nxMcModal'),sel:[...nxMc.sel]};nxModal('nxMcModal',false);
nxOnListClick({target:actTarget({act:'cfg',g:'acme 契約レビュー'}),stopPropagation(){}});await settle();
out.tabOne={shown:shown('nxMcModal'),sel:[...nxMc.sel],ed:els.nxMcEd.innerHTML};nxModal('nxMcModal',false);

/* 開始モーダルの「変更」: まだ記録の無い名前でも選ばれ、保存後は開始モーダルに戻って設定を取り直す */
await click('nxMeetingBtn');els.nxStName.value='新しい会議';(els.nxStName.handlers.input||[]).forEach(f=>f({}));
timers.splice(0).forEach(f=>f());await settle();
const link=els.nxStCfg.children.slice(-1)[0];
(link.handlers.click||[]).forEach(f=>f({preventDefault(){}}));await settle();
out.fromStart={st:shown('nxStModal'),mc:shown('nxMcModal'),sel:[...nxMc.sel],items:els.nxMcItems.innerHTML};
MOCK.rules['新しい会議']={matched:'^新しい会議$',analyze:false};
await edit('analyze','false');posts.length=0;gets.length=0;await click('nxMcSave');
out.backToStart={posts:posts.slice(),st:shown('nxStModal'),mc:shown('nxMcModal'),assist:els.nxStAssist.checked,
  cfg:els.nxStCfg.textContent,refetched:gets.some(u=>u.includes('meeting=%E6%96%B0'))};
/* キャンセルでも開始モーダルに戻る */
(els.nxStCfg.children.slice(-1)[0].handlers.click||[]).forEach(f=>f({preventDefault(){}}));await settle();
posts.length=0;await click('nxMcCancel');out.cancelStart={posts:posts.length,st:shown('nxStModal'),mc:shown('nxMcModal')};
/* 設定を取れなければ「該当なし」ではなく取れなかったと出す */
MOCK.failGet=true;await click('nxMiMtgCfg');out.getFail=els.nxMcItems.innerHTML;MOCK.failGet=false;nxModal('nxMcModal',false);
/* 文字の項目で Enter を押すと保存する（日本語入力の確定の Enter では保存しない） */
const key=async(k,value,extra)=>{(els.nxMcEd.handlers.keydown||[]).forEach(f=>f({key:'Enter',target:{dataset:{k},value},
  preventDefault(){},stopPropagation(){},...extra}));await settle();};
await click('nxMiMtgCfg');await pick('週次定例',true);
posts.length=0;await key('workdir','/new',{isComposing:true});out.enterIme={posts:posts.length,shown:shown('nxMcModal')};
await key('workdir','/new');out.enter={posts:posts.slice(),shown:shown('nxMcModal')};
console.log(JSON.stringify(out));
})().catch(e=>{console.error(e&&e.stack||e);process.exit(1);});
"""


def main() -> int:
    js = (_PRE + _NEXT_JS_CORE + _NEXT_JS_LIST + _NEXT_JS_TRANSCRIPT + _NEXT_JS_EXTRACT + _NEXT_JS_START
          + _NEXT_JS_MTGCFG + _BODY)
    proc = subprocess.run(["node", "-"], input=js, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        print(proc.stderr)
        check("node が動く", False)
        return 1
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    ja = STRINGS["ja"]
    o = out["open"]
    check("その他メニューから開く", o["shown"] is True)
    check("会議名ごとに 1 回で取る（名前なし・日次は含めない）", len(o["gets"]) == 1
          and o["gets"][0].count("meeting=") == 4 and "ad-hoc" not in o["gets"][0], repr(o["gets"]))
    check("一覧に 4 件", all(n in o["items"] for n in ("週次定例", "acme 社 打ち合わせ", "acme 契約レビュー", "1on1")), o["items"][:200])
    check("選んでいなければ案内", ja["nx.mc_pick_title"] in o["ed"], o["ed"][:200])
    check("meeting.yaml の場所を出す", "/x/meeting.yaml" in o["path"], repr(o["path"]))
    check("一覧のチップ: 分析する・作業フォルダ", ja["nx.st_chip_analyze"] in o["items"] and "📁 /w" in o["items"])
    check("一覧: 共通の設定 / 既定の設定を使用", "<code>acme</code>" in o["items"] and ja["nx.mc_uses_defaults"] in o["items"])
    check("一覧: 最新の回の日時", "2026-10-30 10:00" in o["items"], o["items"][:300])
    two = out["two"]
    check("値が違う項目は（会議によって違う）", two["ed"].count(ja["nx.mc_mixed"]) >= 2, two["ed"][:400])
    check("値が違う文字列は空欄・空欄なら変えない", ja["nx.mc_mixed_ph"] in two["ed"])
    check("shared の会議には注意書き", "acme 社 打ち合わせ" in two["ed"].split("⚠")[-1] if "⚠" in two["ed"] else False,
          two["ed"][:600])
    check("shared でない会議は注意書きに出ない", "⚠" in two["ed"] and "週次定例" not in two["ed"].split("⚠")[1].split("</div>")[0])
    check("既定の表示に全体の設定値（オン）", "既定（全体の設定: オン）" in two["ed"])
    check("変えた項目に「保存すると 2件に設定」", "保存すると 2件に設定" in out["twoEdited"]["ed"])
    check("変えた項目だけを 1 回で送る（analyze は default・空欄と同じ値は送らない）", out["twoSave"]["posts"] == [[
        "/api/meeting-settings", {"meetings": ["週次定例", "acme 社 打ち合わせ"],
                                  "set": {"analyze": "default", "publish_advice": True}}]], repr(out["twoSave"]["posts"]))
    check("保存したら閉じてトースト", out["twoSave"]["shown"] is False and out["twoSave"]["toast"] == "2件の会議に設定しました",
          repr(out["twoSave"]))
    check("同じ値なら送らない", out["noChange"]["posts"] == [] and out["noChange"]["toast"] == ja["nx.mc_nothing"],
          repr(out["noChange"]))
    check("1 件で作業フォルダを空にするのは変更", out["clearWd"] == [[
        "/api/meeting-settings", {"meetings": ["週次定例"], "set": {"workdir": ""}}]], repr(out["clearWd"]))
    check("Notion で URL が空なら送らない", out["notionEmpty"]["posts"] == [] and out["notionEmpty"]["err"] == ja["nx.mc_notion_bad"]
          and out["notionEmpty"]["shown"] is True, repr(out["notionEmpty"]))
    check("http の URL は送らない", out["notionHttp"]["posts"] == [] and out["notionHttp"]["err"] == ja["nx.mc_notion_bad"])
    check("https の URL なら送る", out["notionOk"] == [["/api/meeting-settings", {
        "meetings": ["1on1"], "set": {"publish_to": "notion", "notion_url": "https://www.notion.so/acme/x"}}]], repr(out["notionOk"]))
    check("保存に失敗したら閉じずに理由", out["fail"] == {"posts": 1, "shown": True, "err": "boom"}, repr(out["fail"]))
    check("選び直すと保存前の変更は消える", out["resetPend"] == [], repr(out["resetPend"]))
    check("絞り込み（大文字小文字を区別しない）", "acme 社" in out["filtered"] and "週次定例" not in out["filtered"]
          and "1on1" not in out["filtered"])
    check("表示中をすべて選ぶ", sorted(out["allSel"]) == sorted(["acme 社 打ち合わせ", "acme 契約レビュー"]) and out["allChecked"],
          repr(out["allSel"]))
    check("絞り込みを外すと「すべて」は外れる", out["allCheckedAfter"] is False)
    check("個別の設定がある会議だけ（matched !== (defaults)）", "週次定例" in out["only"] and "acme 契約レビュー" in out["only"]
          and "1on1" not in out["only"])
    check("既定の表示に全体の設定値（オフ）", "既定（全体の設定: オフ）" in out["autoOff"])
    check("会議タブに「会議ごとの設定」", 'data-act="cfg"' in out["tabHtml"] and ja["nx.mc_open_all"] in out["tabHtml"])
    check("会議タブのボタン: 選択なしで開く", out["tabAll"] == {"shown": True, "sel": []}, repr(out["tabAll"]))
    check("各会議の ⚙: その会議を選んで開く", out["tabOne"]["shown"] and out["tabOne"]["sel"] == ["acme 契約レビュー"]
          and "<h4>acme 契約レビュー</h4>" in out["tabOne"]["ed"], repr(out["tabOne"]["sel"]))
    fs = out["fromStart"]
    check("開始モーダルの「変更」: 記録の無い名前も選んで開く", fs["mc"] and not fs["st"] and fs["sel"] == ["新しい会議"]
          and "新しい会議" in fs["items"], repr(fs))
    bs = out["backToStart"]
    check("保存は 1 回", bs["posts"] == [["/api/meeting-settings", {"meetings": ["新しい会議"], "set": {"analyze": False}}]],
          repr(bs["posts"]))
    check("保存後は開始モーダルに戻り設定を取り直す", bs["st"] and not bs["mc"] and bs["refetched"]
          and bs["assist"] is False and ja["nx.st_chip_no_analyze"] in bs["cfg"], repr(bs))
    check("キャンセルでも開始モーダルに戻る", out["cancelStart"] == {"posts": 0, "st": True, "mc": False}, repr(out["cancelStart"]))
    check("設定を取れなければ取れなかったと出す（該当なしにしない）",
          bool(ja.get("nx.mc_load_failed")) and ja.get("nx.mc_load_failed", "?") in out["getFail"]
          and ja["nx.mc_none_match"] not in out["getFail"], out["getFail"][:200])
    check("日本語入力の確定の Enter では保存しない", out["enterIme"] == {"posts": 0, "shown": True}, repr(out["enterIme"]))
    check("文字の項目で Enter を押すと、その値で保存する", out["enter"] == {"posts": [["/api/meeting-settings", {
        "meetings": ["週次定例"], "set": {"workdir": "/new"}}]], "shown": False}, repr(out["enter"]))
    check("文言（試作）", ja["nx.mc_mixed"] == "（会議によって違う）" and ja["nx.mc_only_custom"] == "個別の設定がある会議だけ"
          and ja["nx.mc_select_all"] == "表示中をすべて選ぶ")
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
