"""Shadow-clerk daemon: ダッシュボード HTTP ハンドラー（ルーティング・基本エンドポイント）"""
from __future__ import annotations
import json
from typing import Any
import logging
import os
import queue
import re
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from shadow_clerk.i18n import t, t_all
from shadow_clerk._daemon_constants import SESSION_FILE
from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_dashboard_html import _HTML_TEMPLATE
from shadow_clerk._transcript_name import TranscriptName

logger = logging.getLogger("shadow-clerk")


class _DashboardHandlerBase(BaseHTTPRequestHandler):
    """ダッシュボード HTTP ハンドラー（ルーティング・基本エンドポイント）"""

    recorder: Any = None
    log_buffer: Any = None
    file_watcher: Any = None
    gcal_monitor: Any = None

    def log_message(self, format: str, *args: object) -> None:
        pass  # suppress default request logging

    def do_GET(self) -> None:
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
        elif path == "/api/gcal-events":
            self._serve_gcal_events()
        elif path == "/api/attendees":
            self._serve_attendees()
        elif path == "/api/search":
            self._serve_search()
        else:
            self.send_error(404)

    def do_POST(self) -> None:
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
        elif path == "/api/transcript/split-by-silence":
            self._split_by_silence()
        elif path == "/api/transcript/rename-meeting":
            self._rename_meeting()
        elif path == "/api/transcript/merge-to-daily":
            self._merge_meeting_to_daily()
        else:
            self.send_error(404)

    def _send_json(self, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self) -> None:
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

    def _serve_sse(self) -> None:
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

    def _serve_status(self) -> None:
        session = ""
        try:
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                session = f.read().strip()
        except OSError:
            pass
        translating = (self.recorder._translate_thread is not None
                       and self.recorder._translate_thread.is_alive())
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
            "use_mic": self.recorder.use_mic,
            "use_monitor": self.recorder.use_monitor,
            "ptt": self.recorder._command_mode,
            "asr_backend": self.recorder.transcriber._backend,
            "asr_model_id": self.recorder.transcriber._loaded_model_id or self.recorder.transcriber.model_size,
            "gcal_enabled": self.__class__.gcal_monitor is not None,
        })

    def _serve_files(self) -> None:
        output_dir = self.recorder._output_dir
        transcript_file_names: list[tuple[str, TranscriptName]] = []
        try:
            all_files = set(os.listdir(output_dir))
        except OSError:
            all_files = set()
        for f in sorted(all_files, reverse=True):
            if (tn := TranscriptName.parse(f)) is not None:
                transcript_file_names.append((f, tn))
        # 翻訳言語を取得
        config = load_config()
        lang = config.get("translate_language", "ja")
        # 会議グループと file_info を構築
        groups: dict[str, list[str]] = {}
        file_info: dict[str, dict] = {}
        for f, tn in transcript_file_names:
            info = tn.file_info()
            info["has_translation"] = tn.translation_filename(lang) in all_files
            info["has_summary"] = tn.summary_filename in all_files
            file_info[f] = info
            if tn.meeting_group is not None:
                groups.setdefault(tn.meeting_group, []).append(f)
        self._send_json({
            "files": [f for f, _ in transcript_file_names],
            "active": os.path.basename(self.recorder.output_path),
            "groups": groups,
            "file_info": file_info,
        })

    def _serve_transcript(self) -> None:
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

    def _serve_translation(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        file_param = params.get("file", [None])[0]
        config = load_config()
        lang = config.get("translate_language", "ja")
        if file_param:
            file_param = os.path.basename(file_param)
            tn = TranscriptName.parse(file_param)
            if tn:
                tr_name = tn.translation_filename(lang)
            elif TranscriptName.parse_translation(file_param) is not None:
                # 既に翻訳ファイル名の場合はそのまま使用
                tr_name = file_param
            else:
                self._send_json({"file": "", "lines": []})
                return
            filepath = os.path.join(self.recorder._output_dir, tr_name)
        else:
            basename = os.path.basename(self.recorder.output_path)
            tn = TranscriptName.parse(basename)
            if tn is None:
                self._send_json({"file": "", "lines": []})
                return
            tr_name = tn.translation_filename(lang)
            filepath = os.path.join(self.recorder._output_dir, tr_name)
        lines = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
            lines = [l.rstrip("\n") for l in all_lines]
        except OSError:
            pass
        translating = (self.recorder._translate_thread is not None
                       and self.recorder._translate_thread.is_alive())
        self._send_json({
            "file": os.path.basename(filepath), "lines": lines, "translating": translating})

    def _serve_logs(self) -> None:
        self._send_json({"lines": self.log_buffer.get_lines(100)})

    def _handle_command(self) -> None:
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
        logger.info("ダッシュボードからコマンド: %s", cmd)
        self.recorder._execute_command(cmd)
        self._send_json({"status": "ok", "command": cmd})

    def _get_summary_path(self, transcript_path: str | None = None) -> str:
        """transcript パスから summary パスを導出する"""
        if transcript_path is None:
            transcript_path = self.recorder.output_path
        basename = os.path.basename(transcript_path)
        tn = TranscriptName.parse(basename)
        if tn is None:
            return os.path.join(self.recorder._output_dir, basename)
        return os.path.join(self.recorder._output_dir, tn.summary_filename)

    def _serve_attendees(self) -> None:
        """GET /api/attendees?file=<transcript-filename>
        指定した transcript ファイルの参加予定者リストを返す"""
        params = parse_qs(urlparse(self.path).query)
        file_param = params.get("file", [None])[0]
        if not file_param:
            self._send_json({"attendees": []})
            return
        tn = TranscriptName.parse(os.path.basename(file_param))
        if tn is None:
            self._send_json({"attendees": []})
            return
        path = os.path.join(self.recorder._output_dir, tn.attendees_filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._send_json({"attendees": []})
            return
        attendees = [a for a in (data.get("attendees") or []) if isinstance(a, str) and a.strip()]
        self._send_json({"attendees": attendees})

    def _serve_summary(self) -> None:
        """GET /api/summary — summary ファイルの内容を返す"""
        params = parse_qs(urlparse(self.path).query)
        file_param = params.get("file", [None])[0]
        if file_param:
            file_param = os.path.basename(file_param)
            tn = TranscriptName.parse(file_param)
            if tn is None:
                self._send_json({"summary": "", "summary_file": ""})
                return
            summary_path = os.path.join(self.recorder._output_dir, tn.summary_filename)
        else:
            summary_path = self._get_summary_path()
        summary_name = os.path.basename(summary_path)
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._send_json({"file": summary_name, "content": content})
        except FileNotFoundError:
            self._send_json({"file": summary_name, "content": ""})

    def _generate_summary(self) -> None:
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
        logger.info("ダッシュボード: 要約生成 provider=%s, file=%s",
                    config.get("llm_provider", "claude"), os.path.basename(transcript_path))
        self._send_json({"status": "ok", "message": t("dash.summary_generation_started")})
        threading.Thread(
            target=self.recorder._auto_summarize,
            args=(transcript_path,),
            name="dashboard-summary", daemon=True,
        ).start()

    def _notify_summary_done(self) -> None:
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
