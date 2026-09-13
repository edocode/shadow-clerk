"""AI Console の末尾空行畳み (_trimConsoleTail) の検証

実行: uv run python tests/test_console_trim.py
daemon は不要。ダッシュボードの JS から関数の実体を切り出し、node の上で
最小の DOM 相当を用意して動かす。node が無い環境では skip する。

このロジックは「入力行の下に空行が積み上がる」不具合で二度直しているので、
JS のまま回帰を押さえる。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_js_console import _JS_TEMPLATE_CONSOLE

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    raise SystemExit(0)


def extract_const(name: str) -> str:
    """トップレベルの const 宣言を切り出す"""
    head = f"const {name}="
    i = _JS_TEMPLATE_CONSOLE.index(head)
    j = _JS_TEMPLATE_CONSOLE.index(";\n", i)
    return _JS_TEMPLATE_CONSOLE[i:j + 2]


def extract(name: str) -> str:
    """トップレベル関数の宣言を JS テンプレートから切り出す"""
    head = f"function {name}("
    i = _JS_TEMPLATE_CONSOLE.index(head)
    j = _JS_TEMPLATE_CONSOLE.index("\n}\n", i)
    return _JS_TEMPLATE_CONSOLE[i:j + 3]


HARNESS = """
let _consoleRows={}, _consoleMaxRow=-1, _consoleKeep=-1, _consoleTrimmed=-1;
const CONSOLE_CURSOR_NEAR=100;
__EXTRA__
function addRow(y, html){
  for(let i=_consoleMaxRow+1;i<=y;i++)
    if(!_consoleRows[i])_consoleRows[i]={innerHTML:'',style:{display:''}};
  _consoleMaxRow=Math.max(_consoleMaxRow,y);
  _consoleRows[y].innerHTML=html;
}
function visibleRows(){
  const v=[];
  for(let y=0;y<=_consoleMaxRow;y++)
    if(_consoleRows[y]&&_consoleRows[y].style.display!=='none')v.push(y);
  return v;
}
__TRIM__
const out=[];
__SCENARIO__
console.log(JSON.stringify(out));
"""

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def run(scenario: str, extra: str = "") -> list:
    js = (HARNESS.replace("__TRIM__", extract("_trimConsoleTail"))
          .replace("__EXTRA__", extra).replace("__SCENARIO__", scenario))
    p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        print(p.stderr, file=sys.stderr)
        raise SystemExit(1)
    return json.loads(p.stdout)


# --- 基本 ---

out = run("""
addRow(0,'a');addRow(1,'b');addRow(2,'');addRow(3,'');
_trimConsoleTail(1);
out.push(visibleRows());
""")
check("1. 末尾の空行を畳む", out[0] == [0, 1], str(out[0]))

out = run("""
addRow(0,'a');addRow(1,'');addRow(2,'');
_trimConsoleTail(2);
out.push(visibleRows());
""")
check("2. カーソル行は空でも残す", out[0] == [0, 1, 2], str(out[0]))

out = run("""
addRow(0,'a');addRow(1,'b');addRow(2,'');
_trimConsoleTail(1);
addRow(2,'c');
_trimConsoleTail(1);
out.push(visibleRows());
""")
check("3. 書き戻された行は表示に戻る", out[0] == [0, 1, 2], str(out[0]))

# --- 回帰: keep が変わらないまま行だけ増えるケース ---

out = run("""
addRow(0,'a');addRow(1,'b');
_trimConsoleTail(1);
// TUI が深い行を消去すると、その行も dirty として届いて div が作られる
for(let y=2;y<=70;y++)addRow(y,'');
_trimConsoleTail(1);
out.push(visibleRows());
""")
check("4. keep 据え置きで行が増えても畳む", out[0] == [0, 1], str(out[0]))

out = run("""
addRow(0,'a');addRow(1,'b');
_trimConsoleTail(1);
for(let y=2;y<=20;y++)addRow(y,'');
_trimConsoleTail(1);
for(let y=21;y<=40;y++)addRow(y,'');
_trimConsoleTail(1);
out.push(visibleRows());
""")
check("5. 繰り返し増えても積み上がらない", out[0] == [0, 1], str(out[0]))

# --- 余計に触らない ---

out = run("""
addRow(0,'a');addRow(1,'b');addRow(2,'');
_trimConsoleTail(1);
_consoleRows[0].style.display='none';   // 外から触られた印
_trimConsoleTail(1);                     // 何も変わっていないので触らないはず
out.push(_consoleRows[0].style.display);
""")
check("6. 変化が無ければ何もしない", out[0] == "none", str(out[0]))

out = run("""
for(let y=0;y<=5;y++)addRow(y,'x');
_trimConsoleTail(5);
out.push(visibleRows());
""")
check("7. 全行に中身があれば全部残す", out[0] == [0, 1, 2, 3, 4, 5], str(out[0]))

# --- カーソルが本文から離れているとき ---

out = run("""
addRow(0,'a');addRow(1,'b');
for(let y=2;y<=500;y++)addRow(y,'');
_trimConsoleTail(500);
out.push(visibleRows());
""")
check("8. 遠いカーソルまで表示を伸ばさない", out[0] == [0, 1], str(out[0])[:60])

out = run("""
addRow(0,'a');addRow(1,'b');
for(let y=2;y<=50;y++)addRow(y,'');
_trimConsoleTail(50);
out.push(visibleRows().length);
""")
check("9. 近いカーソルまでは伸ばす", out[0] == 51, str(out[0]))

out = run("""
addRow(0,'a');
for(let y=1;y<=101;y++)addRow(y,'');
_trimConsoleTail(101);          // last=0 なので境界のすぐ外
out.push(visibleRows());
""")
check("10. 境界のすぐ外は伸ばさない", out[0] == [0], str(out[0])[:60])

out = run("""
addRow(0,'a');
for(let y=1;y<=100;y++)addRow(y,'');
_trimConsoleTail(100);          // last=0 + 100 = 境界ちょうど
out.push(visibleRows().length);
""")
check("11. 境界ちょうどは伸ばす", out[0] == 101, str(out[0]))

out = run("""
_trimConsoleTail(0);            // 行がまだ無い
out.push(visibleRows());
""")
check("12. 行が無くても壊れない", out[0] == [], str(out[0]))

# --- full 更新で入力欄を消さない ---
# #consoleInput は #consolec の子なので、innerHTML='' で消えると
# 以後キー入力が一切通らなくなる

FULL_ENV = """
const removed=[];
function mkEl(cls){
  return {className:cls,style:{display:''},innerHTML:'',
          remove(){removed.push(cls);cc.children=cc.children.filter(e=>e!==this);}};
}
const cc={children:[],
  set innerHTML(v){if(v===''){for(const e of cc.children)removed.push(e.className);
                              cc.children=[];}},
  get innerHTML(){return '';},
  querySelectorAll(sel){const c=sel.replace('.','');
    return cc.children.filter(e=>e.className===c);},
  appendChild(e){cc.children.push(e);return e;}};
