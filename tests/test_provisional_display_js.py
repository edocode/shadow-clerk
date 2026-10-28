"""仮登録の表示差し替え（spSpan）を node で検証する

実行: uv run python tests/test_provisional_display_js.py
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys

from shadow_clerk._daemon_dashboard_js_core import _JS_TEMPLATE_CORE

if shutil.which("node") is None:
    print("[SKIP] node が無いため実行しない")
    sys.exit(0)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_SRC = _JS_TEMPLATE_CORE[_JS_TEMPLATE_CORE.index("function spCls"):_JS_TEMPLATE_CORE.index("function fmtLine")]
_BODY = r"""
const I18N={'speaker.mic':'自分','speaker.monitor':'相手','dash.speakers_provisional_mark':'PROV'};
function esc(s){return String(s);}function escAttr(s){return String(s);}
function spColor(sp){return sp==='太郎'?'#e57373':'';}
let spkProv={labels:{'相手A':'太郎','次郎':'三郎'},lines:{'10:00:02\t相手A':'次郎','10:00:03\t相手':'花子'}};
console.log(JSON.stringify([spSpan('10:00:01','相手A'),spSpan('10:00:02','相手A'),spSpan('10:00:03','相手'),
  spSpan('10:00:04','相手'),spSpan('10:00:05','自分'),spSpan('10:00:06','相手B')]));
"""


def main() -> None:
    r = subprocess.run(["node", "-e", _SRC + _BODY], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-500:])
        sys.exit(1)
    by_label, by_line, loose, plain, me, other = json.loads(r.stdout)
    check("ラベル単位の仮登録で名前に差し替え、色と印を付ける", by_label ==
          '<span class="sp-o sp-prov" data-sp="太郎" title="PROV" style="color:#e57373">[太郎]</span>', by_label)
    check("行単位が先、その名前にラベル単位を当てる（本登録と同じ順）", "[三郎]" in by_line, by_line)
    check("分離なしの「相手」の行も行単位で差し替える", "[花子]" in loose and "sp-prov" in loose, loose)
    check("仮登録の無い行はそのまま", plain == '<span class="sp-o" data-sp="相手">[相手]</span>'
          and "sp-prov" not in me and other == '<span class="sp-o" data-sp="相手B">[相手B]</span>', repr((plain, me, other)))


if __name__ == "__main__":
    main()
    sys.exit(0 if all(results) else 1)
