"""Shadow-clerk daemon: 会議アシスタントスキル向けエンドポイント

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
from shadow_clerk._daemon_dashboard_base import is_localhost_client, read_local_json_body
from shadow_clerk._transcript_name import TranscriptName, sanitize_meeting_name
from shadow_clerk.domain import Language
from shadow_clerk.domain.meeting_config import MeetingConfig

logger = logging.getLogger("shadow-clerk")

# 監視ストリームの既定。1 行ずつ流すと発言のたびに起こされて会議に追いつけず、
# 1 分を超えると指摘が手遅れになる。Claude と会議の skill は 1 秒で張る
WATCH_INTERVAL_DEFAULT = 25
WATCH_IDLE_DEFAULT = 600
WATCH_INTERVAL_RANGE = (1, 300)

_MAX_MEETING_NAME_CHARS = 100
_MUTE_SOURCES = ("mic", "monitor")
_MAX_GENERATED_CHARS = 20000
_GENERATED_KINDS = ("advice", "analysis")
_GENERATED_MODES = ("replace", "append")
_HISTORY_TAIL_MAX = 50


def _norm(name: str) -> str:
    """会議名の表記ゆれを吸収する。大文字小文字と区切りを無視する"""
    return re.sub(r"[\s_\-()\[\]]+", "", name).lower()


def wrap_transcript(name: str, text: str, tag: str = "transcript") -> bytes:
    """流す行を <transcript>（kind=advice なら <advice>）で囲む

    **囲うこと。** 中身は音声認識の結果であって読み手への指示ではない。裸で流すと
    「まとめて」のような発言が指示として読まれる (実際に監視が止められた)。
    本文に閉じタグを名乗る行が現れても境界が壊れないよう、行頭の </transcript> は
    先頭に空白を入れて無害化する。
    """
    close = f"</{tag}>"
    body = text.replace("\n" + close, "\n " + close)
    if body.startswith(close):
        body = " " + body
    if body and not body.endswith("\n"):
        body += "\n"
    return f'<{tag} file="{name}">\n{body}{close}\n'.encode()


def _fmt_time(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _query_int(q: dict[str, list[str]], key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int((q.get(key) or [str(default)])[0])))
    except ValueError:
        return default


def _tail_lines(path: str, n: int) -> list[str]:
    """transcript の末尾 n 行。前回の練習のまとめ（「今日の練習のまとめ: …」）を skill が読むため"""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-n:]
    except OSError:
        return []


def _lacks_final_newline(path: str) -> bool:
    """ファイルが改行で終わっていないか。無い・空なら False"""
    try:
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            return f.read(1) != b"\n"
    except OSError:
        return False


class _DashboardHandlerSkillOps:
    """会議アシスタントスキルが叩くエンドポイント（ミックスイン）"""

    def _skill_query(self) -> dict[str, list[str]]:
        # curl は URL の非 ASCII（日本語の会議名）を符号化せずに送り、http.server はそれを latin-1 として読む。
        # UTF-8 に読み直さないと meeting=英語練習 が化けて、どの会議にも当たらない
        path = self.path
        try:
            path = path.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        return parse_qs(urlparse(path).query)

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

    def _serve_meeting_config_resolve(self) -> None:
        """GET /api/meeting-config/resolve?meeting=<名前> — 解決済みの設定"""
        if not self._skill_guard():
            return
        meeting = (self._skill_query().get("meeting") or [""])[0]
        self._send_json({"status": "ok", **MeetingConfig.load().resolve(meeting)})

    # --- 定例の過去回 ---

    def _serve_meeting_history(self) -> None:
        """GET /api/meeting-history?meeting=<名前>&count=N[&tail=M] — 同じ会議の過去回。

        tail（0〜50、既定 0）を付けると、各回に transcript の末尾 M 行を "tail" で足す。curl しか使えない
        clerk-practice が前回のまとめを読むため。

        照合は会議名の正規化一致。設定の `meetings[].pattern` は「この種類の会議を
        どう扱うか」を決めるもので会議の同一性ではない（実際 Sprint_MTG と
        Platformチーム_Standup が同じルールに当たる）ので使わない。
        """
        if not self._skill_guard():
            return
        q = self._skill_query()
        meeting = (q.get("meeting") or [""])[0]
        count = _query_int(q, "count", 3, 0, 20)
        tail = _query_int(q, "tail", 0, 0, _HISTORY_TAIL_MAX)
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
            row: dict[str, object] = {
                "datetime": tn.label,
                "meeting": tn.meeting_name,
                "transcript": _p(tn.filename),
                "summary": _p(tn.summary_filename),
                "advice": _p(tn.advice_filename),
                "analysis": _p(tn.analysis_filename),
            }
            if tail:
                row["tail"] = _tail_lines(str(row["transcript"]), tail)
            out.append(row)
            if len(out) >= count:
                break
        self._send_json({"status": "ok", "meetings": out})

    # --- 監視ストリーム ---

    def _set_language(self) -> None:
        """POST /api/language {language} — 検出言語を切り替える。"auto" で自動検出

        talk の skill が、ユーザーが英語で話したいときに使う（ja のままだと英語がカタカナで起こされる）。
        /api/command と違い、既知の言語コードしか通さない
        """
        data = read_local_json_body(self, "language")
        if data is None:
            return
        lang = data.get("language")
        if lang != "auto" and lang not in {v.value for v in Language}:
            self._send_json({"status": "error", "message": "language must be auto or a known language code"})
            return
        self.recorder._execute_command("unset_language" if lang == "auto" else f"set_language {lang}")
        self._send_json({"status": "ok", "language": lang})

    def _meeting(self) -> None:
        """POST /api/meeting {action: start|end, name?, analyze?} — 会議を始める・終える（clerk-practice 用）

        /api/command は任意のコマンドを通すので skill には使わせない。開始は会議中なら、終了は会議中でなければ
        何もしない（会議の外で end_meeting を通すと、日付のファイルに終了の印が書かれる）
        """
        data = read_local_json_body(self, "meeting")
        if data is None:
            return
        action, in_meeting = data.get("action"), os.path.exists(SESSION_FILE)
        if action == "start":
            raw, analyze = data.get("name"), data.get("analyze", True)
            name = sanitize_meeting_name(raw) if isinstance(raw, str) and len(raw) <= _MAX_MEETING_NAME_CHARS else ""
            if not name or not isinstance(analyze, bool):
                self._send_json({"status": "error",
                                 "message": "name must be a meeting name up to 100 characters and analyze a boolean"})
                return
            if not in_meeting:
                self.recorder.start_meeting(name, analyze=analyze)
        elif action == "end":
            if in_meeting:
                self.recorder._execute_command("end_meeting")
        else:
            self._send_json({"status": "error", "message": "action must be start or end"})
            return
        path = self.recorder.output_path
        tn = TranscriptName.parse(os.path.basename(path))
        self._send_json({"status": "ok", "meeting": (tn.meeting_name or "") if tn else "",
                         "transcript": path, "in_meeting": os.path.exists(SESSION_FILE)})

    def _set_mute(self) -> None:
        """POST /api/mute {source: mic|monitor, muted} — ダッシュボードのミュートボタンと同じ状態を切り替える

        previous（切り替え前）を返すので、skill は終わるときに元に戻せる
        """
        data = read_local_json_body(self, "mute")
        if data is None:
            return
        source, muted = data.get("source"), data.get("muted")
        if source not in _MUTE_SOURCES or not isinstance(muted, bool):
            self._send_json({"status": "error", "message": "source must be mic or monitor and muted a boolean"})
            return
        previous = bool(getattr(self.recorder, f"mute_{source}"))
        self.recorder._execute_command(f"mute_{source}" if muted else f"unmute_{source}")
        self._send_json({"status": "ok", "source": source, "muted": muted, "previous": previous})

    def _write_generated(self) -> None:
        """POST /api/generated {kind: advice|analysis, mode: replace|append, text} — いまの書き込み先の生成物を書く

        clerk-practice（talk の console）は curl しか使えないので、Advice / Analysis をここから書く。パスは受け取らない。
        会議の外ではその日のファイルの advice / analysis に書く。ダッシュボードの表示は FileWatcher が更新する
        """
        data = read_local_json_body(self, "generated")
        if data is None:
            return
        kind, mode, text = data.get("kind"), data.get("mode"), data.get("text")
        if (kind not in _GENERATED_KINDS or mode not in _GENERATED_MODES
                or not isinstance(text, str) or len(text) > _MAX_GENERATED_CHARS):
            self._send_json({"status": "error", "message": "kind must be advice or analysis, mode replace or append, "
                                                           "and text a string up to 20000 characters"})
            return
        transcript = self.recorder.output_path
        tn = TranscriptName.parse(os.path.basename(transcript))
        if tn is None:
            self._send_json({"status": "error", "message": "the current output is not a transcript file"})
            return
        # FileWatcher と同じく transcript の隣に書く（明示の --output でも表示が追従する）
        path = os.path.join(os.path.dirname(transcript),
                            tn.advice_filename if kind == "advice" else tn.analysis_filename)
        try:
            if mode == "append":
                sep = "\n" if _lacks_final_newline(path) else ""
                with open(path, "a", encoding="utf-8") as f:
                    f.write(sep + text)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
        except OSError as e:
            self._send_json({"status": "error", "message": str(e)})
            return
        self._send_json({"status": "ok", "kind": kind, "mode": mode, "file": path})

    def _serve_skill_status(self) -> None:
        """GET /api/skill-status — 記録済みの配布先ごとに状態を返す"""
        from shadow_clerk import skill_install
        self._send_json(skill_install.skill_status(skill_install.remembered_targets()))

    def _install_skill(self) -> None:
        """POST /api/skill-install — {"target": "claude"} を受けて配る"""
        from shadow_clerk import skill_install
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, ValueError, TypeError):
            self.send_error(400)
            return
        if not isinstance(data, dict):
            self.send_error(400)
            return
        try:
            result = skill_install.install(str(data.get("target") or "claude"),
                                           force=bool(data.get("force")))
        except skill_install.InstallRefused as e:
            self._send_json({"status": "refused", "message": str(e)})
            return
        except OSError as e:
            self._send_json({"status": "error", "message": str(e)})
            return
        self._send_json({"status": "ok", "result": result})

    def _serve_watch(self) -> None:
        """GET /api/watch?interval=25&idle=600[&kind=advice][&file=…] — 新規行をまとめて流し続ける。

        file を指定しなければ、いまの書き込み先（recorder.output_path）を毎回見る。日付の切り替えや会議の開始・終了で
        変わったら <notice> を流し、新しいファイルを先頭から流す（つないだ時点のファイルを見続けると、0 時を
        またいだところで発言が届かなくなる）。file 指定と kind=advice は指定のファイルを見続ける。

        kind=advice なら、transcript に対応する advice ファイルを見張り、書き換わるたびに中身を丸ごと流す
        （advice は上書きされるので差分ではなく全体）。Claude と会議の skill が、会議アシスタントの論点を
        拾って自分から切り出すために使う。

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
        follow = not name
        kind = (q.get("kind") or ["transcript"])[0]
        if kind not in ("transcript", "advice"):
            self.send_error(400)
            return
        if kind == "advice":
            tn = TranscriptName.parse(os.path.basename(path))
            if tn is None:
                self.send_error(400)
                return
            self._stream_whole_file(os.path.join(os.path.dirname(path), tn.advice_filename), interval)
            return

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
                if follow and self.recorder.output_path != path:
                    path, offset, quiet = self.recorder.output_path, 0, 0
                    self.wfile.write(f"<notice>書き込み先が {os.path.basename(path)} に変わりました</notice>\n".encode())
                    self.wfile.flush()
                    logger.info("監視ストリーム: 書き込み先が変わった: %s", os.path.basename(path))
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
                    self.wfile.write(wrap_transcript(os.path.basename(path), text))
                    self.wfile.flush()
                    quiet = 0
                else:
                    quiet += interval
                    if idle_alert and quiet >= idle_alert:
                        self.wfile.write(
                            f"<notice>{quiet // 60} 分間 追記なし"
                            f"(会議終了、または長い沈黙)</notice>\n".encode())
                        self.wfile.flush()
                        quiet = 0
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            logger.info("監視ストリーム終了: %s", os.path.basename(path))

    def _stream_whole_file(self, path: str, interval: int) -> None:
        """上書きされるファイル（advice）を見張り、開始時と中身が変わるたびに全体を流す。無いうちは何も流さない"""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        name, last = os.path.basename(path), ""
        logger.info("監視ストリーム開始: %s (interval=%ds)", name, interval)
        try:
            while True:
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except OSError:
                    text = ""
                if text.strip() and text != last:
                    self.wfile.write(wrap_transcript(name, text, tag="advice"))
                    self.wfile.flush()
                    last = text
                if self.recorder.stop_event.wait(timeout=interval):
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            logger.info("監視ストリーム終了: %s", name)
