"""Shadow-clerk daemon: ログバッファ・ファイルウォッチャー"""
from __future__ import annotations
import collections
import json
import logging
import os
import queue
import threading
import time
from typing import Any
from shadow_clerk import DATA_DIR, CONFIG_FILE
from shadow_clerk._daemon_audio import get_default_source_name
from shadow_clerk._daemon_audio_devices import _device_label, _wpctl_description_map
from shadow_clerk._daemon_constants import SESSION_FILE, STREAM_RESOLVE_INTERVAL
from shadow_clerk._daemon_config import load_config

logger = logging.getLogger("shadow-clerk")

# device 名がこれらのエイリアスの場合は get_default_source_name で OS 側の実名を
# 問い合わせる。それ以外の実デバイス名 (例: "alsa_output...monitor") はデバイス
# 選択 UI と同じ _device_label でラベル化する（_resolve_device_name 参照）
_ALIAS_DEVICE_NAMES = {"default", "pipewire"}

# 同じ例外が毎秒起きてもログが溢れないよう、抑制した回数をまとめて出す間隔
_POLL_ERROR_LOG_INTERVAL_SEC = 60.0

# SSE クライアント 1 人あたりのキュー上限。イベントは小さな JSON 文字列
# (数十〜数百バイト、transcript の diff でも通常は数KB) なので、200件分を
# 保持しても最悪数百KB〜数MB 程度でトリビアル。level イベントは毎秒配信され
# transcript/translation/log が同時に飛ぶこともあるバーストを吸収しつつ、
# 詰まったクライアント (読み出しが止まっている) を十分な余裕を持って検出できる
# 大きさとして選んだ
_CLIENT_QUEUE_MAXSIZE = 200


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
        # device 名 → (表示名, 解決時刻) のキャッシュ。エイリアス ("default" 等)
        # の実名解決だけでなく、実デバイス名のラベル化（_device_label 経由）も
        # ここを通す。STREAM_RESOLVE_INTERVAL 秒だけ再利用し、_poll_levels の
        # 毎秒呼び出しで subprocess を叩き続けない
        self._name_cache: dict[str, tuple[str, float]] = {}
        self._last_poll_error: str | None = None
        self._last_poll_error_at = 0.0
        self._poll_error_suppressed = 0

    def add_client(self) -> queue.Queue[tuple[str, str]]:
        q: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=_CLIENT_QUEUE_MAXSIZE)
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
        """全クライアントへ配信する。

        キューが満杯になるのは一時的に忙しいクライアントではなく、読み出しが
        止まっている（=切断済みか、ソケットが詰まっている）クライアントで
        ある。ダッシュボードは再接続時に /api/status 等で状態を再取得するため、
        イベントを読み損ねても壊れず古くなるだけ。よって個々のイベントを
        黙って捨てるのではなく、そのクライアントを以後の配信対象から外す
        （実ソケットの後始末は _serve_sse 側のソケット書き込みタイムアウトが
        別途担う）。
        put_nowait が queue.Full 以外の例外を出すのは想定外なので、以前のように
        黙って握り潰さずログに残す。
        """
        with self._clients_lock:
            clients = list(self._clients)
        dead: list[queue.Queue[tuple[str, str]]] = []
        for q in clients:
            try:
                q.put_nowait((event, data))
            except queue.Full:
                dead.append(q)
            except Exception:  # pylint: disable=broad-except
                logger.warning("SSE クライアントへの配信で想定外の例外", exc_info=True)
                dead.append(q)
        if dead:
            with self._clients_lock:
                for q in dead:
                    try:
                        self._clients.remove(q)
                    except ValueError:
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
            self._poll_iteration()
            self._recorder.stop_event.wait(timeout=1.0)

    def _poll_iteration(self) -> None:
        """1 回分のポーリングを行う。

        _poll_levels() は _poll() の最後の文として置いていたため、transcript
        読み取りや翻訳など無関係な処理が _poll() の途中で例外を投げると、
        レベル配信そのものが永久に止まっていた。フリーズしたレベルバーは
        最後に描いた値のまま緑で止まるため、「音声は正常」に見えてしまう
        （fail unsafe）。呼び出しを分離し、どちらが失敗しても他方は必ず動く
        ようにする
        """
        try:
            self._poll()
        except Exception as e:  # pylint: disable=broad-except
            self._log_poll_exception(e)
        try:
            self._poll_levels()
        except Exception as e:  # pylint: disable=broad-except
            self._log_poll_exception(e)

    def _log_poll_exception(self, exc: BaseException) -> None:
        """ポーリング中の想定外の例外を記録する。

        以前は run() が `except Exception: pass` で無条件に握り潰し、原因が
        全く分からなかった。ここでは記録してループを継続するが、同じ例外が
        毎秒起きてもログを溢れさせないよう、同一メッセージは
        _POLL_ERROR_LOG_INTERVAL_SEC 秒に一度だけ出し、その間の発生回数は
        まとめて次のログに添える。
        """
        key = f"{type(exc).__name__}: {exc}"
        now = time.monotonic()
        if (key == self._last_poll_error
                and now - self._last_poll_error_at < _POLL_ERROR_LOG_INTERVAL_SEC):
            self._poll_error_suppressed += 1
            return
        suffix = (f"（直近 {self._poll_error_suppressed} 回抑制）"
                  if self._poll_error_suppressed else "")
        logger.warning("FileWatcher のポーリングで例外%s: %s", suffix, key, exc_info=exc)
        self._last_poll_error = key
        self._last_poll_error_at = now
        self._poll_error_suppressed = 0

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
                # sounddevice 経路が開けていない。pw-record/parec バックエンド経路
                # (backend_source) で開いている可能性があり、そちらのレベルも
                # 同じ CaptureLevel に積まれているので、破棄せず配信する。
                # PipeWire は名前でなく object.serial を渡すため、requested/
                # fallback は判定不能として None/false のままにする
                src = getattr(self._recorder, "backend_source", {}).get(label)
                payload[label] = None if src is None else {
                    "rms": round(snap.rms, 1),
                    "peak": round(snap.peak),
                    "crest": round(snap.crest, 1),
                    "device": src,
                    "requested": None,
                    "fallback": False,
                }
                continue
            requested = stream.requested
            raw_name = stream.device.name
            payload[label] = {
                "rms": round(snap.rms, 1),
                "peak": round(snap.peak),
                "crest": round(snap.crest, 1),
                "device": self._resolve_device_name(raw_name),
                "requested": requested,
                "fallback": bool(requested) and raw_name != requested,
            }
        self._broadcast("level", json.dumps(payload, ensure_ascii=False))

    def _resolve_device_name(self, name: str) -> str:
        """ツールチップ用にデバイス名を表示用ラベルへ解決する。

        2 通りの名前が来る。
        - エイリアス ("default" 等): device 未指定でマイクを開くと PortAudio は
          これしか返さない。そのまま出すと、OS のデフォルト入力が死んだ内蔵
          マイクにすり替わっていても気づけない——このレベルバー機能の
          きっかけになった障害そのものが再現するため、get_default_source_name
          で OS 側の実名に解決する。
        - 実デバイス名 (例 "alsa_output...monitor"): ノード名そのものはツール
          チップに出すには長すぎる壁の文字列なので、デバイス選択 UI と同じ
          _device_label（_daemon_audio_devices.py）に通し、picker と表記を
          揃える。ラベル化できない場合は生の名前をそのまま返す（何も出さない
          より良い）。

        どちらの経路も subprocess 呼び出しを伴いうる（wpctl）。
        _wpctl_description_map 側にもモジュールレベルのキャッシュがあるが、
        それは「取得に成功した場合だけ」キャッシュするため、wpctl が異常系で
        空を返し続けると _poll_levels の毎秒呼び出しのたびに subprocess が
        起き続ける恐れがある。そこをこのメソッド自身の TTL キャッシュ
        （STREAM_RESOLVE_INTERVAL 秒。キャプチャ監視スレッドが自身のデフォルト
        Sink 変更チェックに使う周期と同じ）で必ず抑える——2 層のキャッシュの
        責務を分けず「ここで引いたら STREAM_RESOLVE_INTERVAL 秒は再利用する」
        という単純な取り決め 1 つに寄せている。
        """
        cached = self._name_cache.get(name)
        now = time.monotonic()
        if cached and now - cached[1] < STREAM_RESOLVE_INTERVAL:
            return cached[0]
        if name in _ALIAS_DEVICE_NAMES:
            resolved = get_default_source_name() or name
        else:
            resolved = _device_label(name, _wpctl_description_map())
        self._name_cache[name] = (resolved, now)
        return resolved
