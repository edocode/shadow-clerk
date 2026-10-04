"""AI分析 の 🔊 の例文をクリックで読み上げる JS を node で検証する

実行: uv run python tests/test_say_js.py
"""
from __future__ import annotations
import os
import shutil
import sys

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

# ブラウザの代役と node の実行は、読み上げの JS の検証と同じものを使う
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_talk_speech_js import check, results, run, stubs  # noqa: E402

PANE = r"""
const out={};
function mkEl(text){return {textContent:text,title:'',onclick:null,classList:{list:[],add(c){this.list.push(c);}}};}
const items=[mkEl('🔊 They are there.'),mkEl('説明の文'),mkEl('\n  🔊  Quote\n')];
const root={querySelectorAll:sel=>{out.sel=sel;return items;}};
decorateSay(root);
out.classes=items.map(i=>i.classList.list);out.titles=items.map(i=>i.title);out.plain=items[1].onclick;
let stopped=0;const ev={stopPropagation(){stopped++;}};
if(items[0].onclick){items[0].onclick(ev);LANG='auto';items[2].onclick(ev);}
out.spoken=spoken.map(u=>({text:u.text,lang:u.lang}));out.stopped=stopped;
console.log(JSON.stringify(out));
"""


def test_say_marks_and_speaks() -> None:
    out = run(stubs(), PANE)
    check("段落・リスト項目・引用を見る", out["sel"] == "p,li,blockquote", repr(out))
    check("🔊 で始まる項目にだけ .say を付ける", out["classes"] == [["say"], [], ["say"]], repr(out))
    check("クリックできると分かる title", out["titles"] == ["SAY", "", "SAY"], repr(out))
    check("🔊 の無い項目はクリックしても何もしない", out["plain"] is None, repr(out))
    check("🔊 の後ろの文を聞き取り中の言語で読む（auto なら言語を指定しない）",
          out["spoken"] == [{"text": "They are there.", "lang": "en"}, {"text": "Quote", "lang": ""}], repr(out))
    check("入れ子（引用の中の段落）で二度読まない", out["stopped"] == 2, repr(out))


def test_no_speech_synthesis() -> None:
    out = run(stubs(speech=False), PANE)
    check("speechSynthesis が無ければ .say を付けない", out["classes"] == [[], [], []] and out["spoken"] == [], repr(out))


def test_render_calls_decorate() -> None:
    from shadow_clerk._daemon_dashboard_js import _JS_TEMPLATE
    from shadow_clerk._daemon_dashboard_js_core import _JS_TEMPLATE_CORE
    from shadow_clerk._daemon_dashboard_js_speech import _JS_TEMPLATE_SPEECH
    check("Advice / Analysis の描画のたびに 🔊 を付ける", "decorateSay(el);" in _JS_TEMPLATE_CORE)
    check("読み上げの JS がページに入る", _JS_TEMPLATE_SPEECH in _JS_TEMPLATE)


if __name__ == "__main__":
    test_say_marks_and_speaks()
    test_no_speech_synthesis()
    test_render_calls_decorate()
    sys.exit(0 if all(results) else 1)
