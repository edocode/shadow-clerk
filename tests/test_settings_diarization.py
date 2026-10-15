"""設定モーダルの話者分離キーの保存 (server) と フォーム (JS) の検証

実行: uv run python tests/test_settings_diarization.py
一時ディレクトリ内で完結する。
"""
from __future__ import annotations
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

# **import より前に差し替えること。** CONFIG_FILE は import 時に DATA_DIR から決まる
DATA = tempfile.mkdtemp(prefix="shadow-clerk-settings-")
os.environ["SHADOW_CLERK_DATA_DIR"] = DATA

import yaml  # noqa: E402
from shadow_clerk import CONFIG_FILE  # noqa: E402
from shadow_clerk._daemon_constants import DEFAULT_CONFIG  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_config import _DashboardHandlerConfigOps as Ops  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Handler(Ops):
    def __init__(self, body: object) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}

    def _send_json(self, d: dict) -> None:
        self.sent = d

    def _atomic_write_lines(self, path: str, lines: list[str]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)


def saved() -> dict:
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def post(body: dict) -> dict:
    # load_config は mtime キャッシュなので、書き直した直後でも拾えるよう mtime を進める
    _Handler(body)._save_config()
    st = os.stat(CONFIG_FILE)
    os.utime(CONFIG_FILE, (st.st_atime, st.st_mtime + 5))
    return saved()


def test_defaults() -> None:
    check("DEFAULT_CONFIG の既定値", all(DEFAULT_CONFIG.get(k) == v for k, v in {
        "speaker_diarization": False, "speaker_enrollment": False, "diarization_threshold": 0.70,
        "diarization_min_sec": 1.0, "voiceprint_max_samples": 200}.items()))
    from shadow_clerk._daemon_speaker_diarization import _MIN_SEGMENT_SEC, _SIMILARITY_THRESHOLD_DEFAULT
    from shadow_clerk._daemon_voiceprint_store import _MAX_SAMPLES_DEFAULT
    check("モジュール定数は DEFAULT_CONFIG と同じ", (
        _SIMILARITY_THRESHOLD_DEFAULT, _MIN_SEGMENT_SEC, _MAX_SAMPLES_DEFAULT)
        == (DEFAULT_CONFIG["diarization_threshold"], DEFAULT_CONFIG["diarization_min_sec"],
            DEFAULT_CONFIG["voiceprint_max_samples"]))


def test_save() -> None:
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        yaml.dump({"my_unknown_key": {"a": 1}}, f)
    c = post({"speaker_enrollment": True, "diarization_threshold": "0.65",
              "diarization_min_sec": "2.0", "voiceprint_max_samples": "150"})
    check("bool/float/int の型で保存", c["speaker_enrollment"] is True and c["diarization_threshold"] == 0.65
          and c["diarization_min_sec"] == 2.0 and c["voiceprint_max_samples"] == 150
          and isinstance(c["voiceprint_max_samples"], int), "")
    check("未知のキーは残る", c.get("my_unknown_key") == {"a": 1}, repr(c.get("my_unknown_key")))
    c = post({"diarization_threshold": "abc", "diarization_min_sec": None, "voiceprint_max_samples": "x"})
    check("不正値は既定値に戻る", (c["diarization_threshold"], c["diarization_min_sec"],
                                  c["voiceprint_max_samples"]) == (0.70, 1.0, 200), "")
    c = post({"diarization_threshold": "0.62"})
    check("一覧外の値もそのまま保存", c["diarization_threshold"] == 0.62)


HARNESS = r"""
const I18N=new Proxy({},{get:(t,k)=>String(k)});
const PATH_HINTS={};
let CFG,posted=null;const els={};
function mkEl(){return {children:[],value:'',disabled:false,textContent:'',style:{},dataset:{},classList:{add(){},remove(){}},
  appendChild(c){this.children.push(c);if(c.id)els[c.id]=c;if(c.value!==undefined&&this.tagName==='SELECT'&&this.value==='')this.value=c.value;},
  addEventListener(){},querySelector(){return null;},querySelectorAll(){return [];},set innerHTML(v){this.children=[];}};}
const document={getElementById:id=>els[id]=els[id]||mkEl(),createTextNode:t=>({}),
  createElement:tag=>{const e=mkEl();e.tagName=tag.toUpperCase();return e;}};
async function fetch(url,opt){
  if(url==='/api/config'&&!opt)return {json:async()=>JSON.parse(JSON.stringify(CFG))};
  if(url==='/api/config'){posted=JSON.parse(opt.body);return {json:async()=>({})};}
  return {json:async()=>({items:[],presets:[]})};
}
function docLink(){return '';} function refreshAudioDevices(){} async function _skillStatus(){return null;}
function loadAudioDevices(){} function esc(s){return s;}
function fetchApiModels(){} const location={reload(){}};
"""
TAIL = r"""
(async()=>{
  CFG={speaker_diarization:false,speaker_enrollment:true,diarization_threshold:0.62,
       diarization_min_sec:1.0,voiceprint_max_samples:200};
  await openCfg();
  const th=els['cfg_diarization_threshold'];
  const out={fields:['speaker_diarization','speaker_enrollment','diarization_threshold','diarization_min_sec',
    'voiceprint_max_samples'].map(k=>!!els['cfg_'+k]),
    thOpts:th.children.map(o=>o.value),thVal:th.value};
  els['cfg_voiceprint_max_samples'].value='150';
  await saveCfg();
  out.posted={e:posted.speaker_enrollment,d:posted.speaker_diarization,t:posted.diarization_threshold,
    m:posted.diarization_min_sec,n:posted.voiceprint_max_samples};
  console.log(JSON.stringify(out));
})();
"""


def test_self_group_saved() -> None:
    h = _Handler({"self_group": "自社"})
    h._save_config()
    with open(os.path.join(DATA, "config.yaml"), encoding="utf-8") as f:
        check("self_group を保存する", "self_group: 自社" in f.read())


def test_js() -> None:
    if shutil.which("node") is None:
        print("[SKIP] node が無いため JS 検証をしない")
        return
    from shadow_clerk._daemon_dashboard_js_settings import _JS_TEMPLATE_SETTINGS
    r = subprocess.run(["node", "-e", HARNESS + _JS_TEMPLATE_SETTINGS + TAIL],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("JS 実行", False, r.stderr[-500:])
        return
    o = json.loads(r.stdout.strip().splitlines()[-1])
    check("新フィールドが全て描画される", all(o["fields"]), repr(o["fields"]))
    check("一覧外の閾値 0.62 が選択肢に足され選択される", "0.62" in o["thOpts"] and o["thVal"] == "0.62", repr(o))
    check("既定の選択肢を持つ", {"0.50", "0.80", "0.70"} <= set(o["thOpts"]), repr(o["thOpts"]))
    p = o["posted"]
    check("送信値: bool と number、select は文字列", p["e"] is True and p["d"] is False and p["n"] == 150
          and p["t"] == "0.62" and p["m"] == "1.0", repr(p))


if __name__ == "__main__":
    test_defaults()
    test_save()
    test_self_group_saved()
    test_js()
    shutil.rmtree(DATA, ignore_errors=True)
    sys.exit(0 if all(results) else 1)
