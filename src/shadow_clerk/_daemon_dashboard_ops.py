"""Shadow-clerk daemon: ダッシュボード ファイル操作・設定エンドポイント"""
# pylint: disable=duplicate-code  # 各モジュールで必要な optional import ブロックは共通形だが抽象化不可
from __future__ import annotations
import collections
import json
import logging
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import yaml
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import GLOSSARY_FILE, DEFAULT_CONFIG
from shadow_clerk._daemon_config import load_config, get_translation_provider
from shadow_clerk._transcript_name import TranscriptName, sanitize_meeting_name

try:
    from shadow_clerk.llm_client import load_dotenv as llm_load_dotenv
    _HAS_LLM_CLIENT = True
except ImportError:
    _HAS_LLM_CLIENT = False

logger = logging.getLogger("shadow-clerk")


class _DashboardHandlerOps:
    """ダッシュボード ファイル操作・設定エンドポイント（ミックスイン）"""

    def _delete_transcript_line(self) -> None:
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
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
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

        # 転写スレッドの追記と競合しないようロックを取って read-modify-write する
        with self.recorder.transcript_lock:
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
            tr_path = None
            if timestamps:
                config = load_config()
                lang = config.get("translate_language", "ja")
                _tn = TranscriptName.parse(os.path.basename(t_path))
                if _tn:
                    tr_path = os.path.join(os.path.dirname(t_path), _tn.translation_filename(lang))
                    if os.path.exists(tr_path):
                        self._remove_lines_from_file_by_ts(tr_path, timestamps)
                    else:
                        tr_path = None

        # FileWatcher オフセット・translate_offset を新サイズにリセット
        self._reset_watch_offsets(
            [("transcript", t_path), ("translation", tr_path)], [t_path])

        # transcript がマーカー行・空行のみになった場合は関連ファイルごと削除
        cleaned = self._check_and_cleanup_empty_transcript(t_path)
        if cleaned:
            self._send_json({"status": "ok", "deleted": cleaned})
            return

        self._send_json({"status": "ok"})

    def _cleanup_transcript_files(self, t_path: str, tn: TranscriptName | None) -> list[str]:
        """transcript ファイルと関連ファイルを削除し、削除ファイル名リストを返す。
        transcript 本体の削除に失敗した場合は空リストを返す。"""
        output_dir = os.path.dirname(t_path)
        deleted: list[str] = []
        try:
            os.remove(t_path)
            deleted.append(os.path.basename(t_path))
        except OSError:
            return []
        if tn:
            for f in os.listdir(output_dir):
                if f.startswith(tn.stem + "-") and f.endswith(".txt"):
                    try:
                        os.remove(os.path.join(output_dir, f))
                        deleted.append(f)
                    except OSError:
                        pass
            summary_path = os.path.join(output_dir, tn.summary_filename)
            if os.path.exists(summary_path):
                try:
                    os.remove(summary_path)
                    deleted.append(tn.summary_filename)
                except OSError:
                    pass
        offset_file = t_path + ".translate_offset"
        if os.path.exists(offset_file):
            try:
                os.remove(offset_file)
                deleted.append(os.path.basename(offset_file))
            except OSError:
                pass
        trans_prefix = os.path.join(output_dir, tn.stem + "-") if tn else None
        if self.file_watcher:
            for k in [k for k in self.file_watcher._file_offsets
                      if k[1] == t_path or (trans_prefix and k[1].startswith(trans_prefix))]:
                del self.file_watcher._file_offsets[k]
            for k in [k for k in self.file_watcher._mtimes
                      if k == t_path or (trans_prefix and k.startswith(trans_prefix))]:
                del self.file_watcher._mtimes[k]
        if self.recorder.output_path == t_path:
            self.recorder.output_path = self.recorder._get_default_output()
        return deleted

    def _delete_transcript_file(self) -> None:
        """POST /api/transcript/delete-file — transcript ファイルと関連ファイルを一括削除"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            file_param = data.get("file", "")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
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
        tn = TranscriptName.parse(os.path.basename(t_path))
        deleted = self._cleanup_transcript_files(t_path, tn)
        if not deleted:
            self._send_json({"status": "error", "message": t("dash.delete_error")})
            return
        self._send_json({"status": "ok", "deleted": deleted})

    def _merge_meeting_to_daily(self) -> None:
        """POST /api/transcript/merge-to-daily — 会議ファイルを日次ファイルにマージして削除"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            file_param = data.get("file", "")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
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
        tn = TranscriptName.parse(os.path.basename(t_path))
        if not tn or not tn.is_meeting_file:
            self._send_json({"status": "error", "message": t("dash.merge_to_daily_error")})
            return

        daily_tn = TranscriptName(tn.datetime_str[:8], None)
        ts_pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]")
        marker_re = re.compile(r"^---\s.*\s---\s*$")

        def _merge_file(src: str, dst: str) -> None:
            """src の行（マーカー除去）を dst にタイムスタンプ順でマージして書き戻す"""
            try:
                with open(src, "r", encoding="utf-8") as f:
                    src_lines = [l for l in f if not marker_re.match(l.strip())]
            except OSError:
                return
            dst_lines: list[str] = []
            if os.path.exists(dst):
                try:
                    with open(dst, "r", encoding="utf-8") as f:
                        dst_lines = f.readlines()
                except OSError:
                    pass
            blocks: list[list[str]] = []
            cur: list[str] = []
            for line in dst_lines + src_lines:
                if ts_pattern.match(line):
                    if cur:
                        blocks.append(cur)
                    cur = [line]
                else:
                    cur.append(line)
            if cur:
                blocks.append(cur)
            blocks.sort(key=lambda b: (ts_pattern.match(b[0]).group(1) if ts_pattern.match(b[0]) else ""))
            self._atomic_write_lines(dst, [line for b in blocks for line in b])

        daily_path = os.path.join(output_dir, daily_tn.filename)
        merged_translations: list[str] = []
        with self.recorder.transcript_lock:
            # transcript 本体をマージ
            _merge_file(t_path, daily_path)
            # 翻訳ファイルをマージ (transcript-YYYYMMDDHHMM[@name]-{lang}.txt → transcript-YYYYMMDD-{lang}.txt)
            for fname in os.listdir(output_dir):
                if fname.startswith(tn.stem + "-") and fname.endswith(".txt"):
                    lang = fname[len(tn.stem) + 1:-4]
                    if lang:
                        daily_tr = os.path.join(output_dir, daily_tn.translation_filename(lang))
                        _merge_file(os.path.join(output_dir, fname), daily_tr)
                        merged_translations.append(daily_tr)

        # マージは日次ファイルの途中に行を挿入するため、旧オフセットのままだと
        # FileWatcher が無関係なバイト範囲を配信し、翻訳ループもずれた範囲を翻訳する
        self._reset_watch_offsets(
            [("transcript", daily_path)] + [("translation", p) for p in merged_translations],
            [daily_path])

        deleted = self._cleanup_transcript_files(t_path, tn)
        if not deleted:
            self._send_json({"status": "error", "message": t("dash.merge_to_daily_error")})
            return
        self._send_json({"status": "ok", "deleted": deleted})

    @staticmethod
    def _atomic_write_lines(path: str, lines: list[str]) -> None:
        """一時ファイル → os.replace でアトミックに書き戻す。

        `open(path, "w")` の直接書き戻しは truncate 中の読み取りで
        空/途中のファイルが見えるため使用しない。
        """
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(path), prefix=".transcript-", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.writelines(lines)
            os.replace(tmp_path, path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @classmethod
    def _remove_lines_from_file(cls, path: str, raw_lines: list[str]) -> bool:
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
            cls._atomic_write_lines(path, new_lines)
            return True
        except OSError:
            return False

    @classmethod
    def _remove_lines_from_file_by_ts(cls, path: str, timestamps: list[str]) -> bool:
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
            cls._atomic_write_lines(path, new_lines)
            return True
        except OSError:
            return False

    @staticmethod
    def _get_file_size(path: str) -> int:
        """ファイルサイズを返す（存在しない場合は0）"""
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _reset_watch_offsets(self, watched: list[tuple[str, str | None]],
                             offset_paths: list[str]) -> None:
        """ファイル書き換え後に FileWatcher オフセットと translate_offset を現サイズへリセットする。

        watched: [(file_type, path)] — FileWatcher の追跡オフセットを合わせる対象
        offset_paths: `.translate_offset` を現ファイルサイズに更新する transcript パス
        """
        for ftype, fpath in watched:
            if fpath is None:
                continue
            fkey = (ftype, fpath)
            if self.file_watcher and fkey in self.file_watcher._file_offsets:
                self.file_watcher._file_offsets[fkey] = self._get_file_size(fpath)
        for p in offset_paths:
            offset_file = p + ".translate_offset"
            if os.path.exists(offset_file):
                try:
                    with open(offset_file, "w", encoding="utf-8") as f:
                        f.write(str(self._get_file_size(p)))
                except OSError:
                    pass

    @staticmethod
    def _is_only_markers(lines: list[str]) -> bool:
        """行リストが空またはマーカー行・空行のみか判定"""
        marker_re = re.compile(r"^---\s.*\s---\s*$")
        return all(marker_re.match(line.strip()) or not line.strip() for line in lines)

    def _check_and_cleanup_empty_transcript(self, t_path: str) -> list[str]:
        """transcript が空またはマーカー行のみの場合、関連ファイルごと削除。削除ファイル名リスト返却。"""
        if not os.path.exists(t_path):
            return []
        try:
            with open(t_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return []
        if not self._is_only_markers(lines):
            return []
        tn = TranscriptName.parse(os.path.basename(t_path))
        return self._cleanup_transcript_files(t_path, tn)

    def _trigger_auto_jobs_for_meetings(
        self, meeting_paths: list[str], *, is_new: bool,
    ) -> None:
        """会議ファイルに対して自動要約・翻訳をバックグラウンドで起動。

        is_new=True: 新規切り出し → auto_summary / auto_translate 設定に従う
        is_new=False: 既存会議へのマージ → 既存サマリー/翻訳ファイルがあれば更新
        """
        config = load_config()
        lang = config.get("translate_language", "ja")

        jobs: list[tuple[str, bool, bool]] = []  # (path, do_summary, do_translate)
        for mp in meeting_paths:
            _tn = TranscriptName.parse(os.path.basename(mp))
            if not _tn:
                continue
            output_dir = os.path.dirname(mp)
            if is_new:
                do_summary = bool(config.get("auto_summary"))
                do_translate = bool(config.get("auto_translate"))
            else:
                do_summary = os.path.exists(os.path.join(output_dir, _tn.summary_filename))
                do_translate = os.path.exists(
                    os.path.join(output_dir, _tn.translation_filename(lang)))
            if do_summary or do_translate:
                jobs.append((mp, do_summary, do_translate))

        if not jobs:
            return

        def _worker() -> None:
            for mp, do_summary, do_translate in jobs:
                # 翻訳を先に実行（summary_source=translate の場合に必要）
                if do_translate:
                    try:
                        with open(mp + ".translate_offset", "w", encoding="utf-8") as f:
                            f.write("0")
                    except OSError:
                        pass
                    # 専用の stop イベントを渡す: ユーザーが translate_stop した後でも
                    # 会議切り出しの自動翻訳は独立して動くようにする
                    self.recorder._translate_loop(mp, threading.Event())
                if do_summary:
                    self.recorder._auto_summarize(mp)

        logger.info("自動ジョブ起動: %d 件 (is_new=%s)", len(jobs), is_new)
        threading.Thread(target=_worker, name="auto-jobs", daemon=True).start()

    def _serve_config(self) -> None:
        self._send_json(load_config())

    def _serve_models(self) -> None:
        """GET /api/models — api_endpoint から利用可能なモデル一覧を取得"""
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

    def _save_config(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
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
        from shadow_clerk import CONFIG_FILE
        # FileWatcher が毎秒 config を読むため、truncate 中の部分 YAML を
        # 読ませないよう一時ファイル → os.replace でアトミックに書く
        self._atomic_write_lines(
            CONFIG_FILE,
            [yaml.dump(config, default_flow_style=False, allow_unicode=True)])
        logger.info("ダッシュボードから設定変更")
        self._send_json(config)

    def _serve_glossary(self) -> None:
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

    def _rename_meeting(self) -> None:
        """POST /api/transcript/rename-meeting
        { file: "transcript-YYYYMMDDHHMM[@old].txt", name: "新会議名" }
        transcript / translation(s) / summary / offset ファイルを一括リネームする。
        name が空文字の場合は ad-hoc 扱い（@suffix なし）。
        """
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length))
            file_param = os.path.basename(data.get("file", ""))
            new_name = sanitize_meeting_name(data.get("name", ""))
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            self.send_error(400)
            return

        # meeting ファイル（HHMM 付き）のみ対象
        old_tn = TranscriptName.parse(file_param)
        if not old_tn or not old_tn.is_meeting_file:
            self._send_json({"status": "error", "message": "Not a meeting file"})
            return

        output_dir = self.recorder._output_dir
        new_tn = old_tn.with_name(new_name or None)

        renamed = []
        errors = []

        def _rename(src_name, dst_name):
            src = os.path.join(output_dir, src_name)
            dst = os.path.join(output_dir, dst_name)
            if os.path.exists(src):
                try:
                    os.rename(src, dst)
                    renamed.append((src_name, dst_name))
                except OSError as e:
                    errors.append(str(e))

        for old_fname, new_fname in old_tn.rename_plan(new_tn, output_dir):
            _rename(old_fname, new_fname)

        if errors:
            self._send_json({"status": "error", "message": "; ".join(errors)})
            return

        new_transcript = new_tn.filename
        logger.info("会議リネーム: %s → %s (%d files)", file_param, new_transcript, len(renamed))
        self._send_json({"status": "ok", "new_file": new_transcript, "renamed": len(renamed)})

    def _serve_gcal_events(self):
        """GET /api/gcal-events — Google Calendar の直近イベント一覧を返す"""
        monitor = self.__class__.gcal_monitor
        if monitor is None:
            self._send_json({"enabled": False, "events": []})
            return
        self._send_json({"enabled": True, "events": monitor.get_upcoming_events()})

    def _save_glossary(self) -> None:
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

    def _serve_search(self) -> None:
        """GET /api/search — transcript/translation/summary 全文検索"""
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        def _p(key: str) -> str:
            return qs.get(key, [""])[0].strip()

        year = _p("year")
        month = _p("month").zfill(2) if _p("month") else ""
        day = _p("day").zfill(2) if _p("day") else ""
        hour = _p("hour").zfill(2) if _p("hour") else ""
        query = _p("query").lower()
        search_type = _p("type") or "all"

        if not query and not (year or month or day or hour):
            self._send_json({"results": []})
            return

        output_dir = self.recorder._output_dir
        try:
            all_files = sorted(os.listdir(output_dir), reverse=True)
        except OSError:
            self._send_json({"results": []})
            return

        results: list[dict] = []

        for f in all_files:
            tn = TranscriptName.parse(f)
            if tn is None:
                continue
            dt = tn.datetime_str
            if year and not dt.startswith(year):
                continue
            if month and dt[4:6] != month:
                continue
            if day and dt[6:8] != day:
                continue
            if hour and (len(dt) < 10 or dt[8:10] != hour):
                continue

            if not query:
                # 日付フィルタのみ: ファイル単位で1件返す
                results.append({
                    "file": f,
                    "line": 0,
                    "type": "transcript",
                    "display": _fmt_search_display(tn, 0),
                    "text": "",
                })
                continue

            # テキスト検索対象ファイルを列挙
            to_search: list[tuple[str, str]] = []
            if search_type in ("transcript", "all"):
                to_search.append(("transcript", f))
            if search_type in ("translation", "all"):
                stem = tn.stem
                for sf in all_files:
                    if re.match(r"^" + re.escape(stem) + r"-[a-z]{2,10}\.txt$", sf):
                        to_search.append(("translation", sf))
                        break
            if search_type in ("summary", "all"):
                to_search.append(("summary", tn.summary_filename))

            for ftype, fname in to_search:
                fpath = os.path.join(output_dir, fname)
                if not os.path.exists(fpath):
                    continue
                try:
                    with open(fpath, "r", encoding="utf-8") as fp:
                        for lineno, line in enumerate(fp, 1):
                            if query in line.lower():
                                results.append({
                                    "file": f,
                                    "line": lineno,
                                    "type": ftype,
                                    "display": _fmt_search_display(tn, lineno),
                                    "text": line.strip()[:120],
                                })
                                if len(results) >= 200:
                                    break
                except OSError:
                    continue
            if len(results) >= 200:
                break

        self._send_json({"results": results})


def _fmt_search_display(tn: TranscriptName, lineno: int) -> str:
    """検索結果の表示文字列を生成: YYYY-MM-DD[ HH:MM][ @name][ L{n}]"""
    dt = tn.datetime_str
    if len(dt) >= 12:
        date_part = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]} {dt[8:10]}:{dt[10:12]}"
    else:
        date_part = f"{dt[:4]}-{dt[4:6]}-{dt[6:8]}"
    if tn.meeting_name:
        date_part += f" @{tn.meeting_name}"
    return f"{date_part} L{lineno}" if lineno > 0 else date_part
