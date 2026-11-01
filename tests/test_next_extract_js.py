"""/next の切り出し（会議として切り出す・沈黙で分ける）と 🗑（削除・日次ファイルに戻す）を node で検証する

nxSplitSegments は server の split-by-silence と同じ区切りになることを、同じ入力を
DashboardHandler に一時ディレクトリで実行させ、できた会議ファイルの先頭・末尾の時刻と比べて確かめる。

実行: uv run python tests/test_next_extract_js.py
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-extract-")

from shadow_clerk._daemon_dashboard_handler import DashboardHandler  # noqa: E402
from shadow_clerk._daemon_dashboard_next_js_core import _NEXT_JS_CORE  # noqa: E402
from shadow_clerk._daemon_dashboard_next_js_extract import _NEXT_JS_EXTRACT  # noqa: E402
from shadow_clerk._daemon_dashboard_next_js_list import _NEXT_JS_LIST  # noqa: E402
from shadow_clerk._daemon_dashboard_next_js_transcript import _NEXT_JS_TRANSCRIPT  # noqa: E402
from shadow_clerk.i18n import STRINGS  # noqa: E402

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


# 試作 dashboard-friendly-ui-interactive.js の今日のメモ（sessions[0].lines）
_MEMO = [
    ("09:02", "自分", "おはようございます"), ("09:03", "相手A", "おはようございます。昨日の件、見ておきました"),
    ("09:04", "自分", "ありがとうございます、助かります"),
    ("10:00", "相手A", "では acme 社との打ち合わせを始めます"), ("10:01", "相手B", "よろしくお願いします。まず見積もりの件からですが"),
    ("10:02", "自分", "前回いただいた要件で金額を出しています"), ("10:03", "相手B", "内訳を見せていただけますか"),
    ("10:04", "自分", "画面に出します。開発が7割、テストが2割です"), ("10:05", "相手A", "テストの割合は妥当だと思います"),
    ("10:06", "相手B", "納期はもう少し早められますか？"), ("10:07", "自分", "範囲を絞れば可能です"),
    ("10:08", "相手B", "どの機能を後回しにできますか"), ("10:09", "自分", "2週間なら前倒しできます"),
    ("10:10", "相手A", "管理画面は次の段階でも構いません"), ("10:11", "自分", "それなら 11/14 に出せます"),
    ("10:12", "相手B", "社内で確認します"), ("10:13", "相手A", "支払い条件は前回どおりでお願いします"),
    ("10:14", "自分", "承知しました"), ("10:15", "相手A", "では次回までに修正版をお送りします"),
    ("10:16", "相手B", "負荷テストの目標値はどうしますか"), ("10:17", "自分", "まだ決めていません。来週までに案を出します"),
    ("10:18", "相手B", "お願いします"), ("10:19", "相手A", "次回は来週の同じ時間で"), ("10:20", "自分", "大丈夫です"),
    ("10:21", "相手B", "議事録は共有いただけますか"), ("10:22", "自分", "今日中にお送りします"),
    ("10:23", "相手A", "以上です"), ("10:24", "相手B", "ありがとうございました"),
    ("12:17", "Claude", "練習用の会議は終えました。ここで終わりにしますか？"), ("12:18", "自分", "終わります"),
    ("13:40", "alice", "ちょっといいですか、レビューの件で"), ("13:41", "自分", "はい、どうぞ"),
    ("13:42", "alice", "テストの書き方を揃えたいです"), ("13:43", "自分", "雛形を作って共有しますね"),
    ("13:44", "alice", "助かります。金曜までにお願いします"),
]
_DAILY = [f"[2026-10-31 {t}:00] [{w}] {x}" for t, w, x in _MEMO]
# 秒単位の境界: 60 秒の間隔は候補のまま・61 秒で失格、179 秒の沈黙は会議の続き・180 秒で終了、
# 候補開始からちょうど 180 秒で会議と確定
_EDGE = [f"[2026-10-31 {t}] [alice] edge {i}" for i, t in enumerate(
    ["08:00:00", "08:01:00", "08:02:00", "08:03:00", "08:05:59", "08:09:00", "08:10:01",
     "08:20:00", "08:21:00", "08:22:00", "08:23:00", "08:30:00", "08:31:00", "08:32:00", "08:33:00", "08:36:00"])]
_TS = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]")
# (名前, 行, 沈黙の分, 範囲の行 index [a, b] または None)
_CASES = [
    ("memo-10", _DAILY, 10, None), ("memo-1", _DAILY, 1, None), ("memo-3", _DAILY, 3, None),
    ("memo-30", _DAILY, 30, None), ("memo-range-1", _DAILY, 1, [8, 34]), ("memo-head-10", _DAILY, 10, [0, 27]),
    ("memo-tail-1", _DAILY, 1, [28, 34]), ("edge-3", _EDGE, 3, None), ("edge-2", _EDGE, 2, None),
    ("edge-5", _EDGE, 5, None), ("edge-range-1", _EDGE, 1, [5, 15]),
]


class _Noop:
    """split-by-silence が後始末で触る recorder の部品（翻訳 offset の記録・自動ジョブ）は何もしない"""

    def __getattr__(self, name: str) -> object:
        return lambda *a, **k: None


class _Rec:
    def __getattr__(self, name: str) -> object:
        return _Noop()

    def __init__(self, out_dir: str) -> None:
        self._output_dir = out_dir
        self.output_path = os.path.join(out_dir, "transcript-20261031.txt")
        self.transcript_lock = threading.Lock()

    def _execute_command(self, cmd: str) -> None:
        pass


class _Handler(DashboardHandler):
    def __init__(self, out_dir: str, path: str, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.path = path
        self.client_address = ("127.0.0.1", 1)
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        self.recorder = _Rec(out_dir)
        self.file_watcher = None

    def _send_json(self, d: dict) -> None:
        self.sent = d

    def send_error(self, code: int, *_: object) -> None:
        self.sent = {"status": "error", "code": code}


def _server_split(lines: list[str], minutes: int, rng: list[int] | None) -> dict:
    """server の split-by-silence を一時ディレクトリで実行し、できた会議ファイルの先頭・末尾の時刻を返す"""
    out_dir = tempfile.mkdtemp(prefix="split-", dir=os.environ["SHADOW_CLERK_DATA_DIR"])
    daily = os.path.join(out_dir, "transcript-20261031.txt")
    with open(daily, "w", encoding="utf-8") as f:
        f.write("".join(l + "\n" for l in lines))
    body: dict = {"file": "transcript-20261031.txt", "min_silence_minutes": minutes}
    ts = [_TS.match(l).group(1) for l in lines]  # type: ignore[union-attr]
    if rng:
        body |= {"start_ts": ts[rng[0]], "end_ts": ts[rng[1]]}
    h = _Handler(out_dir, "/api/transcript/split-by-silence", body)
    h.do_POST()
    if h.sent.get("status") != "ok":
        return {"segs": None}
    # 応答の files（作った会議ファイル名）だけを読む。ディレクトリにできたものと一致すること
    files = h.sent.get("files")
    if files != sorted(n for n in os.listdir(out_dir) if re.fullmatch(r"transcript-\d{12}\.txt", n)):
        return {"segs": "files mismatch", "files": files}
    segs = []
    for name in files:
        with open(os.path.join(out_dir, name), encoding="utf-8") as f:
            got = [m.group(1) for l in f if (m := _TS.match(l))]
        segs.append([got[0], got[-1]])
    left = []
    if os.path.exists(daily):
        with open(daily, encoding="utf-8") as f:
            left = [m.group(1) for l in f if (m := _TS.match(l))]
    lo, hi = (ts[rng[0]], ts[rng[1]]) if rng else (ts[0], ts[-1])
    return {"segs": segs, "rest": sum(1 for t in left if lo <= t <= hi)}


def _server_extract(target: str, name: str) -> tuple[dict, list[str]]:
    """server の extract-meeting を一時ディレクトリで実行し、応答とディレクトリの会議ファイル名を返す"""
    out_dir = tempfile.mkdtemp(prefix="extract-", dir=os.environ["SHADOW_CLERK_DATA_DIR"])
    with open(os.path.join(out_dir, "transcript-20261031.txt"), "w", encoding="utf-8") as f:
        f.write("".join(l + "\n" for l in _DAILY))
    if target != "new":
        with open(os.path.join(out_dir, target), "w", encoding="utf-8") as f:
            f.write("[2026-10-31 09:00:00] [alice] earlier\n")
    h = _Handler(out_dir, "/api/transcript/extract-meeting", {
        "file": "transcript-20261031.txt", "start_ts": "2026-10-31 10:00:00", "end_ts": "2026-10-31 10:24:00",
        "target": target, "name": name})
    h.do_POST()
    return h.sent, sorted(n for n in os.listdir(out_dir) if re.fullmatch(r"transcript-\d{12}(@[^.]+)?\.txt", n))


_FILES = {
    "files": ["transcript-20261031.txt", "transcript-202610311500@acme_sync.txt", "transcript-202610300900@acme_sync.txt",
              "transcript-202611010900.txt", "transcript-202610291000@acme_sync.txt", "transcript-202611021000.txt"],
    "active": "transcript-20261031.txt",
    "file_info": {
        "transcript-20261031.txt": {"label": "2026-10-31", "dt": "20261031", "meeting_group": None},
        "transcript-202610311500@acme_sync.txt": {"dt": "202610311500", "meeting_group": "acme_sync",
                                                  "related": ["transcript-202610311500@acme_sync-ja.txt",
                                                              "summary-202610311500@acme_sync.md"]},
        "transcript-202610300900@acme_sync.txt": {"dt": "202610300900", "meeting_group": "acme_sync"},
        "transcript-202611010900.txt": {"dt": "202611010900", "meeting_group": "ad-hoc"},
        "transcript-202610291000@acme_sync.txt": {"dt": "202610291000", "meeting_group": "acme_sync"},
        "transcript-202611021000.txt": {"dt": "202611021000", "meeting_group": "ad-hoc"},
    },
}
_CAL = {"enabled": True, "events": [
    {"summary": "acme sync", "start": "2026-10-31T10:00:00", "end": "2026-10-31T10:30:00", "status": "ended"},
    {"summary": "all day", "start": "2026-10-31", "end": "2026-11-01"}]}
_DATA = {"daily": _DAILY, "files": _FILES, "cal": _CAL,
         "cases": [{"name": n, "lines": ls, "min": m, "rng": r} for n, ls, m, r in _CASES]}

_PRE = "const I18N=" + json.dumps(STRINGS["ja"], ensure_ascii=False) + ";\nconst DATA=" + json.dumps(_DATA, ensure_ascii=False) + ";\n" + r"""
const mkEl=()=>({textContent:'',innerHTML:'',className:'',title:'',style:{},dataset:{},value:'',disabled:false,children:[],
  scrollTop:0,scrollHeight:1000,clientHeight:200,
  classList:{s:new Set(),add(c){this.s.add(c);},remove(c){this.s.delete(c);},
    toggle(c,f){(f===undefined?!this.s.has(c):f)?this.s.add(c):this.s.delete(c);return this.s.has(c);},contains(c){return this.s.has(c);}},
  handlers:{},addEventListener(t,f){this.handlers[t]=f;},setAttribute(){},getAttribute(){return null;},appendChild(c){this.children.push(c);},
  querySelectorAll(){return [];},querySelector(){return null;},closest(){return null;},focus(){},select(){}});
