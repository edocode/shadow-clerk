"""Shadow-clerk daemon: ダッシュボード 設定・用語集・検索・リネームエンドポイント"""
# pylint: disable=duplicate-code  # optional import ブロック・POST 解析の定型は共通形
from __future__ import annotations
import json
import logging
import os
import re
import urllib.parse
import urllib.request
import yaml
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import GLOSSARY_FILE, DEFAULT_CONFIG
from shadow_clerk._daemon_config import load_config
from shadow_clerk._transcript_name import TranscriptName, sanitize_meeting_name

try:
    from shadow_clerk.llm_client import load_dotenv as llm_load_dotenv
    _HAS_LLM_CLIENT = True
except ImportError:
    _HAS_LLM_CLIENT = False

logger = logging.getLogger("shadow-clerk")


class _DashboardHandlerConfigOps:
    """設定・用語集・検索・会議リネーム（ミックスイン）"""

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
