"""口のかたち図鑑（/mouth）と、AI分析 の発音記号をそこへのリンクにする JS を検証する

実行: uv run python tests/test_mouth_chart.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from importlib import resources

from shadow_clerk._daemon_dashboard_next_js_right import _NEXT_JS_RIGHT

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


# 正規表現とリンク生成だけを切り出して動かす（DOM の走査は実ブラウザで見る）
_SRC = _NEXT_JS_RIGHT[_NEXT_JS_RIGHT.index("const nxIpaCh"):_NEXT_JS_RIGHT.index("function nxLinkifyFiles")]
_BODY = r"""
const I18N={'nx.mouth_link':'口のかたちを見る'};
const document={createElement:()=>({addEventListener(){}})};
// 表のセルのテキストノードの偽物（1列目に綴り）
const cell=t=>{const row={querySelector:()=>({textContent:' right '})};const td={parentElement:row};
  return {parentElement:{closest:()=>td}};};
const texts=[
 '/θ/ が /s/ に聞こえました。',
 'お手本 /θɪŋk/ と /ðə ˈkæt/。',
 '舌先 /r/ と /tʃ/、/l/。',
 '`/api/say` と /api/ と A/B と and/or と 1/2/3。',
];
const links=texts.map(t=>[...t.matchAll(nxIpaRe)].map(m=>{const a=nxIpaLink(m,null);
  return a?[a.textContent,a.href,a.target,a.title]:[m[0],null];}));
const words=['think /θɪŋk/ と went /wɛnt/。','お手本 /θɪŋk/'].map(t=>[...t.matchAll(nxIpaRe)].map(m=>nxIpaLink(m,null).href));
const inCell=nxIpaLink([...'/ɹaɪt/'.matchAll(nxIpaRe)][0],cell()).href;
console.log(JSON.stringify({links,words,inCell}));
"""


def test_ipa_links() -> None:
    if shutil.which("node") is None:
        print("[SKIP] node が無いため JS は実行しない")
        return
    r = subprocess.run(["node", "-e", _SRC + _BODY], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        check("node で実行できる", False, r.stderr[-500:])
        return
    res = json.loads(r.stdout.strip().splitlines()[-1])
    out = res["links"]
    check("直前の英単語を綴りとして渡す", res["words"][0] == [
        "/mouth?ipa=%CE%B8%C9%AA%C5%8Bk&word=think", "/mouth?ipa=w%C9%9Bnt&word=went"], repr(res["words"]))
    check("英単語が無ければ綴りを付けない", res["words"][1] == ["/mouth?ipa=%CE%B8%C9%AA%C5%8Bk"], repr(res["words"]))
    check("表では同じ行の1列目を綴りにする", res["inCell"] == "/mouth?ipa=%C9%B9a%C9%AAt&word=right", res["inCell"])
    th = "%CE%B8"
    check("1音の記号は図鑑のその音を開く", out[0] == [
        ["/θ/", f"/mouth?ipa={th}", "shadow-clerk-mouth", "口のかたちを見る"],
        ["/s/", "/mouth?ipa=s", "shadow-clerk-mouth", "口のかたちを見る"]], repr(out[0]))
    check("単語・空白入りの文の記号もリンクにする",
          [o[0] for o in out[1]] == ["/θɪŋk/", "/ðə ˈkæt/"], repr(out[1]))
    check("英字だけの短い記号（/r/・/l/）と /tʃ/ も拾う", [o[0] for o in out[2]] == ["/r/", "/tʃ/", "/l/"], repr(out[2]))
    check("パスや A/B はリンクにしない", all(o[1] is None for o in out[3]), repr(out[3]))


def test_page() -> None:
    html = resources.files("shadow_clerk").joinpath("mouth_chart.html").read_text(encoding="utf-8")
    check("図鑑を同梱する", html.startswith("<!doctype html>") and "<title>" in html)
    check("外部のフォントを読まない（ローカルで完結する）", "fonts.googleapis" not in html and "https://" not in html)
    check("?ipa= で音・単語を開く", "URLSearchParams(location.search).get('ipa')" in html)
    check("ブラウザの声で綴りを読む", "speechSynthesis.speak" in html and "get('word')" in html)


def test_route() -> None:
    from shadow_clerk._daemon_dashboard_base import _DashboardHandlerBase

    class _H(_DashboardHandlerBase):
        def __init__(self) -> None:  # pylint: disable=super-init-not-called
            self.path, self.served = "/mouth", ""

        def _serve_html(self, template: str) -> None:
            self.served = template

    h = _H()
    h.do_GET()
    check("GET /mouth で図鑑を返す", "英語発音 口のかたち図鑑" in h.served)


if __name__ == "__main__":
    test_ipa_links()
    test_page()
    test_route()
    sys.exit(0 if all(results) else 1)
