"""/next を worktree のコードで描き、それ以外を稼働中の daemon に中継する開発用プロキシ

daemon は音声デバイスを掴むので 1 台しか動かせない。このプロキシは GET /next のたびに
_daemon_dashboard_next_* と i18n を import し直して返し、/api/* の GET と SSE は upstream へ流す。
POST は --allow-writes が無い限り送らず、本文を標準出力に 1 行 JSON で出して dry-run 応答を返す。

実行: uv run python improvement/dashboard-redesign/dev_proxy.py --port 8766
"""
from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger("dev-proxy")

# 依存の順。i18n を作り直してから、流用する旧 JS の部品・/next の部品（部品が先）・組み立てを作り直す。
# 前方一致の段は名前の長い順（`_js_console_side` を `_js_console` より先に）
_RELOAD_PREFIXES = ("shadow_clerk._i18n_", "shadow_clerk.i18n", "shadow_clerk._daemon_dashboard_js_",
                    "shadow_clerk._daemon_dashboard_next_js_")
_RELOAD_ASSEMBLY = ("shadow_clerk._daemon_dashboard_js", "shadow_clerk._daemon_dashboard_css",
                    "shadow_clerk._daemon_dashboard_html", "shadow_clerk._daemon_dashboard_next_js",
                    "shadow_clerk._daemon_dashboard_next_css", "shadow_clerk._daemon_dashboard_next_html")


def _reload_order() -> list[str]:
    names = [n for n in sys.modules if n.startswith("shadow_clerk.")]
    order: list[str] = []
    for prefix in _RELOAD_PREFIXES:
        order += sorted((n for n in names if n.startswith(prefix) and n not in order and n not in _RELOAD_ASSEMBLY),
                        key=lambda n: (-len(n), n))
    return order + list(_RELOAD_ASSEMBLY)


def render_next() -> str:
    """worktree の最新のコードで /next の HTML を作る（daemon の _serve_html と同じ render_html を通す）"""
    from shadow_clerk._daemon_dashboard_base import render_html
    importlib.import_module("shadow_clerk._daemon_dashboard_next_html")
    for name in _reload_order():
        importlib.reload(sys.modules[name])
    return render_html(sys.modules["shadow_clerk._daemon_dashboard_next_html"]._NEXT_HTML_TEMPLATE)


class _Proxy(BaseHTTPRequestHandler):
    upstream = "http://127.0.0.1:8765"
    allow_writes = False

    def log_message(self, format: str, *args: object) -> None:
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path.split("?")[0] == "/next":
            self._send(200, render_next().encode("utf-8"), "text/html; charset=utf-8")
        else:
            self._forward(None)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.allow_writes:
            self._forward(body)
            return
        try:
            payload: object = json.loads(body or b"null")
        except ValueError:
            payload = body.decode("utf-8", "replace")
        sys.stdout.write(json.dumps({"dry_run": True, "path": self.path, "body": payload}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        self._send(200, b'{"status":"ok","dry_run":true}', "application/json")

    def _forward(self, body: bytes | None) -> None:
        req = urllib.request.Request(self.upstream + self.path, data=body,
                                     headers={"Content-Type": self.headers.get("Content-Type", "application/json")}
                                     if body is not None else {})
        try:
            resp = urllib.request.urlopen(req, timeout=None if self.path.startswith("/api/events") else 30)
        except urllib.error.HTTPError as e:
            self._send(e.code, e.read(), e.headers.get("Content-Type", "text/plain"))
            return
        except OSError as e:
            self._send(502, str(e).encode("utf-8"), "text/plain; charset=utf-8")
            return
        with resp:
            ctype = resp.headers.get("Content-Type", "application/octet-stream")
            if ctype.startswith("text/event-stream"):
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    while chunk := resp.read1(4096):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                except (OSError, ValueError):
                    pass
                return
            self._send(resp.status, resp.read(), ctype)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--upstream", default="http://127.0.0.1:8765")
    ap.add_argument("--allow-writes", action="store_true", help="POST も upstream に送る（既定は dry-run）")
    args = ap.parse_args()
    _Proxy.upstream, _Proxy.allow_writes = args.upstream.rstrip("/"), args.allow_writes
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logger.info("dev proxy http://127.0.0.1:%d/next -> %s (writes: %s)", args.port, _Proxy.upstream,
                "forwarded" if args.allow_writes else "dry-run")
    ThreadingHTTPServer(("127.0.0.1", args.port), _Proxy).serve_forever()


if __name__ == "__main__":
    main()
