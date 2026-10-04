"""ダッシュボードのブラウザ読み上げ（talk_speak）の JS を node で検証する

実行: uv run python tests/test_talk_speech_js.py
"""
from __future__ import annotations
import json
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

from shadow_clerk._daemon_dashboard_js_speech import _JS_TEMPLATE_SPEECH  # noqa: E402


def stubs(speech: bool = True, active: bool = True, voices: str = "[{lang:'en-US',name:'E'},{lang:'ja-JP',name:'J'}]") -> str:
    """ブラウザの代役。speech=False なら speechSynthesis の無いブラウザ"""
    synth = (f"let VOICES={voices};const ssHandlers={{}};\n"
             "class SpeechSynthesisUtterance{constructor(t){this.text=t;this.lang='';this.voice=null;}}\n"
             "const speechSynthesis={getVoices:()=>VOICES,speak:u=>spoken.push(u),cancel:()=>{cancels++;},"
             "addEventListener:(k,f)=>{ssHandlers[k]=f;}};\n") if speech else ""
    return ("const I18N={'dash.say_title':'SAY'};\n"
            "const posted=[],spoken=[],beacons=[],winHandlers={},esHandlers={};let cancels=0,intervals=0;\n"
            "const es={addEventListener:(k,f)=>{(esHandlers[k]=esHandlers[k]||[]).push(f);}};\n"
            "const fire=(k,d)=>(esHandlers[k]||[]).forEach(f=>f({data:JSON.stringify(d)}));\n"
            + synth +
            "Object.defineProperty(globalThis,'navigator',{configurable:true,writable:true,value:{"
            f"userActivation:{{hasBeenActive:{'true' if active else 'false'}}},"
            "sendBeacon:(u,b)=>{beacons.push([u,JSON.parse(b)]);return true;}}});\n"
            "const window={addEventListener:(k,f)=>{(winHandlers[k]=winHandlers[k]||[]).push(f);}};\n"
            "function setInterval(){intervals++;}\n"
            "async function fetch(url,opt){posted.push([url,JSON.parse(opt.body)]);return {json:async()=>({status:'ok'})};}\n"
            "let LANG='en';const document={getElementById:id=>id==='langSel'?{value:LANG}:null};\n")


def run(prefix: str, body: str) -> dict:
    r = subprocess.run(["node", "-e", prefix + _JS_TEMPLATE_SPEECH + body], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-500:])
        sys.exit(1)
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_ready() -> None:
    out = run(stubs(), r"""
const ready=()=>posted.filter(p=>p[0]==='/api/talk-speech/ready').map(p=>p[1]);
const out={onLoad:ready(),intervals,tab:SPEECH_TAB};
posted.length=0;fire('transcript',{});out.soon=ready().length;
_speechLast=0;fire('transcript',{});out.later=ready().length;
(winHandlers.pagehide||[]).forEach(f=>f());out.beacons=beacons;
console.log(JSON.stringify(out));
""")
    check("開いたときに声のある言語で名乗る", out["onLoad"] == [{"tab": out["tab"], "langs": ["en", "ja"]}], repr(out))
    check("30 秒ごとに名乗り直す", out["intervals"] == 1, repr(out))
    check("発言が届いても 10 秒以内なら名乗り直さない", out["soon"] == 0, repr(out))
    check("発言が届いたら名乗り直す（背景タブのタイマー間引き対策）", out["later"] == 1, repr(out))
    check("閉じるときは名乗りを取り下げる",
          out["beacons"] == [["/api/talk-speech/ready", {"tab": out["tab"], "langs": []}]], repr(out))


