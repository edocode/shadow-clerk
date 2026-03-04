"""Shadow-clerk daemon: Web ダッシュボード"""

import collections
import json
import logging
import os
import queue
import re
import threading
import urllib.request
import yaml
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from shadow_clerk import DATA_DIR, CONFIG_FILE
from shadow_clerk.i18n import t, t_all
from shadow_clerk._daemon_constants import (
    COMMAND_FILE, SESSION_FILE, GLOSSARY_FILE, DEFAULT_CONFIG,
)
from shadow_clerk._daemon_config import load_config

try:
    from shadow_clerk.llm_client import get_api_client, load_glossary, load_glossary_replacements, load_dotenv as llm_load_dotenv, _spell_check
    _HAS_LLM_CLIENT = True
except ImportError:
    _HAS_LLM_CLIENT = False

logger = logging.getLogger("shadow-clerk")


class LogBuffer(logging.Handler):
    """ログ用の循環バッファ（メモリ内でログ行を保持）"""

    def __init__(self, maxlen=500):
        super().__init__()
        self._buf = collections.deque(maxlen=maxlen)
        self._seq = 0
        self._buf_lock = threading.Lock()

    def emit(self, record):
        line = self.format(record)
        with self._buf_lock:
            self._buf.append((self._seq, line))
            self._seq += 1

    @property
    def counter(self):
        with self._buf_lock:
            return self._seq

    def get_lines(self, n=100):
        with self._buf_lock:
            items = list(self._buf)
        return [line for _, line in items[-n:]]

    def get_new_lines(self, since):
        with self._buf_lock:
            items = list(self._buf)
            seq = self._seq
        return [line for s, line in items if s >= since], seq


