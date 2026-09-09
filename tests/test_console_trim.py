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
# 保存した高さが容器を超えると、下の分析ペインが 0 近くまで潰れる

SPLIT_ENV = """
let _adviceWant=0, availH=745, topH=0, topStyleH='';
const els={
  advWrap:{style:{get height(){return topStyleH;},set height(v){topStyleH=v;}},
           getBoundingClientRect(){return {height:topH};}},
  aiWrap:{getBoundingClientRect(){return {height:availH};}},
};
const document={getElementById(id){return els[id]||null;}};
"""

out = run("""
_adviceWant=923; els.advWrap.style.height='923px';
clampSumSplit();
out.push(topStyleH);
availH=2000; clampSumSplit();
out.push(topStyleH);
""", extra=SPLIT_ENV + extract_const("SUM_SPLIT_MIN") + extract("clampSumSplit"))
check("36. 容器を超える保存値は挟み込む", out[0] == "675px", out[0])
check("37. 容器が広がれば元の高さに戻る", out[1] == "923px", out[1])

out = run("""
_adviceWant=10; els.advWrap.style.height='10px';
clampSumSplit();
out.push(topStyleH);
availH=50; els.advWrap.style.height='40px'; clampSumSplit();
out.push(topStyleH);
""", extra=SPLIT_ENV + extract_const("SUM_SPLIT_MIN") + extract("clampSumSplit"))
check("38. 小さすぎる値は最低値まで戻す", out[0] == "60px", out[0])
check("39. 容器が測れないときは触らない", out[1] == "40px", out[1])

check("41. AI分析タブに切り替えたら分割を挟み直す",
      "clampSumSplit()" in _TC[_TC.index("function switchSumTab("):_TC.index("function switchLeftTab(")], "")
check("40. 畳みを開いたら分割を挟み直す", "clampSumSplit()" in _TC[_TC.index("function togSumPane()"):_TC.index("function openSumPane()")], "")

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