cc.appendChild(mkEl('consoleInput'));
cc.appendChild(mkEl('cr'));cc.appendChild(mkEl('cr'));
"""

out = run("""
cc.querySelectorAll('.cr').forEach(el=>el.remove());
out.push(cc.children.map(e=>e.className));
""", extra=FULL_ENV)
check("13. full 更新で .cr だけ消える", out[0] == ["consoleInput"], str(out[0]))

# 実装が本当にその形で書かれているか（innerHTML='' に戻っていないか）
from shadow_clerk._daemon_dashboard_js_console import _JS_TEMPLATE_CONSOLE as _T
_full = _T[_T.index("if(d.full){"):_T.index("const rows=d.rows")]
check("14. applyConsole の full 分岐が innerHTML='' を使っていない",
      "cc.innerHTML=''" not in _full and "querySelectorAll('.cr')" in _full)

# --- フォーカスの取り方 ---
# mousedown で focus しても、そのあとに走るブラウザの既定動作が
# フォーカスを body へ移してしまい、キーが textarea に届かない
_init = _T[_T.index("(function initConsole()"):_T.index("})();")]
check("15. #consolec のフォーカスは click で取る",
      "c.addEventListener('click'" in _init
      and "c.addEventListener('mousedown'" not in _init)

# --- 色 ---
# pyte は 30-37 を brown/white 等、90-97 を bright* と呼ぶ。名前が合わないと
# クラスが付かず画面がほぼ白黒になる

SPAN_ENV = ("function esc(t){return String(t).replace(/&/g,'&amp;')"
            ".replace(/</g,'&lt;').replace(/>/g,'&gt;');}\n"
            + extract_const("_CONSOLE_COLOR_NAMES")
            + extract_const("_CONSOLE_HEX")
            + extract("_consoleSpan"))

out = run("out.push(_consoleSpan('x','fg:brightred'));", extra=SPAN_ENV)
check("16. bright 系の色にクラスが付く", out[0] == '<span class="cfg-brightred">x</span>', out[0])

out = run("out.push(_consoleSpan('x','fg:brown,bg:brightblack,bold'));", extra=SPAN_ENV)
check("17. brown と bg と装飾が同時に付く",
      out[0] == '<span class="cfg-brown cbg-brightblack cs-bold">x</span>', out[0])

out = run("out.push(_consoleSpan('x','fg:ff8800'));", extra=SPAN_ENV)
check("18. 256色/24bit の16進はインラインで当てる",
      out[0] == '<span style="color:#ff8800;">x</span>', out[0])

out = run("out.push(_consoleSpan('x','fg:javascript:alert(1)'));", extra=SPAN_ENV)
check("19. 16進でも既知の名前でもない値は捨てる", out[0] == "x", out[0])

out = run("out.push(_consoleSpan('<b>&','fg:red'));", extra=SPAN_ENV)
check("20. 本文はエスケープする",
      out[0] == '<span class="cfg-red">&lt;b&gt;&amp;</span>', out[0])

# CSS 側にクラスが揃っているか
from shadow_clerk._daemon_dashboard_css import _CSS_TEMPLATE as _CSS
import re as _re
_names = _re.search(r"const _CONSOLE_COLOR_NAMES=\[(.*?)\];", _T, _re.S).group(1)
_names = _re.findall(r"'([a-z]+)'", _names)
_missing = [n for n in _names
            if f".cfg-{n}{{" not in _CSS or f".cbg-{n}{{" not in _CSS]
check("21. 全ての色名に CSS クラスがある", not _missing, str(_missing))

check("22. コンソールのフォントは CJK 幅を揃えた変数を使う",
      "--console-font" in _CSS and "size-adjust" in _CSS
      and "'SF Mono','Monaco','Menlo','Consolas',monospace;\n  font-size:12px" not in _CSS)

check("23. 幅の変化は ResizeObserver で拾う",
      "new ResizeObserver" in _init and "scheduleConsoleCols" in _init, "")
check("24. 高さだけの変化では列数を測り直さない",
      "w===_lastW" in _init or "w === _lastW" in _init, "")

# --- 子の起こし直しと既定タブ ---
_status = _T[_T.index("function updateConsoleStatus("):_T.index("async function loadConsole")]
check("25. 走っていると分かった時点で列数を送り直す",
      "_lastCols=0" in _status and "reportConsoleCols()" in _status
      and "_consoleRunning!==true" in _status, "")

check("26. auto_analyze のときだけ既定タブを AI コンソールにする",
      "cfg.auto_analyze" in _init and "switchLogTab('console'" in _init
      and "switchLogTab('logs',{expand:false})" in _init, "")

from shadow_clerk._daemon_dashboard_js_core import _JS_TEMPLATE_CORE as _TC
_tog = _TC[_TC.index("function togLogs()"):]
_tog = _tog[:_tog.index("\n}\n")]
check("27. 折りたたみを開いたら列数を測り直す",
      "scheduleConsoleCols()" in _tog and "logTab==='console'" in _tog, "")

# --- 分析ボタンのトグルと自動起動 ---
from shadow_clerk._daemon_dashboard_js_panels import _JS_TEMPLATE_PANELS as _TP
from shadow_clerk._daemon_dashboard_html import _HTML_TEMPLATE as _H

check("28. 分析ボタンは1つのトグル",
      "toggleAnalysis()" in _H and "startAnalysis()" not in _H
      and "async function toggleAnalysis()" in _TP, "")

_tog = _TP[_TP.index("async function toggleAnalysis()"):]
_tog = _tog[:_tog.index("\nasync function")]
check("29. 走っているときは停止に回す",
      "_consoleRunning" in _tog and "stopConsole()" in _tog, "")

_upd = _T[_T.index("function updateConsoleStatus("):_T.index("/* 自動で分析")]
check("30. ラベルを開始/停止で入れ替える",
      "dash.stop_analysis" in _upd and "dash.start_analysis" in _upd, "")

check("31. 自動起動なら生成物とコンソールを開く",
      "if(d.auto)showAutoAnalysis()" in _T
      and "togSumPane()" in _T and "switchSumTab('ai')" in _T
      and "switchLogTab('console')" in _T, "")

from shadow_clerk._i18n_ja import STRINGS_JA as _JA
from shadow_clerk._i18n_en import STRINGS_EN as _EN
for k in ("dash.stop_analysis", "dash.stop_analysis_title"):
    check(f"32. i18n に {k} がある", k in _JA and k in _EN, "")

# --- 開いたときのスクロール位置 ---
# 畳んでいる間は clientHeight も scrollHeight も 0 で scrollTop に書いても
# 効かないため、タブ切替と展開の両方で最下部に送る必要がある
check("33. タブを開いたら最下部に送る",
      "scrollConsoleBottom()" in _T[_T.index("function switchLogTab("):_T.index("/* サーバが送ってくる色名")], "")
_togLogs = _TC[_TC.index("function togLogs()"):]
_togLogs = _togLogs[:_togLogs.index("\n}\n")]
check("34. 畳みを開いたときも最下部に送る", "scrollConsoleBottom()" in _togLogs, "")
check("35. 非表示のときは触らない",
      "if(c&&c.clientHeight)c.scrollTop=c.scrollHeight" in _T, "")

# --- 提案/分析の上下分割 ---
# 位置は比率で持つ。px で覚えると、容器が狭まったとき上のペインだけが元の
# 大きさを保ち、下の分析ペインが最小まで潰れる

SPLIT_ENV = """
let _adviceRatio=0, _adviceRatioW=0, availH=745, availW=400, topH=0, topW=0,
    topStyleH='', topStyleW='', rowCls=false;
