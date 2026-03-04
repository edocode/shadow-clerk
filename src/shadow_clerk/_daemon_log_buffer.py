"""Shadow-clerk daemon: ログバッファ・ファイルウォッチャー"""

import collections
import json
import logging
import os
import queue
import threading
from shadow_clerk import DATA_DIR, CONFIG_FILE
from shadow_clerk._daemon_constants import (
    COMMAND_FILE, SESSION_FILE,
)
from shadow_clerk._daemon_config import load_config

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