const els={};
const document={getElementById:id=>els[id]||(els[id]=mkEl()),createElement:mkEl,querySelectorAll:()=>[],querySelector:()=>null,
  addEventListener(){},body:mkEl(),documentElement:mkEl()};
const localStorage={getItem(){return null;},setItem(){}};
const location={hash:'',pathname:'/next',search:''};
const history={replaceState(a,b,u){location.hash=u.startsWith('#')?u:'';}};
const window={addEventListener(){}};
const navigator={clipboard:{writeText:async()=>{}}};
const setTimeout=()=>0;
const clearTimeout=()=>{};
const setInterval=()=>0;
const posts=[];
const MOCK={cal:DATA.cal,create:[],resp:{}};
const fetch=async (url,opt)=>{
  const ok=v=>({json:async()=>JSON.parse(JSON.stringify(v))});
  if(opt&&opt.method==='POST'){
    posts.push([url,JSON.parse(opt.body)]);
    MOCK.create.forEach(([n,info])=>{DATA.files.files.push(n);DATA.files.file_info[n]=info;});MOCK.create=[];
    const resp={status:'ok',message:'done',...MOCK.resp};MOCK.resp={};
    return ok(resp);
  }
  if(url==='/api/files')return ok(DATA.files);
  if(url==='/api/gcal-events')return ok(MOCK.cal);
  if(url.startsWith('/api/transcript?'))return ok({lines:DATA.daily});
  if(url.startsWith('/api/translation?'))return ok({lines:[]});
  return ok({status:'ok',labels:{},lines:{}});
};
const tick=()=>new Promise(r=>setImmediate(r));
// 読み直し（nxLoadTranscript）は待たずに走るので、選択を作る前に終わらせる
const settle=async()=>{for(let k=0;k<6;k++)await tick();};
"""

_BODY = r"""
(async()=>{
const out={};
const toasts=[];
nxToast=(m,...acts)=>toasts.push({m,acts});
const lastActs=()=>toasts[toasts.length-1].acts;
const act=(label)=>lastActs().find(a=>a[0]===label);
for(let k=0;k<6;k++)await tick();
const hm=(ls,c)=>[ls[c.from].ts,ls[c.to].ts];
// 1) 試作の今日のメモ、沈黙 10 分
const memo=DATA.daily.map(nxParseLine);
const s10=nxSplitSegments(memo,10);
out.memo10=s10.map(c=>hm(memo,c));
out.memo10rest=memo.length-s10.reduce((n,c)=>n+c.to-c.from+1,0);
// 2) server と同じ入力
out.cases={};
DATA.cases.forEach(cs=>{
  const ls=cs.lines.map(nxParseLine),a=cs.rng?cs.rng[0]:0,b=cs.rng?cs.rng[1]:ls.length-1,sub=ls.slice(a,b+1);
  const sg=nxSplitSegments(sub,cs.min);
  out.cases[cs.name]={segs:sg.map(c=>hm(sub,c)),rest:sub.length-sg.reduce((n,c)=>n+c.to-c.from+1,0)};
});
// 3) モーダル: 選択なしで全体を分ける
out.cur=nxState.cur;
await nxOpenExtract('splitAll');
const body=()=>els.nxExBody.innerHTML;
out.shown=els.nxExModal.classList.contains('show');
out.memo=I18N[nxToday(0)==='20261031'?'nx.today_memo':'nx.day_memo'];
out.allText=body().includes(nxFmt('nx.ex_will',{n:2}))&&body().includes(nxFmt('nx.ex_rest',{n:5,memo:out.memo}));
out.rangeDisabled=/class="radio disabled" data-mode="splitRange"/.test(body())&&/class="radio disabled" data-mode="extractRange"/.test(body());
out.gapDefault=nxEx.gap;
out.okDisabledDefault=els.nxExOk.disabled;
nxExSet({gap:10});
out.ok10=!els.nxExOk.disabled&&els.nxExOk.textContent===I18N['nx.ex_split'];
out.calSeg=body().includes(nxFmt('nx.ex_cal',{name:'acme sync'}));
out.allDayIgnored=!body().includes('all day');
// 実行: split-by-silence に分数だけ。応答の files（2 つ）だけを元に戻す。同じ間にできた別のファイルは戻さない
nxExSet({gap:10});
MOCK.create=[['transcript-202610311000.txt',{dt:'202610311000',meeting_group:'ad-hoc'}],
  ['transcript-202610311340.txt',{dt:'202610311340',meeting_group:'ad-hoc'}],
  ['transcript-202610311600.txt',{dt:'202610311600',meeting_group:'ad-hoc'}]];
MOCK.resp={files:['transcript-202610311000.txt','transcript-202610311340.txt']};
posts.length=0;
await nxDoExtract();
out.splitPost=posts[0];
out.splitToast=toasts[toasts.length-1].m;
out.splitActs=lastActs().map(a=>a[0]);
posts.length=0;
await act(I18N['nx.ex_undo'])[1]();
out.undoPosts=posts.slice();
out.undoToast=toasts[toasts.length-1].m;
// 戻したファイルは一覧から消える
DATA.files.files=DATA.files.files.filter(n=>!['transcript-202610311000.txt','transcript-202610311340.txt','transcript-202610311600.txt'].includes(n));
await nxLoadFiles();await settle();
// 4) 範囲がファイル先頭を含む（0〜27）: 1 区間なので分けられない / そのまま 1 つの会議
nxSel=new Set([0,27]);
await nxOpenExtract('splitRange');
out.headMode=nxEx.mode;
nxExSet({gap:10});
out.headCannot=els.nxExOk.disabled&&body().includes(I18N['nx.ex_cannot_one']);
nxExSet({mode:'extractRange'});
out.headExtractOk=!els.nxExOk.disabled&&els.nxExOk.textContent===I18N['nx.ex_create'];
out.headSummary=body().includes(nxFmt('nx.ex_range',{from:'09:02',to:'10:24',n:28}));
// 付け足し先は前後 1 日だけ（記録中の日次ファイル自身・日次は含めない）
out.targets=nxExTargets().map(f=>f.name);
out.shift=[nxDayShift('20261031',1),nxDayShift('20260301',-1),nxDayShift('20261231',1)];
// 範囲の先頭が予定の時間帯でも、0 行目（09:02）は予定外 → 名前なしのまま
out.headNewType=nxEx.newType;
nxExSet({tgt:'existing',target:'transcript-202610300900@acme_sync.txt'});
MOCK.resp={file:'transcript-202610300900@acme_sync.txt'};
posts.length=0;
await nxDoExtract();
out.appendPost=posts[0];
out.appendActs=lastActs().map(a=>a[0]);
out.appendToast=toasts[toasts.length-1].m;
await settle();
// 5) 範囲がファイル末尾を含む（28〜34）
nxSel=new Set([28,34]);
await nxOpenExtract('splitRange');
out.tailCannot=els.nxExOk.disabled;
nxExSet({mode:'extractRange'});
MOCK.create=[['transcript-202610311217@retro.txt',{dt:'202610311217',meeting_group:'retro'}]];
nxExSet({newType:'newname',name:' retro '});
MOCK.resp={file:'transcript-202610311217@retro.txt'};
posts.length=0;
await nxDoExtract();
out.tailPost=posts[0];
out.tailToast=toasts[toasts.length-1].m;
out.tailActs=lastActs().map(a=>a[0]);
await settle();
posts.length=0;
act(I18N['nx.ex_open'])[1]();
out.opened=nxState.cur;
nxOpenFile('transcript-20261031.txt');for(let k=0;k<4;k++)await tick();
// 6) 予定と同じ時間帯の範囲: 同じ名前のいつもの会議を選ぶ（空白と _ は同じとみなす）
nxSel=new Set([3,27]);
await nxOpenExtract('extractRange');
out.calGroup=[nxEx.newType,nxEx.group];
out.calHint=body().includes(nxFmt('nx.ex_cal_group',{name:'acme sync',span:'10:00〜10:30'}));
nxExSet({newType:'adhoc'});
nxOnExFocus({target:{dataset:{ex:'group'}}});
out.focusGroup=nxEx.newType;
MOCK.resp={file:'transcript-202610311000@acme_sync.txt'};
posts.length=0;
await nxDoExtract();
out.groupPost=posts[0];
await settle();
// 予定が無ければ（連携していない）📅 を出さない
MOCK.cal={enabled:false,events:[]};
nxSel=new Set([3,27]);
await nxOpenExtract('extractRange');
out.noCal=nxEx.newType==='adhoc'&&!body().includes('📅');
// 名前の無い予定は使わない（"undefined" を入れない）
MOCK.cal={enabled:true,events:[{start:'2026-10-31T13:30:00',end:'2026-10-31T14:00:00'}]};
nxSel=new Set([30,34]);
await nxOpenExtract('extractRange');
out.noSummary=nxEx.newType==='adhoc'&&nxEx.name===''&&!body().includes('undefined')&&!body().includes('📅');
// 応答にファイル名が無い（dry-run など）ときは、元に戻す・開くを出さない
nxSel=new Set();
await nxOpenExtract('splitAll');nxExSet({gap:10});
await nxDoExtract();
out.noNames=[toasts[toasts.length-1].m,lastActs().length];
await settle();
// 7) 🗑: 日次ファイルは削除だけ（現行と同じ）。会議ファイルは日次ファイルに戻すが既定、完全に削除も選べる
nxRenderAll();
out.delBtnDaily=els.nxFileDelBtn.style.display;
nxOpenFileDel();
out.fdDaily=[nxFd.mode,els.nxFdBody.innerHTML.includes('data-fd="merge"'),els.nxFdOk.className.includes('danger')];
posts.length=0;
await nxDoFileDel();
out.dailyDelPost=posts[0];
nxOpenFile('transcript-202610311500@acme_sync.txt');for(let k=0;k<4;k++)await tick();
out.delBtnMtg=els.nxFileDelBtn.style.display;
nxOpenFileDel();
out.fdShown=els.nxFdModal.classList.contains('show');
out.fdMode=nxFd.mode;
out.fdOk=els.nxFdOk.textContent;
posts.length=0;
await nxDoFileDel();
out.mergePost=posts[0];
out.afterMerge=nxState.cur;
nxOpenFile('transcript-202610311500@acme_sync.txt');for(let k=0;k<4;k++)await tick();
nxOpenFileDel();
nxFdSet('delete');
out.fdList=['transcript-202610311500@acme_sync-ja.txt','summary-202610311500@acme_sync.md'].every(n=>els.nxFdBody.innerHTML.includes(n));
out.fdDanger=els.nxFdOk.className.includes('danger');
posts.length=0;
await nxDoFileDel();
out.deletePost=posts[0];
console.log(JSON.stringify(out));
})();
"""


def main() -> None:
    # 試作のメモと i18n 全体を埋め込むと引数の長さ上限を超えるので標準入力で渡す
    r = subprocess.run(["node", "-"], input=_PRE + _NEXT_JS_CORE + _NEXT_JS_LIST + _NEXT_JS_TRANSCRIPT + _NEXT_JS_EXTRACT + _BODY,
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0 or not r.stdout.strip():
        check("node で実行できる", False, r.stderr[-1500:])
        sys.exit(1)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    ja = STRINGS["ja"]
    d = "2026-10-31 "
    daily = "transcript-20261031.txt"
    check("試作の今日のメモを沈黙 10 分で 2 区間（10:00–10:24、13:40–13:44）、残る行 5",
          out["memo10"] == [[d + "10:00:00", d + "10:24:00"], [d + "13:40:00", d + "13:44:00"]] and out["memo10rest"] == 5,
          repr((out["memo10"], out["memo10rest"])))
    for name, lines, minutes, rng in _CASES:
        srv, js = _server_split(lines, minutes, rng), out["cases"][name]
        same = (len(js["segs"]) < 2 if srv["segs"] is None
                else js["segs"] == srv["segs"] and js["rest"] == srv["rest"])
        check(f"server の split-by-silence と同じ区間: {name}", same, repr((srv, js)))
    sent, names = _server_extract("new", "acme sync")
    check("extract-meeting の応答 file は作った会議ファイル名", sent.get("file") == "transcript-202610311000@acme_sync.txt"
          and names == [sent.get("file")], repr((sent, names)))
    sent, names = _server_extract("transcript-202610310900@acme_sync.txt", "")
    check("付け足しの応答 file は付け足し先", sent.get("file") == "transcript-202610310900@acme_sync.txt"
          and names == [sent.get("file")], repr((sent, names)))
    check("選択なし: 全体を分けるだけ選べる（範囲の 2 つは押せない）",
          out["shown"] and out["cur"] == daily and out["rangeDisabled"], repr(out["rangeDisabled"]))
    check("沈黙の既定は現行 extract モーダルと同じ 1 分", out["gapDefault"] == 1, repr(out["gapDefault"]))
    check("2 区間・残る 5 行を予定に出し、分けるを押せる", out["allText"] and out["ok10"], repr((out["allText"], out["ok10"])))
    check("📅 同じ時間帯の予定を区間に出す（終日の予定は使わない）", out["calSeg"] and out["allDayIgnored"])
    check("分けるは現行と同じ本文", out["splitPost"] == [
        "/api/transcript/split-by-silence", {"file": daily, "min_silence_minutes": 10}], repr(out["splitPost"]))
    check("分けたあとのトーストに 元に戻す・開く",
          out["splitToast"] == ja["nx.ex_done_split"].replace("{n}", "2")
          and out["splitActs"] == [ja["nx.ex_undo"], ja["nx.ex_open"]], repr((out["splitToast"], out["splitActs"])))
    check("元に戻すは作ったファイルごとに merge-to-daily", out["undoPosts"] == [
        ["/api/transcript/merge-to-daily", {"file": "transcript-202610311000.txt"}],
        ["/api/transcript/merge-to-daily", {"file": "transcript-202610311340.txt"}]]
          and out["undoToast"] == ja["nx.ex_undone"].replace("{memo}", out["memo"]), repr(out["undoPosts"]))
    check("範囲がファイル先頭を含む: 1 区間なので分けられない、そのまま 1 つの会議にはできる",
          out["headMode"] == "splitRange" and out["headCannot"] and out["headExtractOk"] and out["headSummary"],
          repr((out["headMode"], out["headCannot"], out["headExtractOk"], out["headSummary"])))
    check("付け足し先は開いているファイルの日付の前後 1 日の会議ファイルだけ", out["targets"] == [
        "transcript-202611010900.txt", "transcript-202610311500@acme_sync.txt", "transcript-202610300900@acme_sync.txt"],
          repr(out["targets"]))
    check("日付の前後 1 日は月・年をまたいでも合う", out["shift"] == ["20261101", "20260228", "20270101"], repr(out["shift"]))
    check("予定の時間帯でなければ名前なしが既定", out["headNewType"] == "adhoc", repr(out["headNewType"]))
    check("付け足しは target にファイル名、トーストは 開く だけ", out["appendPost"] == [
        "/api/transcript/extract-meeting", {"file": daily, "start_ts": d + "09:02:00", "end_ts": d + "10:24:00",
                                            "target": "transcript-202610300900@acme_sync.txt", "name": ""}]
          and out["appendActs"] == [ja["nx.ex_open"]]
          and out["appendToast"] == ja["nx.ex_done_append"].replace("{name}", "acme_sync"),
          repr((out["appendPost"], out["appendActs"], out["appendToast"])))
    check("範囲がファイル末尾を含む: 分けられない", out["tailCannot"])
    check("新しい会議名で切り出す（末尾まで）", out["tailPost"] == [
        "/api/transcript/extract-meeting", {"file": daily, "start_ts": d + "12:17:00", "end_ts": d + "13:44:00",
                                            "target": "new", "name": "retro"}]
          and out["tailToast"] == ja["nx.ex_done_new"].replace("{name}", "retro")
          and out["tailActs"] == [ja["nx.ex_undo"], ja["nx.ex_open"]], repr((out["tailPost"], out["tailToast"])))
    check("開く で作った会議ファイルを開く", out["opened"] == "transcript-202610311217@retro.txt", repr(out["opened"]))
    check("予定と同じ時間帯なら、同じ名前のいつもの会議を選んで知らせる",
          out["calGroup"] == ["group", "acme_sync"] and out["calHint"], repr((out["calGroup"], out["calHint"])))
    check("いつもの会議の 1 回として: name にその会議名", out["groupPost"] == [
        "/api/transcript/extract-meeting", {"file": daily, "start_ts": d + "10:00:00", "end_ts": d + "10:24:00",
                                            "target": "new", "name": "acme_sync"}], repr(out["groupPost"]))
    check("予定の連携が無ければ 📅 を出さない", out["noCal"])
    check("🗑 は日次ファイルにも会議ファイルにも出す（くわしく表示）", out["delBtnDaily"] == "" and out["delBtnMtg"] == "",
          repr((out["delBtnDaily"], out["delBtnMtg"])))
    check("日次ファイルの 🗑 は現行と同じく削除だけ", out["fdDaily"] == ["delete", False, True]
          and out["dailyDelPost"] == ["/api/transcript/delete-file", {"file": daily}], repr((out["fdDaily"], out["dailyDelPost"])))
    check("会議名の一覧にフォーカスすると「いつもの会議の1回として」を選ぶ", out["focusGroup"] == "group", repr(out["focusGroup"]))
    check("名前の無い予定は使わない", out["noSummary"])
    check("応答にファイル名が無ければ 元に戻す・開く を出さない", out["noNames"] == ["done", 0], repr(out["noNames"]))
    check("🗑 は「日次ファイルに戻す」が既定", out["fdShown"] and out["fdMode"] == "merge" and out["fdOk"] == ja["nx.fd_merge_ok"],
          repr((out["fdMode"], out["fdOk"])))
    check("日次ファイルに戻すは merge-to-daily、そのあと日次ファイルを開く", out["mergePost"] == [
        "/api/transcript/merge-to-daily", {"file": "transcript-202610311500@acme_sync.txt"}] and out["afterMerge"] == daily,
          repr((out["mergePost"], out["afterMerge"])))
    check("完全に削除は消えるファイル（翻訳・議事録）を並べて delete-file", out["fdList"] and out["fdDanger"]
          and out["deletePost"] == ["/api/transcript/delete-file", {"file": "transcript-202610311500@acme_sync.txt"}],
          repr(out["deletePost"]))
    used = set(re.findall(r"'(nx\.[a-z0-9_]+)'", _NEXT_JS_EXTRACT))
    check("切り出しの文言は日英の i18n にある", bool(used) and all(used <= set(STRINGS[k]) for k in ("ja", "en")),
          repr(sorted(used - set(STRINGS["en"]))))
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