const els={
  advWrap:{style:{get height(){return topStyleH;},set height(v){topStyleH=v;},
                  get width(){return topStyleW;},set width(v){topStyleW=v;}},
           getBoundingClientRect(){return {height:topH,width:topW};}},
  aiWrap:{classList:{contains(){return rowCls;},toggle(c,v){rowCls=v;}},
          getBoundingClientRect(){return {height:availH,width:availW};}},
};
const document={getElementById(id){return els[id]||null;}};
"""
# 軸の判定は 3 つの小関数に分かれているので、切り出しでも一括で連れて行く
SPLIT_FNS = (extract("_sumRow") + extract("_sumProp") + extract("_sumRatio")
             + extract("clampSumSplit"))

out = run("""
_adviceRatio=0.5; els.advWrap.style.height='100px';
clampSumSplit();
out.push(topStyleH);
availH=2000; clampSumSplit();
out.push(topStyleH);
""", extra=SPLIT_ENV + extract_const("SUM_SPLIT_MIN") + SPLIT_FNS)
check("36. 比率どおりの大きさにする", out[0] == "373px", out[0])
check("37. 容器が変わっても同じ割合を保つ", out[1] == "1000px", out[1])

out = run("""
_adviceRatio=0.01; els.advWrap.style.height='10px';
clampSumSplit();
out.push(topStyleH);
availH=50; els.advWrap.style.height='40px'; clampSumSplit();
out.push(topStyleH);
""", extra=SPLIT_ENV + extract_const("SUM_SPLIT_MIN") + SPLIT_FNS)
check("38. 小さすぎる値は最低値まで戻す", out[0] == "60px", out[0])
check("39. 容器が測れないときは触らない", out[1] == "40px", out[1])

check("41. AI分析タブに切り替えたら分割を挟み直す",
      "updateSumSplit()" in _TC[_TC.index("function switchSumTab("):_TC.index("function switchLeftTab(")], "")
check("40. 畳みを開いたら分割を挟み直す", "updateSumSplit()" in _TC[_TC.index("function togSumPane()"):_TC.index("function openSumPane()")], "")

# --- 幅で上下/左右を切り替える ---
# 縦に積んだままだと広い画面で 1 ペインが数行、横に割ったままだと狭い画面で
# 1 ペインが数十文字になる。どちらも読めない

ORIENT = (SPLIT_ENV + extract_const("SUM_SPLIT_MIN") + extract_const("SUM_ROW_ON")
          + extract("_sumRow") + extract("_sumProp") + extract("_sumRatio")
          + extract("applySumOrientation"))

out = run("""
_adviceRatioW=0.4; topStyleH='400px'; availW=800;
applySumOrientation();
out.push([rowCls,topStyleH,topStyleW]);
""", extra=ORIENT)
check("48. 広ければ左右に並べる", out[0][0] is True, str(out[0]))
check("49. 使わない軸のインラインを消す", out[0][1] == "", str(out[0]))
check("50. 大きさは決めない（clampSumSplit が比率から引き直す）",
      out[0][2] == "", str(out[0]))

out = run("""
rowCls=true; _adviceRatio=0.5; topStyleW='300px';
availW=620; applySumOrientation(); out.push([rowCls,topStyleW]);
availW=590; applySumOrientation(); out.push([rowCls,topStyleH,topStyleW]);
""", extra=ORIENT)
check("51. 戻す幅は入る幅より狭くしてばたつきを防ぐ",
      out[0][0] is True and out[0][1] == "300px", str(out[0]))
check("52. 十分狭くなったら縦に戻し、両軸のインラインを落とす",
      out[1][0] is False and out[1][1] == "" and out[1][2] == "", str(out[1]))

out = run("""
availW=0; applySumOrientation(); out.push(rowCls);
""", extra=ORIENT)
check("53. 測れないとき(非表示)は触らない", out[0] is False, str(out[0]))

out = run("""
rowCls=true; _adviceRatioW=0.95; topStyleW='923px'; availW=745;
clampSumSplit();
out.push(topStyleW);
""", extra=SPLIT_ENV + extract_const("SUM_SPLIT_MIN") + SPLIT_FNS)
check("54. 横並びでも最低幅は両側に残す", out[0] == "675px", out[0])

check("61. 左右のときは仕切りも横向きになる",
      "#aiWrap.row { flex-direction:row; }" in _CSS and "ew-resize" in _CSS, "")

# --- 打鍵の順序 ---
# 1打ごとに fetch を投げっぱなしにすると、同時に飛んだ POST がサーバ側で
# 別スレッドに載って追い越す。実測で "hello123" が "holle123" になった


def run_async(scenario: str, extra: str = "") -> list:
    """非同期の筋書き用。node -e はトップレベル await を許さないので包む"""
    js = (extra + "\nconst out=[];\n(async()=>{\n" + scenario
          + "\nconsole.log(JSON.stringify(out));\n})();\n")
    p = subprocess.run(["node", "-e", js], capture_output=True, text=True, timeout=30)
    if p.returncode != 0:
        print(p.stderr, file=sys.stderr)
        raise SystemExit(1)
    return json.loads(p.stdout)


# extract() は "async function" の async を落とすので足し直す
SEND_FNS = extract("sendConsole") + "async " + extract("_postConsole")
SEND_ENV = """
let log=[], _consoleSendQ=Promise.resolve();
// 2文字目だけ極端に遅い応答にして、追い越しが起きれば必ず露見するようにする
function fetch(url,opt){
  const d=JSON.parse(opt.body).data;
  return new Promise(res=>setTimeout(()=>{log.push(d);res({});}, d==='e'?30:1));
}
"""

out = run_async("""
for(const ch of 'hello')sendConsole(ch);
await new Promise(r=>setTimeout(r,300));
out.push(log.join(''));
""", extra=SEND_ENV + SEND_FNS)
check("71. 打った順にサーバへ届く", out[0] == "hello", out[0])

out = run_async("""
// 途中で失敗しても列は止めない
fetch=(u,o)=>{const d=JSON.parse(o.body).data;
  if(d==='l')return Promise.reject(new Error('boom'));
  log.push(d);return Promise.resolve({});};