def test_ready_waits_for_voices_and_activation() -> None:
    out = run(stubs(voices="[]"), r"""
const out={onLoad:posted.length};VOICES=[{lang:'fr-FR',name:'F'}];ssHandlers.voiceschanged();
out.afterVoices=posted.map(p=>p[1].langs);console.log(JSON.stringify(out));
""")
    check("声が無ければ名乗らない", out["onLoad"] == 0, repr(out))
    check("声の一覧が変わったら名乗る", out["afterVoices"] == [["fr"]], repr(out))
    out = run(stubs(active=False), r"""
const out={onLoad:posted.length};navigator.userActivation.hasBeenActive=true;
(winHandlers.pointerdown||[]).forEach(f=>f());out.afterClick=posted.length;console.log(JSON.stringify(out));
""")
    check("一度も操作されていないページは名乗らない（Chrome が speak を拒む）", out["onLoad"] == 0, repr(out))
    check("最初の操作で名乗る", out["afterClick"] == 1, repr(out))


def test_speak_only_own_tab() -> None:
    out = run(stubs(), r"""
const out={};
fire('talk_speak',{id:'s1',tab:'other',text:'No.',lang:'en'});out.other=spoken.length;
fire('talk_speak',{id:'s2',tab:SPEECH_TAB,text:'Yes.',lang:'en'});
const u=spoken[0];out.utt={text:u.text,lang:u.lang,voice:u.voice&&u.voice.name};
posted.length=0;u.onend();out.onEnd=posted.map(p=>p);
fire('talk_speak',{id:'s3',tab:SPEECH_TAB,text:'Again.',lang:'en'});
posted.length=0;spoken[1].onerror({error:'interrupted'});out.onError=posted.map(p=>p);
fire('talk_speak_cancel',{id:'s3',tab:'other'});out.cancelOther=cancels;
fire('talk_speak_cancel',{id:'s3',tab:SPEECH_TAB});out.cancelMine=cancels;
console.log(JSON.stringify(out));
""")
    check("ほかのタブ宛ての文は読まない", out["other"] == 0, repr(out))
    check("自分宛ての文をその言語の声で読む", out["utt"] == {"text": "Yes.", "lang": "en", "voice": "E"}, repr(out))
    check("読み終えたら done を返す", out["onEnd"] == [["/api/talk-speech/done", {"id": "s2"}]], repr(out))
    check("読めなかったときも done を返す", out["onError"] == [["/api/talk-speech/done", {"id": "s3"}]], repr(out))
    check("ほかのタブ宛ての cancel では止めない", out["cancelOther"] == 0, repr(out))
    check("自分宛ての cancel で止める", out["cancelMine"] == 1, repr(out))


def test_utterance_kept_until_end() -> None:
    """Chrome は参照の切れた SpeechSynthesisUtterance を GC し、onend が来なくなる。読み終えるまで持っておく"""
    out = run(stubs(), r"""
const out={};
fire('talk_speak',{id:'s1',tab:SPEECH_TAB,text:'Yes.',lang:'en'});
const u=spoken[0];out.held=_speechLive.has(u);u.onend();out.afterEnd=_speechLive.has(u);
speakText('Click.','en');const c=spoken[1];out.heldNoDone=_speechLive.has(c);
c.onerror({error:'interrupted'});out.afterError=_speechLive.has(c);
console.log(JSON.stringify(out));
""")
    check("読み終えるまで utterance を持っておく", out["held"] and out["heldNoDone"], repr(out))
    check("読み終えたら・失敗したら手放す", not out["afterEnd"] and not out["afterError"], repr(out))


def test_no_speech_synthesis() -> None:
    out = run(stubs(speech=False), "console.log(JSON.stringify({posted:posted.length,handlers:Object.keys(esHandlers)}));")
    check("speechSynthesis が無ければ名乗らず、イベントも聞かない", out == {"posted": 0, "handlers": []}, repr(out))


if __name__ == "__main__":
    test_ready()
    test_ready_waits_for_voices_and_activation()
    test_speak_only_own_tab()
    test_utterance_kept_until_end()
    test_no_speech_synthesis()
    sys.exit(0 if all(results) else 1)
