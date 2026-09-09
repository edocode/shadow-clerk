"""Shadow-clerk daemon: mtg スキル向けエンドポイント

スキルが shell スクリプトで自前に持っていた判定を、デーモン側に寄せたもの。
同じ規則を shell と Python の両方に置くと、片方だけ直したときに黙ってずれる。
とくに「いまどの transcript が生きているか」は mtime からの推測ではなく、
デーモンが SESSION_FILE で確かに知っている事実を返す。
"""
from __future__ import annotations
import datetime
import json
import logging
import os
import re
import time
from urllib.parse import urlparse, parse_qs

from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_constants import SESSION_FILE
from shadow_clerk._daemon_dashboard_base import is_localhost_client
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain.mtg_config import MtgConfig

logger = logging.getLogger("shadow-clerk")

# 監視ストリームの既定。1 行ずつ流すと発言のたびに起こされて会議に追いつけず、
# 1 分を超えると指摘が手遅れになる
WATCH_INTERVAL_DEFAULT = 25
WATCH_IDLE_DEFAULT = 600
WATCH_INTERVAL_RANGE = (5, 300)


def _norm(name: str) -> str:
    """会議名の表記ゆれを吸収する。大文字小文字と区切りを無視する"""
    return re.sub(r"[\s_\-()\[\]]+", "", name).lower()