for(const ch of 'hello')sendConsole(ch);
await new Promise(r=>setTimeout(r,200));
out.push(log.join(''));
""", extra=SEND_ENV + SEND_FNS)
check("72. 1つ失敗しても後続を送り続ける", out[0] == "heo", out[0])

# --- IME の変換中表示 ---
# textarea は opacity:0 で重ねてあるので、何もしないと確定するまで一文字も
# 見えない。「日本語入力時、確定まで文字が見えない」と報告された

out = run("""
out.push([_consoleCells('a'), _consoleCells('あ'), _consoleCells('あa'),
          _consoleCells('（）'), _consoleCells('')]);
""", extra=extract("_consoleCells"))
check("73. CJK は 2 セルで数える", out[0] == [1, 2, 3, 4, 0], str(out[0]))

_comp = _T[_T.index("function onConsoleComposing("):_T.index("/* IME で確定した")]
check("74. 変換中は見える状態にする", "classList.add('composing')" in _comp, "")
check("75. 箱の幅を変換中の文字に合わせる",
      "_consoleCells(e.data" in _comp and "'ch'" in _comp, "")
_end = _T[_T.index("function onConsoleComposition("):_T.index("/* 端末の入力は textarea")]
check("76. 確定したら元に戻す",
      "classList.remove('composing')" in _end and "style.width=''" in _end, "")
check("77. start と update の両方で拾う",
      "'compositionstart',onConsoleComposing" in _T
      and "'compositionupdate',onConsoleComposing" in _T, "")
_ci = _CSS[_CSS.index("#consoleInput.composing {"):] if "#consoleInput.composing {" in _CSS else ""
check("78. CSS が変換中だけ不透明にする",
      "opacity:1" in _ci[:_ci.index("}") + 1] if _ci else False, "")

# --- 文字サイズ (小|中|大) ---
# 変えるのは読む面だけ。ヘッダまで大きくすると折り返して行が増える

check("62. 中は今までの 12px", "['dash.font_m','12px']" in _TC, "")
check("63. 変えるのは --fs だけ",
      "setProperty('--fs',px)" in _TC and _TC.count("setProperty('--fs'") == 1, "")
_fnt = _TC[_TC.index("function applyFontSize("):_TC.index("/* --- Panel cycling")]
check("64. 1文字の幅が変わるので列を測り直す", "scheduleConsoleCols()" in _fnt, "")
check("65. 選択を localStorage に残す", "localStorage.setItem('fontStep'" in _fnt
      or "localStorage.setItem('fontStep'" in _TC, "")
check("66. 起動時に前回の選択を読む", "localStorage.getItem('fontStep')" in _TC, "")
check("67. 適用は console の初期化から呼ぶ",
      "applyFontSize();" in _T[_T.index("function initConsole()"):], "")
# 読む面が --fs を見ていないと、ボタンだけ切り替わって何も変わらない
def _block(sel: str) -> str:
    # 行頭のものを取る。" #consolec {" のような別ルールの一部に当てないため
    i = _CSS.index("\n" + sel + " {") + 1
    return _CSS[i:_CSS.index("}", i)]


for sel in ("#logc", "#consolec", ".interim"):
    check(f"68. {sel} が --fs に追従する", "var(--fs)" in _block(sel), "")
check("69. .pc が --fs に追従する", "font-size: var(--fs)" in _block(".pc"), "")
# .md-body は .pc の中。px を残すと本文だけ大きくなって見出しが置いていかれる
check("70. md-body の見出しは相対指定",
      "font-size:1.25em" in _CSS and "font-size:15px" not in _CSS, "")

# --- T|R|AI ---
# AI は T/R を伏せて AI 分析だけを出す。最後の状態を localStorage に残す

_cyc = _TC[_TC.index("function applyPanelMode("):_TC.index("/* --- Logs toggle")]
check("55. AI を含む 4 状態を回す", "const PANEL_MODES=['T|R','T','R','AI']" in _TC, "")
# AI では T/R を伏せるのではなく、コンソール右の側ペインへ移す。中央に残すと
# 二重に見え、複製すると loadT/loadR の書き込み先が分かれる
check("56. AI では T/R を側ペインへ移し、抜けたら戻す",
      "adoptPanelsIntoSide()" in _cyc and "releasePanelsFromSide()" in _cyc, "")
check("56b. AI 以外では選ばれた側だけを隠す",
      "t.classList.toggle('hidden',panelMode===2)" in _cyc
      and "r.classList.toggle('hidden',panelMode===1)" in _cyc, "")
check("56c. AI では下部ペインを開いてコンソールを出す",
      "switchLogTab('console')" in _cyc, "")
check("57. AI では S ペインを開いて AI タブにする",
      "openSumPane()" in _cyc and "switchSumTab('ai')" in _cyc, "")
check("57b. AI では畳む取っ手を伏せる",
      "sumChevron" in _cyc and "ai?'none':''" in _cyc, "")
check("58. 切り替えを localStorage に残す", "localStorage.setItem('panelMode'" in _cyc, "")
check("59. 起動時に前回の状態を読む", "localStorage.getItem('panelMode')" in _TC, "")

# --- コンソール右の文字起こしペイン ---
# 中身は中央のパネルを移して使うので、AI 以外では空の枠を出さない
check("59b. AI モード以外では枠も仕切りも出さない",
      "#consoleRow:not(.ai-mode) #consoleSide" in _CSS
      and "#consoleRow:not(.ai-mode) #consoleSplit" in _CSS, "")
# **!important が要る**: ドラッグが style.width をインラインで書くため、素の
# width:0 では負けて「中身は消えるのに枠の幅だけ残る」状態になる
check("59c. 畳みはドラッグした幅に勝つ",
      "#consoleRow.side-collapsed #consoleSide { width:0 !important; }" in _CSS, "")
check("59d. 開閉と幅を localStorage に残す",
      "localStorage.setItem('consoleSideCollapsed'" in _T
      and "localStorage.setItem('consoleSideWidth'" in _T, "")
# 列数は #consolec の幅から出して PTY に送る。幅を変えたら教えないと折り返しがずれる
check("59e. 幅が変わったら列数を送り直す",
      "reportConsoleCols()" in _T[_T.index("function togConsoleSide("):
                                  _T.index("function initConsoleSide(")], "")
# **panels の初期化では早すぎる**: SUM_SPLIT_MIN は console 側の const で、
# 先に applyPanelMode を呼ぶと TDZ で初期化ごと止まる
check("60. 適用は console の初期化から呼ぶ",
      "applyPanelMode();" in _T[_T.index("function initConsole()"):], "")

# --- 幅の揺れとキー入力 ---

check("42. スクロールバーの出入りで幅が動かないようにする",
      "scrollbar-gutter:stable" in _CSS, "")

KEY_ENV = ("let sent=[];function sendConsole(d){sent.push(d);}\n"
           + extract_const("_CONSOLE_KEYS"))
_key = extract("onConsoleKey")

def key(ev: str) -> list:
    return run(f"onConsoleKey({ev});out.push(sent);", extra=KEY_ENV + _key)

E = "preventDefault(){},"
out = key("{key:'Enter',altKey:true," + E + "}")
check("43. Alt+Enter は ESC+CR を送る（改行）", out[0] == ["\x1b\r"], repr(out[0]))

out = key("{key:'Enter'," + E + "}")
check("44. ただの Enter は送信のまま", out[0] == ["\r"], repr(out[0]))

out = key("{key:'b',altKey:true," + E + "}")
check("45. Alt+文字も ESC 前置で送る", out[0] == ["\x1bb"], repr(out[0]))

# AltGr は DOM 上 altKey+ctrlKey として届く。ESC 前置で送ってはいけない
# (Ctrl 側の既存分岐に落ちる。AltGr 配列で文字が打てないのは元からの制約)
out = key("{key:'@',altKey:true,ctrlKey:true," + E + "}")
check("46. AltGr(Alt+Ctrl) を ESC 前置で送らない",
      all(not d.startswith("\x1b") for d in out[0]), repr(out[0]))

out = key("{key:'Alt',altKey:true," + E + "}")
check("47. Alt 単独では何も送らない", out[0] == [], repr(out[0]))

print(f"\n{sum(results)}/{len(results)} passed")
raise SystemExit(0 if all(results) else 1)
