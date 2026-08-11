"""Shadow-clerk daemon: ログバッファ・ファイルウォッチャー"""
from __future__ import annotations
import collections
import json
import logging
import os
import queue
import threading
from typing import Any
from shadow_clerk import DATA_DIR, CONFIG_FILE
from shadow_clerk._daemon_constants import SESSION_FILE
from shadow_clerk._daemon_config import load_config

logger = logging.getLogger("shadow-clerk")


class LogBuffer(logging.Handler):
    """ログ用の循環バッファ（メモリ内でログ行を保持）"""

    def __init__(self, maxlen: int = 500) -> None:
        super().__init__()
        self._buf: collections.deque[tuple[int, str]] = collections.deque(maxlen=maxlen)
        self._seq = 0
        self._buf_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        line = self.format(record)
        with self._buf_lock:
            self._buf.append((self._seq, line))
            self._seq += 1

    @property
    def counter(self) -> int:
        with self._buf_lock:
            return self._seq

    def get_lines(self, n: int = 100) -> list[str]:
        with self._buf_lock:
            items = list(self._buf)
        return [line for _, line in items[-n:]]

    def get_new_lines(self, since: int) -> tuple[list[str], int]:
        with self._buf_lock:
            items = list(self._buf)
            seq = self._seq
        return [line for s, line in items if s >= since], seq


class FileWatcher(threading.Thread):
    """ファイル監視 + SSE ブロードキャスト"""

    def __init__(self, recorder: Any, log_buffer: LogBuffer) -> None:
        super().__init__(name="file-watcher", daemon=True)
        self._recorder = recorder
        self._log_buffer = log_buffer
        self._clients: list[queue.Queue[tuple[str, str]]] = []
        self._clients_lock = threading.Lock()
        self._file_offsets: dict[tuple[str, str], int] = {}
        self._mtimes: dict[str, float] = {}
        self._log_counter = 0
        self._last_status: bool | None = None
        self._last_ptt: bool | None = None

    def add_client(self) -> queue.Queue[tuple[str, str]]:
        q: queue.Queue[tuple[str, str]] = queue.Queue()
        running = not self._recorder.stop_event.is_set()
        q.put(("recorder_status", json.dumps({"running": running})))
        with self._clients_lock:
            self._clients.append(q)
        return q

    def remove_client(self, q: queue.Queue[tuple[str, str]]) -> None:
        with self._clients_lock:
            try:
                self._clients.remove(q)
            except ValueError:
                pass

    def _broadcast(self, event: str, data: str) -> None:
        with self._clients_lock:
            for q in self._clients:
                try:
                    q.put_nowait((event, data))
                except Exception:
                    pass

    def _get_size(self, path: str) -> int:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _get_mtime(self, path: str) -> float:
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0

    def _read_diff(self, path: str, old_size: int) -> tuple[str | None, int]:
        """old_size 以降の差分を返す。返す新オフセットは「実際に配信したバイト数」。

        os.path.getsize() と read() の間の追記で diff が getsize 値を超え、
        offset を getsize にすると超過分を次回再配信して行が重複する問題を防ぐため、
        実読み取りバイト数でオフセットを進める。さらに最後の改行までに丸めて、
        マルチバイト文字や行の途中で切れた断片を配信しない。
        """
        try:
            new_size = os.path.getsize(path)
            if new_size < old_size:
                # ファイル縮小（書き換え）→ 呼び出し側が別途オフセットをリセットする
                return None, new_size
            if new_size == old_size:
                return None, old_size
            with open(path, "rb") as f:
                f.seek(old_size)
                raw = f.read()
            nl = raw.rfind(b"\n")
            if nl < 0:
                # 完全な行がまだ書き込まれていない → 次回ポーリングまで保留
                return None, old_size
            raw = raw[:nl + 1]
            return raw.decode("utf-8", errors="replace"), old_size + len(raw)
        except OSError:
            return None, 0

    def run(self) -> None:
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
        # 過去ファイルの one-shot 翻訳中は translate_target_path を優先して監視
        target = getattr(self._recorder, "translate_target_path", None)
        if target and target != t_path:
            from shadow_clerk._transcript_name import TranscriptName as _TN
            _tn = _TN.parse(os.path.basename(target))
            if _tn:
                tr_name = _tn.translation_filename(lang)
                tr_path = os.path.join(os.path.dirname(target), tr_name)
        key = ("translation", tr_path)
        if key not in self._file_offsets:
            self._file_offsets[key] = self._get_size(tr_path)
        # ファイル縮小（再生成で上書き）時はオフセットをリセット
        cur_size = self._get_size(tr_path)
        if cur_size < self._file_offsets[key]:
            self._file_offsets[key] = 0
        diff, new_size = self._read_diff(tr_path, self._file_offsets.get(key, 0))
        if diff:
            self._file_offsets[key] = new_size
            self._broadcast("translation", json.dumps(
                {"file": tr_name, "diff": diff}, ensure_ascii=False))

        # Metadata files (mtime-based)
        for evt, path in [
            ("session", SESSION_FILE),
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

        self._poll_levels()

    def _poll_levels(self) -> None:
        """入力レベルを 1 秒ごとに配信する"""
        levels = getattr(self._recorder, "levels", None)
        if not levels:
            return
        streams = getattr(self._recorder, "open_streams", {})
        payload: dict[str, dict | None] = {}
        for label, level in levels.items():
            snap = level.snapshot()
            stream = streams.get(label)
            if stream is None:
                payload[label] = None
                continue
            requested = stream.requested
            payload[label] = {
                "rms": round(snap.rms, 1),
                "peak": round(snap.peak),
                "crest": round(snap.crest, 1),
                "device": stream.device.name,
                "requested": requested,
                "fallback": bool(requested) and stream.device.name != requested,
            }
        self._broadcast("level", json.dumps(payload, ensure_ascii=False))
