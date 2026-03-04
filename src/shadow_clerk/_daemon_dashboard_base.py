"""Shadow-clerk daemon: ダッシュボード HTTP ハンドラー（ルーティング・基本エンドポイント）"""

import json
import logging
import os
import queue
import re
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from shadow_clerk.i18n import t, t_all
from shadow_clerk._daemon_constants import COMMAND_FILE, SESSION_FILE
from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_dashboard_html import _HTML_TEMPLATE

logger = logging.getLogger("shadow-clerk")


class _DashboardHandlerBase(BaseHTTPRequestHandler):
    """ダッシュボード HTTP ハンドラー（ルーティング・基本エンドポイント）"""

    recorder = None
    log_buffer = None
    file_watcher = None

    def log_message(self, format, *args):
        pass  # suppress default request logging

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._serve_html()
        elif path == "/api/events":
            self._serve_sse()
        elif path == "/api/status":
            self._serve_status()
        elif path == "/api/files":
            self._serve_files()
        elif path == "/api/transcript":
            self._serve_transcript()
        elif path == "/api/translation":
            self._serve_translation()
        elif path == "/api/logs":
            self._serve_logs()
        elif path == "/api/config":
            self._serve_config()
        elif path == "/api/glossary":
            self._serve_glossary()
        elif path == "/api/summary":
            self._serve_summary()
        elif path == "/api/models":
            self._serve_models()
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/command":
            self._handle_command()
        elif path == "/api/config":
            self._save_config()
        elif path == "/api/glossary":
            self._save_glossary()
        elif path == "/api/summary/notify":
            self._notify_summary_done()
        elif path == "/api/summary":
            self._generate_summary()
        elif path == "/api/transcript/delete":
            self._delete_transcript_line()
        elif path == "/api/transcript/delete-file":
            self._delete_transcript_file()
        elif path == "/api/transcript/extract-meeting":
            self._extract_meeting()
        else:
            self.send_error(404)

    def _send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        from shadow_clerk import i18n as _i18n
        _i18n.init()  # re-read config for ui_language changes
        html = _HTML_TEMPLATE
        html = re.sub(r'\{\{i18n:([^}]+)\}\}', lambda m: t(m.group(1)), html)
        html = html.replace("/*I18N_JSON*/", f"const I18N={json.dumps(t_all(), ensure_ascii=False)};")
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        client_q = self.file_watcher.add_client()
        try:
            while not self.recorder.stop_event.is_set():
                try:
                    event, data = client_q.get(timeout=15)
                    self.wfile.write(
                        f"event: {event}\ndata: {data}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.file_watcher.remove_client(client_q)

    def _serve_status(self):
        session = ""
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                session = f.read().strip()
        except OSError:
            pass
        translating = (self.recorder._translate_thread is not None
                       and self.recorder._translate_thread.is_alive()
                       ) or self.recorder._translating_external
        self._send_json({
            "running": not self.recorder.stop_event.is_set(),
            "backend": self.recorder.backend_name,
            "model": self.recorder.transcriber.model_size,
            "language": self.recorder.transcriber.language or "auto",
            "output_path": self.recorder.output_path,
            "session": session or None,
            "translating": translating,
            "mute_mic": self.recorder.mute_mic,
            "mute_monitor": self.recorder.mute_monitor,
            "ptt": self.recorder._command_mode,
            "asr_backend": self.recorder.transcriber._backend,
            "asr_model_id": self.recorder.transcriber._loaded_model_id or self.recorder.transcriber.model_size,
        })

    def _serve_files(self):
        output_dir = self.recorder._output_dir
        files = []
        try:
            for f in sorted(os.listdir(output_dir), reverse=True):
                if (f.startswith("transcript-") and f.endswith(".txt")
                        and not re.search(r"-[a-z]{2}\.txt$", f)):
                    files.append(f)
        except OSError:
            pass
        self._send_json({
            "files": files,
            "active": os.path.basename(self.recorder.output_path),
        })

    def _serve_transcript(self):
        params = parse_qs(urlparse(self.path).query)
        file_param = params.get("file", [None])[0]
        if file_param:
            file_param = os.path.basename(file_param)
            filepath = os.path.join(self.recorder._output_dir, file_param)
        else:
            filepath = self.recorder.output_path
        lines = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            lines = [l.rstrip("\n") for l in all_lines]
        except OSError:
            pass
        self._send_json({
            "file": os.path.basename(filepath), "lines": lines})

    def _serve_translation(self):
        params = parse_qs(urlparse(self.path).query)
        file_param = params.get("file", [None])[0]
        if file_param:
            file_param = os.path.basename(file_param)
            filepath = os.path.join(self.recorder._output_dir, file_param)
        else:
            config = load_config()
            lang = config.get("translate_language", "ja")
            basename = os.path.basename(self.recorder.output_path)
            tr_name = basename.replace(".txt", f"-{lang}.txt")
            filepath = os.path.join(self.recorder._output_dir, tr_name)
        lines = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            lines = [l.rstrip("\n") for l in all_lines]
        except OSError:
            pass
        self._send_json({
            "file": os.path.basename(filepath), "lines": lines})

    def _serve_logs(self):
        self._send_json({"lines": self.log_buffer.get_lines(100)})

    def _handle_command(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            cmd = data.get("command", "").strip()
        except (json.JSONDecodeError, ValueError):
            self.send_error(400)
            return
        if not cmd:
            self.send_error(400)
            return
        with open(COMMAND_FILE, "w", encoding="utf-8") as f:
            f.write(cmd)
        logger.info("ダッシュボードからコマンド: %s", cmd)
        self._send_json({"status": "ok", "command": cmd})

    def _get_summary_path(self, transcript_path: str = None) -> str:
        """transcript パスから summary パスを導出する"""
        if transcript_path is None:
            transcript_path = self.recorder.output_path
        basename = os.path.basename(transcript_path)
        summary_name = basename.replace("transcript-", "summary-").replace(".txt", ".md")
        return os.path.join(self.recorder._output_dir, summary_name)

    def _serve_summary(self):
        """GET /api/summary — summary ファイルの内容を返す"""
        params = parse_qs(urlparse(self.path).query)
        file_param = params.get("file", [None])[0]
        if file_param:
            # transcript ファイル名から summary パスを導出
            file_param = os.path.basename(file_param)
            summary_name = file_param.replace("transcript-", "summary-").replace(".txt", ".md")
            summary_path = os.path.join(self.recorder._output_dir, summary_name)
        else:
            summary_path = self._get_summary_path()
        summary_name = os.path.basename(summary_path)
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._send_json({"file": summary_name, "content": content})
        except FileNotFoundError:
            self._send_json({"file": summary_name, "content": ""})

    def _generate_summary(self):
        """POST /api/summary — 要約生成をトリガーする"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            data = {}
        file_param = data.get("file")
        if file_param:
            transcript_path = os.path.join(self.recorder._output_dir, os.path.basename(file_param))
        else:
            transcript_path = self.recorder.output_path
        if not os.path.exists(transcript_path):
            self._send_json({"status": "error", "message": t("dash.transcript_not_found")})
            return
        config = load_config()
        if config.get("llm_provider") == "api":
            self._send_json({"status": "ok", "message": t("dash.summary_generation_started")})
            threading.Thread(
                target=self.recorder._auto_summarize,
                args=(transcript_path,),
                name="dashboard-summary", daemon=True,
            ).start()
        else:
            # Claude provider: .clerk_command に書いて Claude Code に処理させる（全文モード）
            transcript_name = os.path.basename(transcript_path)
            with open(COMMAND_FILE, "w", encoding="utf-8") as f:
                f.write(f"generate_summary_full {transcript_name}")
            self._send_json({"status": "ok", "message": t("dash.summary_generation_started")})

    def _notify_summary_done(self):
        """POST /api/summary/notify — 外部プロセスからの要約完了通知"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            data = json.loads(body) if body else {}
        except (json.JSONDecodeError, ValueError):
            data = {}
        summary_name = data.get("name", "")
        if summary_name and hasattr(self.recorder, "_file_watcher"):
            self.recorder._file_watcher._broadcast("alert", json.dumps(
                {"message": t("dash.alert_summary_done", name=summary_name)},
                ensure_ascii=False))
        self._send_json({"status": "ok"})