def _fmt_time(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


class _DashboardHandlerSkillOps:
    """mtg スキルが叩くエンドポイント（ミックスイン）"""

    def _skill_query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def _skill_guard(self) -> bool:
        """localhost 限定。通らなければ応答済みにして False を返す"""
        if is_localhost_client(self.client_address):
            return True
        self._send_json({"status": "error", "message": "skill API is localhost only"})
        return False

    # --- いま何を見るべきか ---

    def _serve_session(self) -> None:
        """GET /api/session — いま監視すべき transcript と、その状態。

        `in_meeting` は SESSION_FILE の有無、つまりデーモンが確かに知っている事実。
        mtime からの推測ではないので、沈黙している会議と終わった会議を取り違えない。
        """
        if not self._skill_guard():
            return
        path = self.recorder.output_path
        tn = TranscriptName.parse(os.path.basename(path))
        out_dir = self.recorder._output_dir
        try:
            st = os.stat(path)
            with open(path, "rb") as f:
                lines = sum(1 for _ in f)
            mtime, age = st.st_mtime, int(time.time() - st.st_mtime)
        except OSError:
            lines, mtime, age = 0, 0.0, -1
        body = {
            "status": "ok",
            "dir": out_dir,
            "transcript": path,
            "meeting": (tn.meeting_name or "") if tn else "",
            "in_meeting": os.path.exists(SESSION_FILE),
            "recording": not self.recorder.stop_event.is_set(),
            "lines": lines,
            "last_write": _fmt_time(mtime) if mtime else "",
            "age_seconds": age,
            # スキルの出力言語。プロンプトに {lang} を置いていない場合でも
            # ここから読めるようにしておく
            "language": str(load_config().get("translate_language") or ""),
        }
        if tn is not None:
            att = os.path.join(out_dir, tn.attendees_filename)
            body.update({
                "summary": os.path.join(out_dir, tn.summary_filename),
                "advice": os.path.join(out_dir, tn.advice_filename),
                "analysis": os.path.join(out_dir, tn.analysis_filename),
                "attendees": att if os.path.isfile(att) else "",
            })
        self._send_json(body)

    # --- 会議ごとの設定 ---

    def _serve_mtg_config_resolve(self) -> None:
        """GET /api/mtg-config/resolve?meeting=<名前> — 解決済みの設定"""
        if not self._skill_guard():
            return
        meeting = (self._skill_query().get("meeting") or [""])[0]
        self._send_json({"status": "ok", **MtgConfig.load().resolve(meeting)})

    # --- 定例の過去回 ---

    def _serve_meeting_history(self) -> None:
        """GET /api/meeting-history?meeting=<名前>&count=N — 同じ会議の過去回。

        照合は会議名の正規化一致。設定の `meetings[].pattern` は「この種類の会議を
        どう扱うか」を決めるもので会議の同一性ではない（実際 Sprint_MTG と
        Platformチーム_Standup が同じルールに当たる）ので使わない。
        """
        if not self._skill_guard():
            return
        q = self._skill_query()
        meeting = (q.get("meeting") or [""])[0]
        try:
            count = max(0, min(20, int((q.get("count") or ["3"])[0])))
        except ValueError:
            count = 3
        if not meeting or count == 0:
            self._send_json({"status": "ok", "meetings": []})
            return
        out_dir = self.recorder._output_dir
        target = _norm(meeting)
        rows = []
        try:
            names = os.listdir(out_dir)
        except OSError:
            names = []
        for name in names:
            tn = TranscriptName.parse(name)
            if tn is None or not tn.meeting_name or _norm(tn.meeting_name) != target:
                continue
            rows.append((tn.datetime_str, tn))
        rows.sort(key=lambda r: r[0], reverse=True)
        current = os.path.basename(self.recorder.output_path)
        out = []
        for _, tn in rows:
            if tn.filename == current:
                continue          # 進行中の回は履歴ではない
            def _p(fname: str) -> str:
                full = os.path.join(out_dir, fname)
                return full if os.path.isfile(full) else ""
            out.append({
                "datetime": tn.label,
                "meeting": tn.meeting_name,
                "transcript": _p(tn.filename),
                "summary": _p(tn.summary_filename),
                "advice": _p(tn.advice_filename),
                "analysis": _p(tn.analysis_filename),
            })
            if len(out) >= count:
                break
        self._send_json({"status": "ok", "meetings": out})

    # --- 監視ストリーム ---

    def _serve_watch(self) -> None:
        """GET /api/watch?interval=25&idle=600 — 新規行をまとめて流し続ける。

        Monitor ツールは長く走るコマンドを要求するので、単発の API では
        置き換えられない。接続を保って流し続けることで、shell スクリプトを
        `curl -sN` に置き換えられる。多バイト境界の扱いは FileWatcher の
        `_read_diff` と同じ理屈で、最後の改行までに丸めて送る。
        """
        if not is_localhost_client(self.client_address):
            self.send_error(403)
            return
        q = self._skill_query()

        def _int(key: str, default: int) -> int:
            try:
                return int((q.get(key) or [str(default)])[0])
            except ValueError:
                return default

        interval = max(WATCH_INTERVAL_RANGE[0],
                       min(WATCH_INTERVAL_RANGE[1], _int("interval", WATCH_INTERVAL_DEFAULT)))
        idle_alert = max(0, _int("idle", WATCH_IDLE_DEFAULT))
        name = (q.get("file") or [""])[0]
        path = (os.path.join(self.recorder._output_dir, name)
                if name and os.path.basename(name) == name
                else self.recorder.output_path)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        def _size() -> int:
            try:
                return os.path.getsize(path)
            except OSError:
                return 0

        offset, quiet = _size(), 0
        logger.info("監視ストリーム開始: %s (interval=%ds)", os.path.basename(path), interval)
        try:
            while not self.recorder.stop_event.is_set():
                self.recorder.stop_event.wait(timeout=interval)
                if self.recorder.stop_event.is_set():
                    break
                cur = _size()
                if cur < offset:
                    offset = 0        # 書き直された。先頭から拾い直す
                chunk = b""
                if cur > offset:
                    try:
                        with open(path, "rb") as f:
                            f.seek(offset)
                            chunk = f.read()
                    except OSError:
                        chunk = b""
                nl = chunk.rfind(b"\n")
                if nl >= 0:
                    text = chunk[:nl + 1].decode("utf-8", errors="replace")
                    offset += nl + 1
                    n = text.count("\n")
                    self.wfile.write(f"===== 新規 {n} 行 =====\n{text}".encode())
                    self.wfile.flush()
                    quiet = 0
                else:
                    quiet += interval
                    if idle_alert and quiet >= idle_alert:
                        self.wfile.write(
                            f"===== {quiet // 60} 分間 追記なし"
                            f"(会議終了、または長い沈黙) =====\n".encode())
                        self.wfile.flush()
                        quiet = 0
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            logger.info("監視ストリーム終了: %s", os.path.basename(path))