class FileWatcher(threading.Thread):
    """ファイル監視 + SSE ブロードキャスト"""

    def __init__(self, recorder, log_buffer):
        super().__init__(name="file-watcher", daemon=True)
        self._recorder = recorder
        self._log_buffer = log_buffer
        self._clients = []
        self._clients_lock = threading.Lock()
        self._file_offsets = {}
        self._mtimes = {}
        self._log_counter = 0
        self._last_status = None
        self._last_ptt = None

    def add_client(self):
        q = queue.Queue()
        running = not self._recorder.stop_event.is_set()
        q.put(("recorder_status", json.dumps({"running": running})))
        with self._clients_lock:
            self._clients.append(q)
        return q

    def remove_client(self, q):
        with self._clients_lock:
            try:
                self._clients.remove(q)
            except ValueError:
                pass

    def _broadcast(self, event, data):
        with self._clients_lock:
            for q in self._clients:
                try:
                    q.put_nowait((event, data))
                except Exception:
                    pass

    def _get_size(self, path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _get_mtime(self, path):
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0

    def _read_diff(self, path, old_size):
        try:
            new_size = os.path.getsize(path)
            if new_size <= old_size:
                return None, new_size
            with open(path, "rb") as f:
                f.seek(old_size)
                diff = f.read().decode("utf-8", errors="replace")
            return diff, new_size
        except OSError:
            return None, 0

    def run(self):
        t_path = self._recorder.output_path
        self._file_offsets[("transcript", t_path)] = self._get_size(t_path)
        self._log_counter = self._log_buffer.counter

        while not self._recorder.stop_event.is_set():
            try:
                self._poll()
            except Exception:
                pass
            self._recorder.stop_event.wait(timeout=1.0)

    def _poll(self):
        # Transcript
        t_path = self._recorder.output_path
        key = ("transcript", t_path)
        if key not in self._file_offsets:
            self._file_offsets[key] = self._get_size(t_path)
        diff, new_size = self._read_diff(t_path, self._file_offsets.get(key, 0))
        if diff:
            self._file_offsets[key] = new_size
            self._broadcast("transcript", json.dumps(
                {"file": os.path.basename(t_path), "diff": diff}, ensure_ascii=False))

        # Translation
        config = load_config()
        lang = config.get("translate_language", "ja")
        tr_name = os.path.basename(t_path).replace(".txt", f"-{lang}.txt")
        tr_path = os.path.join(os.path.dirname(t_path), tr_name)
        key = ("translation", tr_path)
        if key not in self._file_offsets:
            self._file_offsets[key] = self._get_size(tr_path)
        diff, new_size = self._read_diff(tr_path, self._file_offsets.get(key, 0))
        if diff:
            self._file_offsets[key] = new_size
            self._broadcast("translation", json.dumps(
                {"file": tr_name, "diff": diff}, ensure_ascii=False))

        # Metadata files (mtime-based)
        for evt, path in [
            ("session", SESSION_FILE),
            ("command", COMMAND_FILE),
            ("response", os.path.join(DATA_DIR, ".clerk_response")),
            ("config", CONFIG_FILE),
        ]:
            mtime = self._get_mtime(path)
            if mtime != self._mtimes.get(evt, 0):
                self._mtimes[evt] = mtime
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                except OSError:
                    content = ""
                self._broadcast(evt, json.dumps(
                    {"content": content}, ensure_ascii=False))

        # Recorder status
        running = not self._recorder.stop_event.is_set()
        if running != self._last_status:
            self._last_status = running
            self._broadcast("recorder_status", json.dumps({"running": running}))

        # PTT status
        ptt = self._recorder._command_mode
        if ptt != self._last_ptt:
            self._last_ptt = ptt
            self._broadcast("ptt", json.dumps({"active": ptt}))

        # Logs
        new_lines, self._log_counter = self._log_buffer.get_new_lines(
            self._log_counter)
        for line in new_lines:
            self._broadcast("log", json.dumps(
                {"line": line}, ensure_ascii=False))


class DashboardHandler(BaseHTTPRequestHandler):
    """ダッシュボード HTTP ハンドラ"""

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

    def _delete_transcript_line(self):
        """POST /api/transcript/delete — transcript 行を削除（対応する翻訳行も削除）
        {line, file} (単一行・後方互換) と {lines: [...], file} (複数行) の両方を受付
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            raw_lines = data.get("lines", [])
            if not raw_lines:
                single = data.get("line", "")
                if single:
                    raw_lines = [single]
            file_param = data.get("file", "")
        except (json.JSONDecodeError, ValueError):
            self.send_error(400)
            return
        if not raw_lines or not file_param:
            self.send_error(400)
            return

        # transcript ファイルパス
        t_path = os.path.join(self.recorder._output_dir, os.path.basename(file_param))
        if not os.path.exists(t_path):
            self._send_json({"status": "error", "message": t("dash.transcript_not_found")})
            return

        # transcript から行削除
        if not self._remove_lines_from_file(t_path, raw_lines):
            self._send_json({"status": "error", "message": t("dash.delete_error")})
            return

        # タイムスタンプを抽出して翻訳ファイルから対応行を削除
        timestamps = []
        for raw_line in raw_lines:
            ts_match = re.match(r"^\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]", raw_line)
            if ts_match:
                timestamps.append(ts_match.group(1))
        if timestamps:
            config = load_config()
            lang = config.get("translate_language", "ja")
            tr_name = os.path.basename(t_path).replace(".txt", f"-{lang}.txt")
            tr_path = os.path.join(os.path.dirname(t_path), tr_name)
            if os.path.exists(tr_path):
                self._remove_lines_from_file_by_ts(tr_path, timestamps)
                tr_key = ("translation", tr_path)
                if self.file_watcher and tr_key in self.file_watcher._file_offsets:
                    self.file_watcher._file_offsets[tr_key] = self._get_file_size(tr_path)

        # FileWatcher のオフセットをリセット
        t_key = ("transcript", t_path)
        if self.file_watcher and t_key in self.file_watcher._file_offsets:
            self.file_watcher._file_offsets[t_key] = self._get_file_size(t_path)

        # translate_offset ファイルを新 transcript サイズに更新
        offset_file = t_path + ".translate_offset"
        if os.path.exists(offset_file):
            try:
                with open(offset_file, "w", encoding="utf-8") as f:
                    f.write(str(self._get_file_size(t_path)))
            except OSError:
                pass

        self._send_json({"status": "ok"})

    def _delete_transcript_file(self):
        """POST /api/transcript/delete-file — transcript ファイルと関連ファイルを一括削除"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            file_param = data.get("file", "")
        except (json.JSONDecodeError, ValueError):
            self.send_error(400)
            return
        if not file_param:
            self.send_error(400)
            return

        output_dir = self.recorder._output_dir
        t_path = os.path.join(output_dir, os.path.basename(file_param))
        if not os.path.exists(t_path):
            self._send_json({"status": "error", "message": t("dash.transcript_not_found")})
            return

        deleted = []
        # 1. transcript ファイル削除
        try:
            os.remove(t_path)
            deleted.append(os.path.basename(t_path))
        except OSError:
            self._send_json({"status": "error", "message": t("dash.delete_error")})
            return

        # 日付部分を抽出 (transcript-YYYYMMDD.txt → YYYYMMDD, transcript-YYYYMMDDHHMM.txt → YYYYMMDDHHMM)
        base = os.path.basename(t_path)
        stem = base.rsplit(".", 1)[0]  # transcript-YYYYMMDD

        # 2. 全翻訳ファイル (transcript-YYYYMMDD-*.txt) を削除
        for f in os.listdir(output_dir):
            if f.startswith(stem + "-") and f.endswith(".txt"):
                fp = os.path.join(output_dir, f)
                try:
                    os.remove(fp)
                    deleted.append(f)
                except OSError:
                    pass

        # 3. summary ファイル削除 (summary-YYYYMMDD.md or summary-YYYYMMDDHHMM.md)
        date_part = stem.replace("transcript-", "")
        summary_name = f"summary-{date_part}.md"
        summary_path = os.path.join(output_dir, summary_name)
        if os.path.exists(summary_path):
            try:
                os.remove(summary_path)
                deleted.append(summary_name)
            except OSError:
                pass

        # 4. translate_offset ファイル削除
        offset_file = t_path + ".translate_offset"
        if os.path.exists(offset_file):
            try:
                os.remove(offset_file)
                deleted.append(os.path.basename(offset_file))
            except OSError:
                pass

        # 5. FileWatcher オフセットから当該エントリ削除
        if self.file_watcher:
            keys_to_remove = [k for k in self.file_watcher._file_offsets
                              if k[1] == t_path or k[1].startswith(os.path.join(output_dir, stem + "-"))]
            for k in keys_to_remove:
                del self.file_watcher._file_offsets[k]
            # mtime キャッシュもクリア
            keys_to_remove_mt = [k for k in self.file_watcher._mtimes
                                 if k == t_path or k.startswith(os.path.join(output_dir, stem + "-"))]
            for k in keys_to_remove_mt:
                del self.file_watcher._mtimes[k]

        # 6. アクティブファイルだった場合は新デフォルトに切り替え
        if self.recorder.output_path == t_path:
            self.recorder.output_path = self.recorder._get_default_output()

        self._send_json({"status": "ok", "deleted": deleted})

    def _extract_meeting(self):
        """POST /api/transcript/extract-meeting — タイムスタンプ範囲の行を会議ファイルへ移動"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            file_param = data.get("file", "")
            start_ts = data.get("start_ts", "")
            end_ts = data.get("end_ts", "")
            target = data.get("target", "new")
        except (json.JSONDecodeError, ValueError):
            self.send_error(400)
            return
        if not file_param or not start_ts or not end_ts:
            self.send_error(400)
            return

        output_dir = self.recorder._output_dir
        t_path = os.path.join(output_dir, os.path.basename(file_param))
        if not os.path.exists(t_path):
            self._send_json({"status": "error", "message": t("dash.transcript_not_found")})
            return

        try:
            with open(t_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
        except OSError:
            self._send_json({"status": "error", "message": t("dash.extract_meeting_error")})
            return

        # タイムスタンプ範囲内の行を抽出 / 残りを分離
        extracted = []
        remaining = []
        ts_pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]")
        for line in all_lines:
            m = ts_pattern.match(line)
            if m and start_ts <= m.group(1) <= end_ts:
                extracted.append(line)
            else:
                remaining.append(line)

        if not extracted:
            self._send_json({"status": "error", "message": t("dash.extract_meeting_no_lines")})
            return

        # 会議ファイル名の決定
        if target == "new":
            # transcript-YYYYMMDDHHMM.txt 形式
            meeting_ts = start_ts.replace("-", "").replace(" ", "").replace(":", "")[:12]
            meeting_name = f"transcript-{meeting_ts}.txt"
            meeting_path = os.path.join(output_dir, meeting_name)
            # 会議開始/終了マーカー付きで作成
            with open(meeting_path, "w", encoding="utf-8") as f:
                f.write(f"--- meeting start ---\n")
                f.writelines(extracted)
                f.write(f"--- meeting end ---\n")
        else:
            # 既存会議ファイルにマージ
            meeting_name = os.path.basename(target)
            meeting_path = os.path.join(output_dir, meeting_name)
            existing_lines = []
            if os.path.exists(meeting_path):
                with open(meeting_path, "r", encoding="utf-8") as f:
                    existing_lines = f.readlines()
            merged = self._merge_meeting_lines(existing_lines, extracted)
            with open(meeting_path, "w", encoding="utf-8") as f:
                f.writelines(merged)

        # 日次 transcript から抽出行を削除
        with open(t_path, "w", encoding="utf-8") as f:
            f.writelines(remaining)

        # 翻訳ファイルも同様に処理
        config = load_config()
        lang = config.get("translate_language", "ja")
        tr_name = os.path.basename(t_path).replace(".txt", f"-{lang}.txt")
        tr_path = os.path.join(output_dir, tr_name)
        meeting_tr_name = meeting_name.replace(".txt", f"-{lang}.txt")
        meeting_tr_path = os.path.join(output_dir, meeting_tr_name)
        if os.path.exists(tr_path):
            self._extract_translation_lines(
                tr_path, meeting_tr_path, start_ts, end_ts,
                is_new=(target == "new"),
            )

        # FileWatcher オフセットリセット
        for ftype, fpath in [("transcript", t_path), ("translation", tr_path)]:
            fkey = (ftype, fpath)
            if self.file_watcher and fkey in self.file_watcher._file_offsets:
                self.file_watcher._file_offsets[fkey] = self._get_file_size(fpath)

        # translate_offset リセット
        for p in [t_path, meeting_path]:
            offset_file = p + ".translate_offset"
            if os.path.exists(offset_file):
                try:
                    with open(offset_file, "w", encoding="utf-8") as f:
                        f.write(str(self._get_file_size(p)))
                except OSError:
                    pass

        self._send_json({
            "status": "ok",
            "message": t("dash.extract_meeting_success", name=meeting_name),
        })

    @staticmethod
    def _merge_meeting_lines(existing, new_lines):
        """既存会議ファイルの行と新しい行をタイムスタンプ順でマージ。マーカー行は保持。"""
        ts_pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]")
        marker_re = re.compile(r"^---\s.*\s---\s*$")

        # 既存からマーカー除去してデータ行のみ抽出
        data_lines = []
        for line in existing:
            if not marker_re.match(line.strip()):
                data_lines.append(line)
        # 新しい行を追加
        data_lines.extend(new_lines)

        # タイムスタンプでソート（タイムスタンプなし行はそのまま末尾）
        def sort_key(line):
            m = ts_pattern.match(line)
            return m.group(1) if m else "9999"

        data_lines.sort(key=sort_key)

        # マーカーを先頭・末尾に付与して返す
        result = ["--- meeting start ---\n"]
        result.extend(data_lines)
        result.append("--- meeting end ---\n")
        return result

    @staticmethod
    def _extract_translation_lines(tr_path, meeting_tr_path, start_ts, end_ts, is_new=True):
        """翻訳ファイルから対応行を会議翻訳ファイルへ移動/マージ"""
        ts_pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]")
        try:
            with open(tr_path, "r", encoding="utf-8") as f:
                all_lines = f.readlines()
        except OSError:
            return

        extracted = []
        remaining = []
        for line in all_lines:
            m = ts_pattern.match(line)
            if m and start_ts <= m.group(1) <= end_ts:
                extracted.append(line)
            else:
                remaining.append(line)

        if not extracted:
            return

        if is_new or not os.path.exists(meeting_tr_path):
            with open(meeting_tr_path, "w", encoding="utf-8") as f:
                f.writelines(extracted)
        else:
            # 既存会議翻訳とマージ
            with open(meeting_tr_path, "r", encoding="utf-8") as f:
                existing = f.readlines()
            merged = existing + extracted

            def sort_key(line):
                m = ts_pattern.match(line)
                return m.group(1) if m else "9999"
            merged.sort(key=sort_key)
            with open(meeting_tr_path, "w", encoding="utf-8") as f:
                f.writelines(merged)

        # 元翻訳ファイルから抽出行を削除
        with open(tr_path, "w", encoding="utf-8") as f:
            f.writelines(remaining)

    @staticmethod
    def _remove_lines_from_file(path, raw_lines):
        """ファイルから完全一致する行を各1件ずつ削除する"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            targets = collections.Counter(
                ln.rstrip("\n") + "\n" for ln in raw_lines
            )
            new_lines = []
            for line in lines:
                if targets.get(line, 0) > 0:
                    targets[line] -= 1
                    continue
                new_lines.append(line)
            if len(new_lines) == len(lines):
                return False
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return True
        except OSError:
            return False

    @staticmethod
    def _remove_lines_from_file_by_ts(path, timestamps):
        """ファイルからタイムスタンプ前方一致する行を各1件ずつ削除する"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            ts_counter = collections.Counter(timestamps)
            new_lines = []
            for line in lines:
                matched = False
                for ts, count in ts_counter.items():
                    if count > 0 and line.startswith(f"[{ts}]"):
                        ts_counter[ts] -= 1
                        matched = True
                        break
                if not matched:
                    new_lines.append(line)
            if len(new_lines) == len(lines):
                return False
            with open(path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            return True
        except OSError:
            return False

    @staticmethod
    def _get_file_size(path):
        """ファイルサイズを返す（存在しない場合は0）"""
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _serve_config(self):
        self._send_json(load_config())

    def _serve_models(self):
        """GET /api/models — api_endpoint から利用可能なモデル一覧を取得"""
        import urllib.request
        import urllib.error
        config = load_config()
        endpoint = config.get("api_endpoint")
        if not endpoint:
            self._send_json({"models": [], "error": "api_endpoint not configured"})
            return
        # /models エンドポイントの URL を構築
        models_url = endpoint.rstrip("/") + "/models"
        # API キー取得
        api_key = None
        api_key_env = config.get("api_key_env")
        if api_key_env:
            if _HAS_LLM_CLIENT:
                llm_load_dotenv()
            api_key = os.environ.get(api_key_env)
        try:
            req = urllib.request.Request(models_url)
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            model_ids = sorted(m["id"] for m in data.get("data", []))
            self._send_json({"models": model_ids})
        except Exception as e:
            logger.warning("モデル一覧取得失敗: %s", e)
            self._send_json({"models": [], "error": str(e)})

    def _save_config(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self.send_error(400)
            return
        # Merge with existing config to preserve unknown keys
        config = load_config()
        for key in list(DEFAULT_CONFIG.keys()):
            if key in data:
                config[key] = data[key]
        # whisper_beam_size は数値に変換
        if "whisper_beam_size" in config:
            try:
                config["whisper_beam_size"] = int(config["whisper_beam_size"])
            except (TypeError, ValueError):
                config["whisper_beam_size"] = DEFAULT_CONFIG["whisper_beam_size"]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
        logger.info("ダッシュボードから設定変更")
        self._send_json(config)

    def _serve_glossary(self):
        content = ""
        try:
            with open(GLOSSARY_FILE, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError:
            pass
        body = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _save_glossary(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
        except Exception:
            self.send_error(400)
            return
        with open(GLOSSARY_FILE, "w", encoding="utf-8") as f:
            f.write(body)
        logger.info("ダッシュボードから用語集を保存")
        self._send_json({"status": "ok"})



_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shadow-clerk Dashboard</title>
<style>
:root {
  --bg: #0d1117;
  --panel: #161b22;
  --header: #010409;
  --border: #30363d;
  --text: #c9d1d9;
  --muted: #8b949e;
  --accent: #58a6ff;
  --green: #3fb950;
  --red: #f85149;
  --yellow: #d29922;
  --purple: #d2a8ff;
  --self: #79c0ff;
  --other: #ffa657;
  --btn: #21262d;
  --btn-h: #30363d;
}
* { margin:0; padding:0; box-sizing:border-box; }
body {
  background: var(--bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  height: 100vh; display: flex; flex-direction: column; overflow: hidden;
}
header {
  background: var(--header); border-bottom: 1px solid var(--border);
  padding: 8px 16px; display: flex; align-items: center; gap: 12px;
  flex-shrink: 0; flex-wrap: wrap;
}
select, input[type=text] {
  background: var(--btn); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 5px 8px; font-size: 13px; outline: none;
}
select:focus, input:focus { border-color: var(--accent); }
button {
  background: var(--btn); color: var(--text); border: 1px solid var(--border);
  border-radius: 6px; padding: 5px 12px; font-size: 13px; cursor: pointer;
}
button:hover { background: var(--btn-h); }
.g { display:flex; gap:6px; align-items:center; }
.pri { background:#238636; border-color:#2ea043; }
.pri:hover { background:#2ea043; }
.dan { background:#da3633; border-color:#f85149; color:#fff; }
.dan:hover { background:#b62324; }
main {
  flex:1; display:flex; gap:1px; background:var(--border); min-height:0;
}
.panel {
  flex:1; background:var(--panel); display:flex; flex-direction:column; min-width:0;
}
.ph {
  padding:8px 12px; border-bottom:1px solid var(--border); font-size:13px;
  font-weight:600; color:var(--muted); flex-shrink:0; display:flex;
  justify-content:space-between; align-items:center;
}
.pc {
  flex:1; overflow-y:auto; padding:8px 12px;
  font-family: 'SF Mono','Monaco','Menlo','Consolas',monospace;
  font-size: 12px; line-height: 1.6;
}
.ln { margin-bottom:2px; word-break:break-word; display:flex; align-items:flex-start; }
.ln .ln-text { flex:1; }
.ln-cb { opacity:0; cursor:pointer; margin:3px 4px 0 0; flex-shrink:0; accent-color:var(--blue,#58a6ff); }
.ln:hover .ln-cb { opacity:0.6; }
.ln-cb:checked { opacity:1 !important; }
.sel-actions { display:none; align-items:center; gap:6px; font-size:12px; }
.sel-actions.show { display:flex; }
.sel-count { color:var(--muted); white-space:nowrap; }
.sel-actions button { min-width:auto; padding:2px 6px; font-size:12px; }
.del-lines-list { max-height:30vh; overflow-y:auto; padding:6px 8px; background:var(--bg); border-radius:4px; margin-bottom:12px; white-space:pre-wrap; line-height:1.6; font-size:12px; }
.extract-option { display:flex; align-items:center; gap:8px; padding:8px 0; cursor:pointer; font-size:13px; text-align:left; color:var(--text); }
.extract-option input[type=radio] { width:auto !important; margin:0; flex-shrink:0; }
.extract-option .eo-label { white-space:nowrap; }
.extract-option select { width:auto !important; flex:1; min-width:120px; margin-left:4px; padding:3px 6px; font-size:12px; }
.ts { color:var(--muted); }
.sp-s { color:var(--self); font-weight:600; }
.sp-o { color:var(--other); font-weight:600; }
.mk { color:var(--purple); font-weight:600; }
#logp {
  height:180px; flex-shrink:0; background:var(--panel);
  border-top:1px solid var(--border); display:flex; flex-direction:column;
}
#logc {
  flex:1; overflow-y:auto; padding:4px 12px;
  font-family: 'SF Mono','Monaco','Menlo','Consolas',monospace;
  font-size:11px; line-height:1.5; color:var(--muted);
}
.ll { white-space:pre-wrap; word-break:break-word; }
.ll.e { color:var(--red); }
.ll.w { color:var(--yellow); }
.interim {
  color: var(--muted); font-style: italic; opacity: 0.7;
  border-left: 2px solid var(--yellow); padding-left: 8px; margin-top: 4px;
}
#resp {
  display:none; background:var(--panel); border-bottom:1px solid var(--border);
  padding:8px 12px; font-size:13px; flex-shrink:0; max-height:120px; overflow-y:auto;
}
#resp.show { display:block; }
#resp .rh {
  display:flex; justify-content:space-between; align-items:center;
  color:var(--accent); font-weight:600; margin-bottom:4px;
}
#resp .rb {
  white-space:pre-wrap; word-break:break-word; color:var(--text);
  font-family:'SF Mono','Monaco','Menlo','Consolas',monospace; font-size:12px;
}
.toggle { font-size:12px; opacity:.7; cursor:pointer; padding:2px 6px; border:1px solid var(--border); border-radius:4px; background:transparent; color:var(--muted); }
.toggle:hover { opacity:1; }
.toggle.off { opacity:.4; text-decoration:line-through; }
.panel.hidden { display:none; }
#logp.collapsed #logc { display:none; }
#logp.collapsed { height:auto; }
.modal-overlay {
  display:none; position:fixed; inset:0; background:rgba(0,0,0,.6);
  z-index:100; justify-content:center; align-items:center;
}
.modal-overlay.open { display:flex; }
.modal {
  background:var(--panel); border:1px solid var(--border); border-radius:12px;
  width:676px; max-height:80vh; display:flex; flex-direction:column;
}
.modal-head {
  padding:12px 16px; border-bottom:1px solid var(--border);
  font-weight:600; display:flex; justify-content:space-between; align-items:center;
}
.modal-body {
  padding:16px; overflow-y:auto; flex:1;
  display:grid; grid-template-columns:140px 1fr; gap:8px 12px; align-items:center;
  font-size:13px;
}
.modal-body label { color:var(--muted); text-align:right; }
.modal-body input, .modal-body select, .modal-body textarea {
  background:var(--btn); color:var(--text); border:1px solid var(--border);
  border-radius:6px; padding:5px 8px; font-size:13px; width:100%; outline:none;
  font-family:inherit;
}
.modal-body input:focus, .modal-body select:focus, .modal-body textarea:focus {
  border-color:var(--accent);
}
.modal-body textarea { resize:vertical; min-height:60px; font-family:monospace; font-size:12px; }
.modal-body .cfg-section { grid-column:1/-1; font-weight:bold; font-size:13px; padding:8px 0 4px; border-bottom:1px solid var(--border); margin-top:4px; color:var(--text); }
.modal-body .cfg-section:first-child { margin-top:0; }
#glossaryTable th, #glossaryTable td {
  border:1px solid var(--border); padding:4px 6px;
}
#glossaryTable th {
  background:var(--bg); color:var(--muted); font-weight:600; font-size:12px;
  text-align:left; position:sticky; top:0; padding:2px 4px;
}
#glossaryTable th select { width:100%; }
#glossaryTable td { padding:0; }
#glossaryTable td input {
  border:none; border-radius:0; width:100%; padding:5px 6px; font-size:13px;
  background:transparent; color:var(--text); outline:none;
}
#glossaryTable td input:focus { background:rgba(100,100,255,0.08); }
#glossaryTable td.gl-del { width:30px; text-align:center; cursor:pointer; color:var(--muted); }
#glossaryTable td.gl-del:hover { color:var(--red,#e55); }
#customCmdTable th, #customCmdTable td {
  border:1px solid var(--border); padding:4px 6px;
}
#customCmdTable th {
  background:var(--bg); color:var(--muted); font-weight:600; font-size:12px;
  text-align:left; position:sticky; top:0; padding:4px 6px;
}
#customCmdTable td { padding:0; }
#customCmdTable td input {
  border:none; border-radius:0; width:100%; padding:5px 6px; font-size:13px;
  background:transparent; color:var(--text); outline:none;
}
#customCmdTable td input:focus { background:rgba(100,100,255,0.08); }
#customCmdTable td.gl-del { width:30px; text-align:center; cursor:pointer; color:var(--muted); }
#customCmdTable td.gl-del:hover { color:var(--red,#e55); }
.modal-foot {
  padding:12px 16px; border-top:1px solid var(--border);
  display:flex; justify-content:flex-end; gap:8px;
}
.modal-foot .saved { color:var(--green); font-size:13px; margin-right:auto; display:none; }
</style>
</head>
<body>
<header>
  <label for="langSel" style="font-size:12px;color:#aaa;margin-right:2px">{{i18n:dash.detect_language}}</label><select id="langSel" onchange="onLangChange(this.value)">
    <option value="auto">auto</option>
    <option value="ja">ja</option>
    <option value="en">en</option>
    <option value="zh">zh</option>
    <option value="ko">ko</option>
    <option value="fr">fr</option>
    <option value="de">de</option>
    <option value="es">es</option>
    <option value="pt">pt</option>
    <option value="ru">ru</option>
  </select>
  <span id="asrInfo" style="font-size:11px;color:#888"></span>
  <select id="fsel" onchange="onSel()"><option value="">...</option></select><button class="toggle" id="btnGoActive" onclick="goActive()" title="Go to active file" style="font-size:13px;padding:2px 4px">★</button>
  <div class="g">
    <button class="pri" id="btnMeeting" onclick="togMeeting()">{{i18n:dash.meeting_toggle_start}}</button>
    <button id="btnTranslate" onclick="togTranslate()">{{i18n:dash.translate_start}}</button>
    <button onclick="genSummary()">{{i18n:dash.summary}}</button>
    <button onclick="viewSummary()">{{i18n:dash.view_summary}}</button>
  </div>
  <div class="g" style="margin-left:auto">
    <button class="toggle" id="togTR" onclick="cyclePanel()">T|R</button>
    <button onclick="openGlossary()">{{i18n:dash.glossary}}</button>
    <button class="toggle" id="btnPTT" onclick="togPTT()" style="min-width:auto;padding:2px 6px;font-size:11px">PTT</button>
    <button onclick="openCustomCmds()">{{i18n:dash.custom_commands}}</button>
    <button onclick="openCfg()" title="{{i18n:dash.settings}}">⚙</button>
    <button onclick="openHelp()" title="{{i18n:dash.help}}">❓</button>
  </div>
</header>
<div id="resp"><div class="rh"><span>LLM Response</span><button class="toggle" onclick="hideResp()">&times;</button></div><div class="rb" id="respBody"></div></div>
<main>
  <div class="panel" id="pnlT">
    <div class="ph"><span>Transcript <button class="toggle" onclick="openFileDelModal()" title="{{i18n:dash.delete_file_title}}" style="font-size:12px;margin-left:2px">🗑</button></span><span style="display:flex;gap:4px;align-items:center"><div class="sel-actions" id="selActions"><span class="sel-count" id="selCount"></span><button onclick="openBulkDelModal()" id="btnBulkDel" title="{{i18n:dash.delete}}">🗑</button><button onclick="openExtractModal()" id="btnExtract" title="{{i18n:dash.extract_meeting_title}}" style="display:none">⏱</button><button class="toggle" onclick="deselectAll()">&times;</button></div><button class="toggle" id="btnMuteMic" onclick="togMute('mic')" title="{{i18n:dash.mute_mic}}">🎤</button><button class="toggle" id="btnMuteMonitor" onclick="togMute('monitor')" title="{{i18n:dash.mute_monitor}}">🔊</button><span id="tf" style="font-weight:normal"></span></span></div>
    <div class="pc" id="tp"></div>
  </div>
  <div class="panel" id="pnlR">
    <div class="ph"><span>Translation</span><span style="display:flex;gap:4px;align-items:center"><button class="toggle" onclick="regenTranslate()" title="{{i18n:dash.translate_regen}}">🔄</button><span id="rf" style="font-weight:normal"></span></span></div>
    <div class="pc" id="rp"></div>
  </div>
</main>
<div id="interim-area" style="display:none; border-top:1px solid var(--border); padding:4px 12px; flex-shrink:0;">
  <div id="interim-monitor" class="interim"></div>
  <div id="itp" class="interim"></div>
</div>
<div id="logp">
  <div class="ph" style="cursor:pointer" onclick="togLogs()"><span>Logs</span><span id="logArrow">▼</span></div>
  <div id="logc"></div>
</div>
<div class="modal-overlay" id="cfgModal" onclick="if(event.target===this)closeCfg()">
  <div class="modal">
    <div class="modal-head"><span>{{i18n:dash.settings_title}}</span><button onclick="closeCfg()">&times;</button></div>
    <div class="modal-body" id="cfgBody"></div>
    <div class="modal-foot">
      <span class="saved" id="cfgSaved">{{i18n:dash.saved}}</span>
      <button onclick="closeCfg()">{{i18n:dash.cancel}}</button>
      <button class="pri" onclick="saveCfg()">{{i18n:dash.save}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="glossaryModal" onclick="if(event.target===this)closeGlossary()">
  <div class="modal" style="max-width:700px;">
    <div class="modal-head"><span>{{i18n:dash.glossary_title}}</span><button onclick="closeGlossary()">&times;</button></div>
    <div class="modal-body" style="display:block;max-height:60vh;overflow-y:auto;">
      <table id="glossaryTable" style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr id="glossaryHead"></tr></thead>
        <tbody id="glossaryBody"></tbody>
      </table>
      <div style="margin-top:8px;">
        <button onclick="glossaryAddRow()" style="font-size:12px;">{{i18n:dash.add_row}}</button>
      </div>
    </div>
    <div class="modal-foot">
      <span class="saved" id="glossarySaved">{{i18n:dash.saved}}</span>
      <button onclick="closeGlossary()">{{i18n:dash.cancel}}</button>
      <button class="pri" onclick="saveGlossary()">{{i18n:dash.save}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="summaryModal" onclick="if(event.target===this)closeSummary()">
  <div class="modal" style="max-width:700px;">
    <div class="modal-head"><span id="summaryTitle">{{i18n:dash.summary_title}}</span><button onclick="closeSummary()">&times;</button></div>
    <div class="modal-body" style="display:block;max-height:60vh;overflow-y:auto;">
      <div id="summaryContent" style="white-space:pre-wrap;font-size:13px;line-height:1.6;"></div>
    </div>
    <div class="modal-foot">
      <button onclick="closeSummary()">{{i18n:dash.close}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="helpModal" onclick="if(event.target===this)closeHelp()">
  <div class="modal" style="max-width:600px;">
    <div class="modal-head"><span>{{i18n:dash.help_title}}</span><span style="margin-left:auto;margin-right:8px;"><a id="helpReadmeLink" href="https://github.com/edocode/shadow-clerk#readme" target="_blank" rel="noopener" style="font-size:13px;">README</a></span><button onclick="closeHelp()">&times;</button></div>
    <div class="modal-body" style="display:block;max-height:70vh;overflow-y:auto;font-size:13px;line-height:1.7;">
      <div id="helpContent" style="white-space:pre-wrap;"></div>
    </div>
    <div class="modal-foot">
      <button onclick="closeHelp()">{{i18n:dash.close}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="customCmdModal" onclick="if(event.target===this)closeCustomCmds()">
  <div class="modal" style="max-width:700px;">
    <div class="modal-head"><span>{{i18n:dash.custom_commands_title}}</span><button onclick="closeCustomCmds()">&times;</button></div>
    <div class="modal-body" style="display:block;max-height:60vh;overflow-y:auto;">
      <table id="customCmdTable" style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead><tr><th>{{i18n:dash.custom_cmd_pattern}}</th><th>{{i18n:dash.custom_cmd_action}}</th><th style="width:30px"></th></tr></thead>
        <tbody id="customCmdBody"></tbody>
      </table>
      <div style="margin-top:8px;">
        <button onclick="customCmdAddRow()" style="font-size:12px;">{{i18n:dash.add_row}}</button>
      </div>
      <div style="margin-top:12px;font-size:12px;color:var(--muted);line-height:1.5;">{{i18n:dash.custom_cmd_hint}}</div>
    </div>
    <div class="modal-foot">
      <span class="saved" id="customCmdSaved">{{i18n:dash.saved}}</span>
      <button onclick="closeCustomCmds()">{{i18n:dash.cancel}}</button>
      <button class="pri" onclick="saveCustomCmds()">{{i18n:dash.save}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="bulkDelModal" onclick="if(event.target===this)closeBulkDelModal()">
  <div class="modal" style="max-width:600px;">
    <div class="modal-head"><span>{{i18n:dash.bulk_delete_title}}</span><button onclick="closeBulkDelModal()">&times;</button></div>
    <div class="modal-body" style="display:block;max-height:50vh;overflow-y:auto;font-size:13px;">
      <div id="bulkDelRangeOpt" style="display:none;margin-bottom:8px;">
        <label class="extract-option"><input type="radio" name="bulkDelMode" value="range"><span class="eo-label">{{i18n:dash.bulk_delete_range}}</span></label>
        <label class="extract-option"><input type="radio" name="bulkDelMode" value="selected"><span class="eo-label">{{i18n:dash.bulk_delete_selected}}</span></label>
      </div>
      <div style="margin-bottom:8px;font-weight:600;color:var(--muted);">{{i18n:dash.delete_line_transcript}}</div>
      <div class="del-lines-list" id="bulkDelTranscript"></div>
      <div style="margin-bottom:8px;font-weight:600;color:var(--muted);">{{i18n:dash.delete_line_translation}}</div>
      <div class="del-lines-list" id="bulkDelTranslation" style="color:var(--muted);"></div>
    </div>
    <div class="modal-foot">
      <button onclick="closeBulkDelModal()">{{i18n:dash.cancel}}</button>
      <button class="dan" onclick="doBulkDel()">{{i18n:dash.delete}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="extractModal" onclick="if(event.target===this)closeExtractModal()">
  <div class="modal" style="max-width:500px;">
    <div class="modal-head"><span>{{i18n:dash.extract_meeting_title}}</span><button onclick="closeExtractModal()">&times;</button></div>
    <div class="modal-body" style="display:block;font-size:13px;">
      <div id="extractRange" style="margin-bottom:8px;color:var(--muted);"></div>
      <div id="extractLineCount" style="margin-bottom:12px;color:var(--muted);"></div>
      <label class="extract-option"><input type="radio" name="extractTarget" value="new" checked><span class="eo-label">{{i18n:dash.extract_meeting_new}}</span></label>
      <label class="extract-option"><input type="radio" name="extractTarget" value="existing"><span class="eo-label">{{i18n:dash.extract_meeting_existing}}</span><select id="extractExistingSel" disabled onclick="event.stopPropagation()"></select></label>
    </div>
    <div class="modal-foot">
      <button onclick="closeExtractModal()">{{i18n:dash.cancel}}</button>
      <button class="pri" onclick="doExtractMeeting()">{{i18n:dash.extract_meeting_create}}</button>
    </div>
  </div>
</div>
<div class="modal-overlay" id="fileDelModal" onclick="if(event.target===this)closeFileDelModal()">
  <div class="modal" style="max-width:500px;">
    <div class="modal-head"><span>{{i18n:dash.delete_file_title}}</span><button onclick="closeFileDelModal()">&times;</button></div>
    <div class="modal-body" style="display:block;font-size:13px;">
      <div style="margin-bottom:8px;color:var(--muted);">{{i18n:dash.delete_file_desc}}</div>
      <div class="del-lines-list" id="fileDelList"></div>
    </div>
    <div class="modal-foot">
      <button onclick="closeFileDelModal()">{{i18n:dash.cancel}}</button>
      <button class="dan" onclick="doFileDel()">{{i18n:dash.delete}}</button>
    </div>
  </div>
</div>
<script>
/*I18N_JSON*/
let curFile='', activeFile='';
let meetingActive=false, translating=false, muteMic=false, muteMonitor=false, pttActive=false;
let panelMode=0; // 0=T|R, 1=T, 2=R
const as={tp:true,rp:true,logc:true};
['tp','rp','logc'].forEach(id=>{
  document.getElementById(id).addEventListener('scroll',function(){
    as[id]=this.scrollTop+this.clientHeight>=this.scrollHeight-30;
  });
});
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function escAttr(s){return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function fmtLine(t){
  if(/^---\\s.*\\s---$/.test(t)) return '<div class="ln"><span class="mk">'+esc(t)+'</span></div>';
  const m=t.match(/^\\[(\\d{4}-\\d{2}-\\d{2}\\s\\d{2}:\\d{2}:\\d{2})\\]\\s\\[([^\\]]+)\\]\\s(.*)$/);
  if(m){const sp=m[2],mic=I18N['speaker.mic']||'自分';const c=(sp===mic||sp==='自分')?'sp-s':'sp-o';
    const dl=sp===mic?mic:sp==='自分'?mic:(sp===(I18N['speaker.monitor']||'相手')||sp==='相手')?(I18N['speaker.monitor']||'相手'):sp;
    return '<div class="ln" data-ts="'+escAttr(m[1])+'" data-raw="'+escAttr(t)+'"><span class="ln-text"><span class="ts">['+esc(m[1])+']</span> <span class="'+c+'">['+esc(dl)+']</span> '+esc(m[3])+'</span></div>';}
  return '<div class="ln" data-raw="'+escAttr(t)+'"><span class="ln-text">'+esc(t)+'</span></div>';
}
function fmtTranscriptLine(t){
  if(/^---\\s.*\\s---$/.test(t)) return '<div class="ln"><span class="mk">'+esc(t)+'</span></div>';
  const m=t.match(/^\\[(\\d{4}-\\d{2}-\\d{2}\\s\\d{2}:\\d{2}:\\d{2})\\]\\s\\[([^\\]]+)\\]\\s(.*)$/);
  if(m){const sp=m[2],mic=I18N['speaker.mic']||'自分';const c=(sp===mic||sp==='自分')?'sp-s':'sp-o';
    const dl=sp===mic?mic:sp==='自分'?mic:(sp===(I18N['speaker.monitor']||'相手')||sp==='相手')?(I18N['speaker.monitor']||'相手'):sp;
    return '<div class="ln" data-ts="'+escAttr(m[1])+'" data-raw="'+escAttr(t)+'"><input type="checkbox" class="ln-cb" onchange="onSelChange()"><span class="ln-text"><span class="ts">['+esc(m[1])+']</span> <span class="'+c+'">['+esc(dl)+']</span> '+esc(m[3])+'</span></div>';}
  return '<div class="ln" data-raw="'+escAttr(t)+'"><span class="ln-text">'+esc(t)+'</span></div>';
}
function addLines(id,text,fmt){
  const el=document.getElementById(id);
  text.split('\\n').forEach(l=>{if(l.trim())el.insertAdjacentHTML('beforeend',fmt(l));});
  if(as[id])el.scrollTop=el.scrollHeight;
}
/* --- Selection management --- */
function getSelectedLines(){return Array.from(document.querySelectorAll('#tp .ln-cb:checked')).map(cb=>cb.closest('.ln'));}
function onSelChange(){
  const sel=getSelectedLines();const n=sel.length;
  const bar=document.getElementById('selActions');
  const cnt=document.getElementById('selCount');
  const btnExt=document.getElementById('btnExtract');
  if(n>0){
    bar.classList.add('show');
    cnt.textContent=(I18N['dash.selected_count']||'{count} selected').replace('{count}',n);
    btnExt.style.display=(n===2)?'':'none';
  }else{bar.classList.remove('show');btnExt.style.display='none';}
}
function deselectAll(){
  document.querySelectorAll('#tp .ln-cb:checked').forEach(cb=>{cb.checked=false;});
  onSelChange();
}
/* --- Bulk delete modal --- */
function openBulkDelModal(){
  const sel=getSelectedLines();if(!sel.length)return;
  const tDiv=document.getElementById('bulkDelTranscript');
  const rDiv=document.getElementById('bulkDelTranslation');
  tDiv.innerHTML='';rDiv.innerHTML='';
  sel.forEach(ln=>{
    const d=document.createElement('div');d.textContent=ln.dataset.raw||ln.textContent;tDiv.appendChild(d);
    const ts=ln.dataset.ts||'';
    if(ts){
      const rp=document.getElementById('rp');
      const els=rp.querySelectorAll('.ln[data-ts]');
      for(const el of els){if(el.dataset.ts===ts){const rd=document.createElement('div');rd.textContent=el.dataset.raw||el.textContent;rDiv.appendChild(rd);break;}}
    }
  });
  if(!rDiv.children.length){const d=document.createElement('div');d.textContent='—';rDiv.appendChild(d);}
  const rangeOpt=document.getElementById('bulkDelRangeOpt');
  if(sel.length===2){rangeOpt.style.display='';document.querySelector('input[name="bulkDelMode"][value="range"]').checked=true;}
  else{rangeOpt.style.display='none';}
  document.getElementById('bulkDelModal').classList.add('open');
}
function closeBulkDelModal(){document.getElementById('bulkDelModal').classList.remove('open');
  const r=document.querySelector('input[name="bulkDelMode"][value="range"]');if(r)r.checked=true;}
async function doBulkDel(){
  const sel=getSelectedLines();if(!sel.length)return;
  const mode=document.querySelector('input[name="bulkDelMode"]:checked');
  const isRange=mode&&mode.value==='range'&&sel.length===2;
  let targets=sel;
  if(isRange){
    const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
    const tsMin=ts0<ts1?ts0:ts1;const tsMax=ts0<ts1?ts1:ts0;
    const allLn=document.querySelectorAll('#tp .ln[data-ts]');
    targets=Array.from(allLn).filter(ln=>{const ts=ln.dataset.ts||'';return ts>=tsMin&&ts<=tsMax;});
  }
  const lines=targets.map(ln=>ln.dataset.raw||'').filter(Boolean);
  const file=document.getElementById('tf').textContent;
  try{
    const r=await fetch('/api/transcript/delete',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({lines:lines,file:file})});
    const d=await r.json();
    if(d.status==='ok'){
      targets.forEach(ln=>{
        const ts=ln.dataset.ts||'';
        if(ts){const rp=document.getElementById('rp');const els=rp.querySelectorAll('.ln[data-ts]');
          for(const el of els){if(el.dataset.ts===ts){el.remove();break;}}}
        ln.remove();
      });
      deselectAll();closeBulkDelModal();
    }else{alert(I18N['dash.delete_error']||'Failed to delete');}
  }catch(e){alert(I18N['dash.delete_error']||'Failed to delete');}
}
/* --- File delete modal --- */
function openFileDelModal(){
  if(!curFile)return;
  const stem=curFile.replace(/\.txt$/,'');
  const date=stem.replace('transcript-','');
  const files=[curFile];
  const sel=document.getElementById('fsel');
  for(const opt of sel.options){
    const v=opt.value;
    if(v!==curFile && v.startsWith(stem+'-') && v.endsWith('.txt'))files.push(v);
  }
  files.push('summary-'+date+'.md');
  files.push(curFile+'.translate_offset');
  const list=document.getElementById('fileDelList');
  list.innerHTML='';
  files.forEach(f=>{const d=document.createElement('div');d.textContent=f;list.appendChild(d);});
  document.getElementById('fileDelModal').classList.add('open');
}
function closeFileDelModal(){document.getElementById('fileDelModal').classList.remove('open');}
async function doFileDel(){
  if(!curFile)return;
  try{
    const r=await fetch('/api/transcript/delete-file',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({file:curFile})});
    const d=await r.json();
    if(d.status==='ok'){closeFileDelModal();loadFiles();}
    else{alert(I18N['dash.delete_error']||'Failed to delete');}
  }catch(e){alert(I18N['dash.delete_error']||'Failed to delete');}
}
/* --- Extract meeting modal --- */
function openExtractModal(){
  const sel=getSelectedLines();if(sel.length!==2)return;
  const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
  if(!ts0||!ts1)return;
  const startTs=ts0<ts1?ts0:ts1;const endTs=ts0<ts1?ts1:ts0;
  document.getElementById('extractRange').textContent=
    (I18N['dash.extract_meeting_range']||'Range: {start} - {end}').replace('{start}',startTs).replace('{end}',endTs);
  // タイムスタンプ範囲内の行数カウント
  const allLns=document.querySelectorAll('#tp .ln[data-ts]');
  let cnt=0;
  allLns.forEach(ln=>{const t=ln.dataset.ts;if(t>=startTs&&t<=endTs)cnt++;});
  document.getElementById('extractLineCount').textContent=
    (I18N['dash.extract_meeting_lines']||'{count} lines selected').replace('{count}',cnt);
  // 既存会議ファイルドロップダウン
  const fsel=document.getElementById('fsel');
  const eSel=document.getElementById('extractExistingSel');
  eSel.innerHTML='';
  Array.from(fsel.options).forEach(o=>{
    if(o.value&&/^transcript-\\d{12}\\.txt$/.test(o.value)){
      const opt=document.createElement('option');opt.value=o.value;opt.textContent=o.value;eSel.appendChild(opt);
    }
  });
  // ラジオ初期化
  document.querySelector('input[name="extractTarget"][value="new"]').checked=true;
  eSel.disabled=true;
  document.querySelectorAll('input[name="extractTarget"]').forEach(r=>{
    r.onchange=()=>{eSel.disabled=(r.value!=='existing'||!r.checked);};
  });
  document.getElementById('extractModal').classList.add('open');
}
function closeExtractModal(){document.getElementById('extractModal').classList.remove('open');}
async function doExtractMeeting(){
  const sel=getSelectedLines();if(sel.length!==2)return;
  const ts0=sel[0].dataset.ts||'';const ts1=sel[1].dataset.ts||'';
  const startTs=ts0<ts1?ts0:ts1;const endTs=ts0<ts1?ts1:ts0;
  const file=document.getElementById('tf').textContent;
  const rad=document.querySelector('input[name="extractTarget"]:checked');
  let target='new';
  if(rad&&rad.value==='existing'){
    const eSel=document.getElementById('extractExistingSel');
    target=eSel.value||'new';
  }
  try{
    const r=await fetch('/api/transcript/extract-meeting',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({file:file,start_ts:startTs,end_ts:endTs,target:target})});
    const d=await r.json();
    if(d.status==='ok'){
      deselectAll();closeExtractModal();
      loadFiles();loadT(curFile);loadR(curFile);
      if(d.message)alert(d.message);
    }else{alert(d.message||I18N['dash.extract_meeting_error']||'Failed');}
  }catch(e){alert(I18N['dash.extract_meeting_error']||'Failed');}
}
/* --- Meeting toggle --- */
function updateMeetingBtn(session){
  meetingActive=!!session;
  const btn=document.getElementById('btnMeeting');
  if(meetingActive){
    btn.textContent='\\u25A0 '+I18N['dash.meeting_toggle_end'];
    btn.className='dan';
  }else{
    btn.textContent='\\u25B6 '+I18N['dash.meeting_toggle_start'];
    btn.className='pri';
  }
}
function togMeeting(){cmd(meetingActive?'end_meeting':'start_meeting');}
/* --- Translation toggle --- */
function updateTranslateBtn(active){
  translating=active;
  const btn=document.getElementById('btnTranslate');
  if(translating){
    btn.textContent='\\u25A0 '+I18N['dash.translate_stop'];
    btn.className='dan';
  }else{
    btn.textContent='\\u25B6 '+I18N['dash.translate_start'];
    btn.className='pri';
  }
}
async function togTranslate(){
  if(translating){cmd('translate_stop');updateTranslateBtn(false);return;}
  cmd('translate_start');updateTranslateBtn(true);
}
async function regenTranslate(){
  if(!confirm(I18N['dash.translate_regen_confirm']))return;
  cmd('translate_regenerate');
  updateTranslateBtn(true);
}

/* --- Mute toggles --- */
function updateMuteBtn(type,muted){
  const btn=document.getElementById(type==='mic'?'btnMuteMic':'btnMuteMonitor');
  if(muted){btn.classList.add('off');btn.title=I18N[type==='mic'?'dash.unmute_mic':'dash.unmute_monitor'];}
  else{btn.classList.remove('off');btn.title=I18N[type==='mic'?'dash.mute_mic':'dash.mute_monitor'];}
}
function togMute(type){
  if(type==='mic'){muteMic=!muteMic;cmd(muteMic?'mute_mic':'unmute_mic');updateMuteBtn('mic',muteMic);}
  else{muteMonitor=!muteMonitor;cmd(muteMonitor?'mute_monitor':'unmute_monitor');updateMuteBtn('monitor',muteMonitor);}
}
/* --- PTT toggle --- */
function updatePTT(active){
  pttActive=active;
  const btn=document.getElementById('btnPTT');
  if(active){btn.style.background='var(--red)';btn.style.color='#fff';}
  else{btn.style.background='';btn.style.color='';}
}
function togPTT(){
  pttActive=!pttActive;
  cmd(pttActive?'ptt_on':'ptt_off');
  updatePTT(pttActive);
}
/* --- Panel cycling (T|R -> T -> R) --- */
function cyclePanel(){
  panelMode=(panelMode+1)%3;
  const t=document.getElementById('pnlT'),r=document.getElementById('pnlR'),btn=document.getElementById('togTR');
  if(panelMode===0){t.classList.remove('hidden');r.classList.remove('hidden');btn.textContent='T|R';}
  else if(panelMode===1){t.classList.remove('hidden');r.classList.add('hidden');btn.textContent='T';}
  else{t.classList.add('hidden');r.classList.remove('hidden');btn.textContent='R';}
}
/* --- Logs toggle --- */
function togLogs(){
  const lp=document.getElementById('logp'),arr=document.getElementById('logArrow');
  lp.classList.toggle('collapsed');
  arr.textContent=lp.classList.contains('collapsed')?'▲':'▼';
}
/* --- Status fetch --- */
async function fetchStatus(){
  try{const d=await(await fetch('/api/status')).json();
    const s=document.getElementById('langSel');if(s&&d.language)s.value=d.language;
    updateMeetingBtn(d.session);
    updateTranslateBtn(d.translating);
    muteMic=d.mute_mic;muteMonitor=d.mute_monitor;
    updateMuteBtn('mic',muteMic);updateMuteBtn('monitor',muteMonitor);
    if(d.ptt!==undefined)updatePTT(d.ptt);
    const ai=document.getElementById('asrInfo');
    if(ai&&d.asr_backend){ai.textContent=d.asr_backend==='whisper'?'Whisper: '+d.asr_model_id:d.asr_backend;}
  }catch(e){}
}
const es=new EventSource('/api/events');
es.addEventListener('transcript',e=>{
  const d=JSON.parse(e.data);
  if(!curFile||curFile===d.file){addLines('tp',d.diff,fmtTranscriptLine);document.getElementById('tf').textContent=d.file;}
});
es.addEventListener('translation',e=>{
  const d=JSON.parse(e.data);addLines('rp',d.diff,fmtLine);document.getElementById('rf').textContent=d.file;
});
es.addEventListener('log',e=>{
  const d=JSON.parse(e.data);const el=document.getElementById('logc');
  const c=d.line.includes('ERROR')?'e':d.line.includes('WARNING')?'w':'';
  el.insertAdjacentHTML('beforeend','<div class="ll '+c+'">'+esc(d.line)+'</div>');
  if(as.logc)el.scrollTop=el.scrollHeight;
});
es.addEventListener('session',e=>{
  try{const d=JSON.parse(e.data);updateMeetingBtn(d.content||null);}catch(ex){}
  loadFiles();
});
es.addEventListener('ptt',e=>{
  try{const d=JSON.parse(e.data);updatePTT(d.active);}catch(ex){}
});
es.addEventListener('interim_transcript',e=>{
  const d=JSON.parse(e.data);
  const el=document.getElementById('interim-monitor');
  if(el){el.innerHTML='<span class="sp-o">['+esc(d.speaker)+']</span> '+esc(d.text);}
  document.getElementById('interim-area').style.display='block';
});
es.addEventListener('interim_translation',e=>{
  const d=JSON.parse(e.data);
  const el=document.getElementById('itp');
  if(el){el.innerHTML='<span class="sp-o">['+esc(d.speaker)+']</span> '+esc(d.translated);}
  document.getElementById('interim-area').style.display='block';
});
es.addEventListener('interim_clear',e=>{
  const el=document.getElementById('interim-monitor');
  if(el)el.innerHTML='';
  document.getElementById('interim-area').style.display='none';
  const itp=document.getElementById('itp');
  if(itp)itp.innerHTML='';
});
async function loadFiles(){
  try{const r=await fetch('/api/files'),d=await r.json(),s=document.getElementById('fsel'),p=s.value;
  s.innerHTML='';activeFile=d.active||'';
  d.files.forEach(f=>{const o=document.createElement('option');o.value=f;
    o.textContent=f+(f===d.active?' ★':'');s.appendChild(o);});
  s.value=(p&&d.files.includes(p))?p:(d.active||'');curFile=s.value;}catch(e){}
}
async function loadT(file){
  try{const u=file?'/api/transcript?file='+encodeURIComponent(file):'/api/transcript';
  const d=await(await fetch(u)).json(),el=document.getElementById('tp');el.innerHTML='';
  d.lines.forEach(l=>el.insertAdjacentHTML('beforeend',fmtTranscriptLine(l)));
  document.getElementById('tf').textContent=d.file;el.scrollTop=el.scrollHeight;}catch(e){}
}
async function loadR(file){
  try{const u=file?'/api/translation?file='+encodeURIComponent(file):'/api/translation';
  const d=await(await fetch(u)).json(),el=document.getElementById('rp');el.innerHTML='';
  d.lines.forEach(l=>el.insertAdjacentHTML('beforeend',fmtLine(l)));
  document.getElementById('rf').textContent=d.file;el.scrollTop=el.scrollHeight;}catch(e){}
}
async function loadLogs(){
  try{const d=await(await fetch('/api/logs')).json(),el=document.getElementById('logc');
  d.lines.forEach(l=>{const c=l.includes('ERROR')?'e':l.includes('WARNING')?'w':'';
    el.insertAdjacentHTML('beforeend','<div class="ll '+c+'">'+esc(l)+'</div>');});
  el.scrollTop=el.scrollHeight;}catch(e){}
}
function onSel(){deselectAll();curFile=document.getElementById('fsel').value;loadT(curFile);loadR(curFile);}
function goActive(){if(!activeFile)return;const s=document.getElementById('fsel');s.value=activeFile;onSel();}
async function cmd(c){try{await fetch('/api/command',{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify({command:c})});}catch(e){}}
function onLangChange(l){cmd(l==='auto'?'unset_language':'set_language '+l);}
fetchStatus();
es.addEventListener('response',e=>{
  const d=JSON.parse(e.data);if(d.content){
    document.getElementById('respBody').textContent=d.content;
    document.getElementById('resp').classList.add('show');}
});
es.addEventListener('alert',e=>{
  const d=JSON.parse(e.data);if(d.message){alert(d.message);}
});
function hideResp(){document.getElementById('resp').classList.remove('show');}
loadFiles();loadT('');loadR('');loadLogs();setInterval(loadFiles,10000);
const LANG_OPTS=['ja','en','zh','ko','fr','de','es','pt','ru'];
const CFG_FIELDS=[
  {type:'section',label:I18N['cfg.section.general']},
  {key:'ui_language',label:I18N['cfg.ui_language'],type:'select',opts:['ja','en']},
  {key:'output_directory',label:I18N['cfg.output_directory'],type:'text',ph:I18N['cfg.output_directory_ph']},
  {type:'section',label:I18N['cfg.section.transcription']},
  {key:'default_language',label:I18N['cfg.default_language'],type:'select',opts:['auto',...LANG_OPTS]},
  {key:'default_model',label:I18N['cfg.default_model'],type:'select',opts:['tiny','base','small','medium','large-v3']},
  {key:'japanese_asr_model',label:I18N['cfg.japanese_asr_model'],type:'select',opts:['default','kotoba-whisper','reazonspeech-k2']},
  {key:'initial_prompt',label:I18N['cfg.initial_prompt'],type:'text',ph:I18N['cfg.initial_prompt_ph']},
  {key:'whisper_beam_size',label:I18N['cfg.whisper_beam_size'],type:'select',opts:['1','2','3','5']},
  {key:'whisper_compute_type',label:I18N['cfg.whisper_compute_type'],type:'select',opts:['int8','float16','float32']},
  {key:'whisper_device',label:I18N['cfg.whisper_device'],type:'select',opts:['cpu','cuda']},
  {key:'interim_transcription',label:I18N['cfg.interim_transcription'],type:'bool'},
  {key:'interim_model',label:I18N['cfg.interim_model'],type:'select',opts:['tiny','base','small','medium']},
  {key:'interim_japanese_asr_model',label:I18N['cfg.interim_japanese_asr_model'],type:'select',opts:['default','kotoba-whisper','reazonspeech-k2']},
  {key:'voice_command_key',label:I18N['cfg.voice_command_key'],type:'select',opts:['menu','f23','ctrl_r','ctrl_l','alt_r','alt_l','shift_r','shift_l']},
  {type:'section',label:I18N['cfg.section.translation']},
  {key:'translate_language',label:I18N['cfg.translate_language'],type:'select',opts:LANG_OPTS},
  {key:'auto_translate',label:I18N['cfg.auto_translate'],type:'bool'},
  {key:'translation_provider',label:I18N['cfg.translation_provider'],type:'select',opts:['','claude','api','libretranslate']},
  {key:'libretranslate_endpoint',label:I18N['cfg.libretranslate_endpoint'],type:'text',ph:'http://localhost:5000'},
  {key:'libretranslate_api_key',label:I18N['cfg.libretranslate_api_key'],type:'text',ph:''},
  {key:'libretranslate_spell_check',label:I18N['cfg.libretranslate_spell_check'],type:'bool'},
  {key:'spell_check_model',label:I18N['cfg.spell_check_model'],type:'text',ph:'sonoisa/t5-base-japanese-spell-checker'},
  {type:'section',label:I18N['cfg.section.summary']},
  {key:'auto_summary',label:I18N['cfg.auto_summary'],type:'bool'},
  {key:'summary_source',label:I18N['cfg.summary_source'],type:'select',opts:['transcript','translate']},
  {type:'section',label:I18N['cfg.section.api']},
  {key:'llm_provider',label:I18N['cfg.llm_provider'],type:'select',opts:['claude','api']},
  {key:'api_endpoint',label:I18N['cfg.api_endpoint'],type:'text',ph:'https://...'},
  {key:'api_model',label:I18N['cfg.api_model'],type:'api_model'},
  {key:'api_key_env',label:I18N['cfg.api_key_env'],type:'text',ph:'SHADOW_CLERK_API_KEY'},
];
let cfgData={};
async function openCfg(){
  try{cfgData=await(await fetch('/api/config')).json();}catch(e){return;}
  const b=document.getElementById('cfgBody');b.innerHTML='';
  CFG_FIELDS.forEach(f=>{
    if(f.type==='section'){
      const h=document.createElement('div');h.className='cfg-section';h.textContent=f.label;b.appendChild(h);return;
    }
    const lbl=document.createElement('label');lbl.textContent=f.label;b.appendChild(lbl);
    let el;const v=cfgData[f.key];
    if(f.type==='bool'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      ['true','false'].forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      el.value=v?'true':'false';
    }else if(f.type==='select'){
      el=document.createElement('select');el.id='cfg_'+f.key;
      f.opts.forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;el.appendChild(op);});
      if(v!==null&&v!==undefined)el.value=String(v);
    }else if(f.type==='api_model'){
      el=document.createElement('div');el.style.display='flex';el.style.gap='4px';el.style.alignItems='center';el.style.width='100%';
      const sel=document.createElement('select');sel.id='cfg_'+f.key;sel.style.flex='1';sel.style.width='auto';
      const cur=document.createElement('option');cur.value=(v===null||v===undefined)?'':String(v);
      cur.textContent=(v===null||v===undefined)?'(not set)':String(v);sel.appendChild(cur);
      el.appendChild(sel);
      const btn=document.createElement('button');btn.textContent='\\u21BB';btn.title='Fetch models';
      btn.style.cssText='padding:2px 8px;cursor:pointer;width:auto;flex-shrink:0;';
      btn.onclick=async()=>{
        btn.disabled=true;btn.textContent='...';
        try{const d=await(await fetch('/api/models')).json();
          if(d.error){alert(d.error);return;}
          const prev=sel.value;sel.innerHTML='';
          const empty=document.createElement('option');empty.value='';empty.textContent='(not set)';sel.appendChild(empty);
          d.models.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);});
          if(prev)sel.value=prev;
        }catch(e){alert('Failed to fetch models');}
        finally{btn.disabled=false;btn.textContent='\\u21BB';}
      };el.appendChild(btn);
    }else if(f.type==='json'){
      el=document.createElement('textarea');el.id='cfg_'+f.key;
      el.value=JSON.stringify(v||[],null,2);
    }else{
      el=document.createElement('input');el.type='text';el.id='cfg_'+f.key;
      el.value=(v===null||v===undefined)?'':String(v);
      if(f.ph)el.placeholder=f.ph;
    }
    b.appendChild(el);
  });
  document.getElementById('cfgSaved').style.display='none';
  const jaEl=document.getElementById('cfg_japanese_asr_model');
  if(jaEl)jaEl.onchange=updateCfgDisabled;
  const ijaEl=document.getElementById('cfg_interim_japanese_asr_model');
  if(ijaEl)ijaEl.onchange=updateCfgDisabled;
  updateCfgDisabled();
  document.getElementById('cfgModal').classList.add('open');
  if(cfgData.api_endpoint){fetchApiModels();}
}
async function fetchApiModels(){
  const sel=document.getElementById('cfg_api_model');if(!sel)return;
  try{const d=await(await fetch('/api/models')).json();
    if(d.error||!d.models.length)return;
    const prev=sel.value;sel.innerHTML='';
    const empty=document.createElement('option');empty.value='';empty.textContent='(not set)';sel.appendChild(empty);
    d.models.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;sel.appendChild(o);});
    if(prev)sel.value=prev;
  }catch(e){}
}
function closeCfg(){document.getElementById('cfgModal').classList.remove('open');}
async function saveCfg(){
  const d={};
  CFG_FIELDS.forEach(f=>{
    const el=document.getElementById('cfg_'+f.key);if(!el)return;
    if(f.type==='bool'){d[f.key]=el.value==='true';}
    else if(f.type==='json'){try{d[f.key]=JSON.parse(el.value);}catch(e){d[f.key]=cfgData[f.key];}}
    else if(f.type==='select'){const sv=el.value;d[f.key]=(sv===''||(sv==='auto'&&f.key==='default_language'))?null:sv;}
    else{const v=el.value.trim();d[f.key]=(v===''||v==='null')?null:v;}
  });
  const langChanged=d.ui_language&&d.ui_language!==cfgData.ui_language;
  try{await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(d)});
    if(langChanged){location.reload();return;}
    const s=document.getElementById('cfgSaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
function updateCfgDisabled(){
  const ja=document.getElementById('cfg_japanese_asr_model');
  const ija=document.getElementById('cfg_interim_japanese_asr_model');
  const isK2=ja&&ja.value==='reazonspeech-k2';
  const iIsK2=ija&&ija.value==='reazonspeech-k2';
  ['default_model','whisper_beam_size','whisper_compute_type','initial_prompt'].forEach(k=>{
    const el=document.getElementById('cfg_'+k);
    if(el){el.disabled=isK2;el.style.opacity=isK2?'0.5':'1';}
  });
  const im=document.getElementById('cfg_interim_model');
  if(im){im.disabled=iIsK2;im.style.opacity=iIsK2?'0.5':'1';}
}
const GL_COL_OPTS=[...LANG_OPTS,'reading','note'];
let glossaryCols=[];
function glossaryAddRow(vals){
  const tb=document.getElementById('glossaryBody');
  const tr=document.createElement('tr');
  glossaryCols.forEach((c,i)=>{
    const td=document.createElement('td');
    const inp=document.createElement('input');
    inp.type='text'; inp.value=(vals&&vals[i])||'';
    inp.placeholder=c;
    td.appendChild(inp); tr.appendChild(td);
  });
  const del=document.createElement('td');
  del.className='gl-del'; del.textContent='\u00d7';
  del.onclick=()=>tr.remove();
  tr.appendChild(del); tb.appendChild(tr);
  return tr;
}
function glossaryMakeHeadSel(val){
  const sel=document.createElement('select');
  sel.style.cssText='background:transparent;color:var(--muted);border:none;font-weight:600;font-size:12px;cursor:pointer;padding:2px;';
  GL_COL_OPTS.forEach(o=>{const op=document.createElement('option');op.value=o;op.textContent=o;sel.appendChild(op);});
  sel.value=val;
  sel.onchange=()=>{const idx=[...sel.closest('tr').children].indexOf(sel.parentElement);glossaryCols[idx]=sel.value;};
  return sel;
}
async function openGlossary(){
  let text='';
  try{const r=await fetch('/api/glossary');text=await r.text();}catch(e){}
  const lines=text.split('\\n').filter(l=>l.trim()&&!l.startsWith('#'));
  glossaryCols=(lines.length>0)?lines[0].split('\\t'):['ja','en','reading','note'];
  const head=document.getElementById('glossaryHead');
  head.innerHTML='';
  glossaryCols.forEach(c=>{const th=document.createElement('th');th.appendChild(glossaryMakeHeadSel(c));head.appendChild(th);});
  const thDel=document.createElement('th');thDel.style.width='30px';head.appendChild(thDel);
  const tb=document.getElementById('glossaryBody');
  tb.innerHTML='';
  for(let i=1;i<lines.length;i++){
    const cols=lines[i].split('\\t');
    glossaryAddRow(cols);
  }
  if(lines.length<=1)glossaryAddRow();
  document.getElementById('glossarySaved').style.display='none';
  document.getElementById('glossaryModal').classList.add('open');
}
function closeGlossary(){document.getElementById('glossaryModal').classList.remove('open');}
async function saveGlossary(){
  glossaryCols=[...document.querySelectorAll('#glossaryHead select')].map(s=>s.value);
  const rows=[glossaryCols.join('\\t')];
  document.querySelectorAll('#glossaryBody tr').forEach(tr=>{
    const vals=Array.from(tr.querySelectorAll('input')).map(i=>i.value);
    if(vals.some(v=>v.trim()))rows.push(vals.join('\\t'));
  });
  const text=rows.join('\\n')+'\\n';
  try{await fetch('/api/glossary',{method:'POST',headers:{'Content-Type':'text/plain; charset=utf-8'},
    body:text});
    const s=document.getElementById('glossarySaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
async function genSummary(){
  const f=curFile||undefined;
  const b=f?JSON.stringify({file:f}):'{}';
  try{await fetch('/api/summary',{method:'POST',headers:{'Content-Type':'application/json'},body:b});
    alert(I18N['dash.summary_started']);}catch(e){}
}
async function viewSummary(){
  const f=curFile?'?file='+encodeURIComponent(curFile):'';
  try{const d=await(await fetch('/api/summary'+f)).json();
    document.getElementById('summaryTitle').textContent=I18N['dash.summary_prefix']+(d.file||'');
    document.getElementById('summaryContent').textContent=d.content||I18N['dash.no_summary'];
    document.getElementById('summaryModal').classList.add('open');
  }catch(e){}
}
function closeSummary(){document.getElementById('summaryModal').classList.remove('open');}
function customCmdAddRow(pattern,action){
  const tb=document.getElementById('customCmdBody');
  const tr=document.createElement('tr');
  const td1=document.createElement('td');
  const inp1=document.createElement('input');inp1.type='text';inp1.value=pattern||'';inp1.placeholder='regex pattern';
  td1.appendChild(inp1);tr.appendChild(td1);
  const td2=document.createElement('td');
  const inp2=document.createElement('input');inp2.type='text';inp2.value=action||'';inp2.placeholder='shell command';
  td2.appendChild(inp2);tr.appendChild(td2);
  const del=document.createElement('td');
  del.className='gl-del';del.textContent='\\u00d7';
  del.onclick=()=>tr.remove();
  tr.appendChild(del);tb.appendChild(tr);
  return tr;
}
async function openCustomCmds(){
  let cmds=[];
  try{const d=await(await fetch('/api/config')).json();cmds=d.custom_commands||[];}catch(e){}
  const tb=document.getElementById('customCmdBody');tb.innerHTML='';
  cmds.forEach(c=>customCmdAddRow(c.pattern||'',c.action||''));
  if(cmds.length===0)customCmdAddRow();
  document.getElementById('customCmdSaved').style.display='none';
  document.getElementById('customCmdModal').classList.add('open');
}
function closeCustomCmds(){document.getElementById('customCmdModal').classList.remove('open');}
async function saveCustomCmds(){
  const rows=[];
  document.querySelectorAll('#customCmdBody tr').forEach(tr=>{
    const inputs=tr.querySelectorAll('input');
    const p=(inputs[0]||{}).value||'';
    const a=(inputs[1]||{}).value||'';
    if(p.trim()||a.trim())rows.push({pattern:p,action:a});
  });
  try{
    const cfg=await(await fetch('/api/config')).json();
    cfg.custom_commands=rows;
    await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
    const s=document.getElementById('customCmdSaved');s.style.display='inline';
    setTimeout(()=>s.style.display='none',2000);
  }catch(e){}
}
function openHelp(){
  document.getElementById('helpContent').textContent=I18N['dash.help_body'];
  const lang=cfgData&&cfgData.ui_language||'en';
  document.getElementById('helpReadmeLink').href='https://github.com/edocode/shadow-clerk/blob/main/'+(lang==='ja'?'README.ja.md':'README.md');
  document.getElementById('helpModal').classList.add('open');
}
function closeHelp(){document.getElementById('helpModal').classList.remove('open');}
</script>
</body>
</html>
"""
