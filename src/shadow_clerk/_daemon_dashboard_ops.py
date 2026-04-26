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
from shadow_clerk._transcript_name import TranscriptName

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
            _tn = TranscriptName.parse(os.path.basename(t_path))
            if _tn:
                tr_path = os.path.join(os.path.dirname(t_path), _tn.translation_filename(lang))
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
            tmp_fd, tmp_p = tempfile.mkstemp(dir=output_dir, prefix=".transcript-", suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    for b in blocks:
                        f.writelines(b)
                os.replace(tmp_p, dst)
            except BaseException:
                try:
                    os.unlink(tmp_p)
                except OSError:
                    pass
                raise

        with self.recorder.transcript_lock:
            # transcript 本体をマージ
            _merge_file(t_path, os.path.join(output_dir, daily_tn.filename))
            # 翻訳ファイルをマージ (transcript-YYYYMMDDHHMM[@name]-{lang}.txt → transcript-YYYYMMDD-{lang}.txt)
            for fname in os.listdir(output_dir):
                if fname.startswith(tn.stem + "-") and fname.endswith(".txt"):
                    lang = fname[len(tn.stem) + 1:-4]
                    if lang:
                        _merge_file(
                            os.path.join(output_dir, fname),
                            os.path.join(output_dir, daily_tn.translation_filename(lang)),
                        )

        deleted = self._cleanup_transcript_files(t_path, tn)
        if not deleted:
            self._send_json({"status": "error", "message": t("dash.merge_to_daily_error")})
            return
        self._send_json({"status": "ok", "deleted": deleted})

    def _extract_meeting(self) -> None:
        """POST /api/transcript/extract-meeting — タイムスタンプ範囲の行を会議ファイルへ移動"""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            file_param = data.get("file", "")
            start_ts = data.get("start_ts", "")
            end_ts = data.get("end_ts", "")
            target = data.get("target", "new")
            name = (data.get("name") or "").strip()
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

        with self.recorder.transcript_lock:
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
                meeting_ts = start_ts.replace("-", "").replace(" ", "").replace(":", "")[:12]
                meeting_name = TranscriptName(meeting_ts, name or None).filename
                meeting_path = os.path.join(output_dir, meeting_name)
                # 会議開始/終了マーカー付きで作成
                with open(meeting_path, "w", encoding="utf-8") as f:
                    f.write("--- meeting start ---\n")
                    f.writelines(extracted)
                    f.write("--- meeting end ---\n")
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

            # 日次 transcript から抽出行を削除（一時ファイル→rename で安全に書き戻し）
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=output_dir, prefix=".transcript-", suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.writelines(remaining)
                os.replace(tmp_path, t_path)
            except BaseException:
                # 書き込み失敗時は一時ファイルを削除
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            # 翻訳ファイルも同様に処理
            config = load_config()
            lang = config.get("translate_language", "ja")
            _src_tn = TranscriptName.parse(os.path.basename(t_path))
            _mtg_tn = TranscriptName.parse(meeting_name)
            tr_path = os.path.join(output_dir, _src_tn.translation_filename(lang)) if _src_tn else None
            meeting_tr_path = os.path.join(output_dir, _mtg_tn.translation_filename(lang)) if _mtg_tn else None
            if tr_path and os.path.exists(tr_path):
                self._extract_translation_lines(
                    tr_path, meeting_tr_path, start_ts, end_ts,
                    is_new=(target == "new"),
                )

        # FileWatcher オフセットリセット
        for ftype, fpath in [("transcript", t_path), ("translation", tr_path)]:
            if fpath is None:
                continue
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

        # 元ファイルがマーカー行・空行のみになった場合は関連ファイルごと削除
        source_deleted = self._check_and_cleanup_empty_transcript(t_path)

        # 自動要約・翻訳トリガー
        self._trigger_auto_jobs_for_meetings(
            [meeting_path], is_new=(target == "new"))

        resp: dict = {
            "status": "ok",
            "message": t("dash.extract_meeting_success", name=meeting_name),
        }
        if source_deleted:
            resp["source_deleted"] = source_deleted
        self._send_json(resp)

    @staticmethod
    def _merge_meeting_lines(existing: list[str], new_lines: list[str]) -> list[str]:
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
        def sort_key(line: str) -> str:
            m = ts_pattern.match(line)
            return m.group(1) if m else "9999"

        data_lines.sort(key=sort_key)

        # マーカーを先頭・末尾に付与して返す
        result = ["--- meeting start ---\n"]
        result.extend(data_lines)
        result.append("--- meeting end ---\n")
        return result

    @staticmethod
    def _extract_translation_lines(tr_path: str, meeting_tr_path: str, start_ts: str, end_ts: str, is_new: bool = True) -> None:
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

            def sort_key(line: str) -> str:
                m = ts_pattern.match(line)
                return m.group(1) if m else "9999"
            merged.sort(key=sort_key)
            with open(meeting_tr_path, "w", encoding="utf-8") as f:
                f.writelines(merged)

        # 元翻訳ファイルから抽出行を削除（一時ファイル→rename で安全に書き戻し）
        output_dir = os.path.dirname(tr_path)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=output_dir, prefix=".translate-", suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.writelines(remaining)
            os.replace(tmp_path, tr_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def _split_by_silence(self) -> None:
        """POST /api/transcript/split-by-silence — 沈黙期間で transcript を会議ファイルに分割"""
        from datetime import datetime
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            file_param = data.get("file", "")
            min_silence_minutes = float(data.get("min_silence_minutes", 1))
            start_ts = data.get("start_ts", "")
            end_ts = data.get("end_ts", "")
        except (json.JSONDecodeError, ValueError):
            self.send_error(400)
            return
        if not file_param or min_silence_minutes <= 0:
            self.send_error(400)
            return

        output_dir = self.recorder._output_dir
        t_path = os.path.join(output_dir, os.path.basename(file_param))
        if not os.path.exists(t_path):
            self._send_json({"status": "error", "message": t("dash.transcript_not_found")})
            return

        min_silence_sec = min_silence_minutes * 60
        ts_pattern = re.compile(r"^\[(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2})\]")

        with self.recorder.transcript_lock:
            try:
                with open(t_path, "r", encoding="utf-8") as f:
                    all_lines = f.readlines()
            except OSError:
                self._send_json({"status": "error", "message": t("dash.extract_split_error")})
                return

            # 対象範囲のフィルタリング（範囲指定なしは全行が対象）
            if start_ts and end_ts:
                target_lines = [l for l in all_lines if (m := ts_pattern.match(l)) and start_ts <= m.group(1) <= end_ts]
                remaining_lines = [l for l in all_lines if not (ts_pattern.match(l) and start_ts <= ts_pattern.match(l).group(1) <= end_ts)]
            else:
                target_lines = all_lines
                remaining_lines = []

            # 沈黙期間でセグメントに分割
            # ルール:
            #   - N分以上の沈黙後の最初の発話が会議開始候補 (candidate)
            #   - 候補中に1分超のギャップ → 候補失格 → idle
            #   - 候補開始から3分以上、1分以内ギャップが続いたら会議確定 (active)
            #   - active中: 3分以上の沈黙で会議終了
            CONFIRM_WINDOW_SEC = 3 * 60   # 確認ウィンドウ: 3分
            MAX_CANDIDATE_GAP_SEC = 60    # 候補中の最大ギャップ: 1分
            MEETING_END_SEC = 3 * 60      # 会議終了閾値: 3分

            segments: list[list[str]] = []
            current_segment: list[str] = []
            last_dt: datetime | None = None
            state = "idle"  # idle | candidate | active
            candidate_start_dt: datetime | None = None

            for line in target_lines:
                m = ts_pattern.match(line)
                if not m:
                    if state in ("candidate", "active"):
                        current_segment.append(line)
                    continue
                dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                if last_dt is None:
                    # ファイル先頭 → 会議開始候補
                    current_segment = [line]
                    candidate_start_dt = dt
                    state = "candidate"
                    last_dt = dt
                    continue
                gap = (dt - last_dt).total_seconds()
                if state == "candidate":
                    if gap > MAX_CANDIDATE_GAP_SEC:
                        # 1分超ギャップ → 候補失格
                        current_segment = []
                        candidate_start_dt = None
                        state = "idle"
                        if gap >= min_silence_sec:
                            current_segment = [line]
                            candidate_start_dt = dt
                            state = "candidate"
                    else:
                        current_segment.append(line)
                        if (dt - candidate_start_dt).total_seconds() >= CONFIRM_WINDOW_SEC:
                            state = "active"  # 3分以上継続 → 会議確定
                elif state == "active":
                    if gap >= MEETING_END_SEC:
                        # 3分以上沈黙 → 会議終了
                        segments.append(current_segment)
                        current_segment = []
                        candidate_start_dt = None
                        state = "idle"
                        if gap >= min_silence_sec:
                            current_segment = [line]
                            candidate_start_dt = dt
                            state = "candidate"
                    else:
                        current_segment.append(line)
                else:  # idle
                    if gap >= min_silence_sec:
                        current_segment = [line]
                        candidate_start_dt = dt
                        state = "candidate"
                last_dt = dt

            # active のまま終了した場合は保存（candidate は未確定のため破棄）
            if state == "active" and current_segment:
                segments.append(current_segment)

            if len(segments) < 2:
                self._send_json({"status": "error", "message": t("dash.extract_split_no_segments")})
                return

            # 各セグメントを会議ファイルとして作成
            config = load_config()
            lang = config.get("translate_language", "ja")
            _src_tn = TranscriptName.parse(os.path.basename(t_path))
            created: list[str] = []

            for seg in segments:
                first_ts = next((ts_pattern.match(l).group(1) for l in seg if ts_pattern.match(l)), None)
                if not first_ts:
                    continue
                meeting_ts = first_ts.replace("-", "").replace(" ", "").replace(":", "")[:12]
                meeting_name = TranscriptName(meeting_ts, None).filename
                meeting_path = os.path.join(output_dir, meeting_name)
                with open(meeting_path, "w", encoding="utf-8") as f:
                    f.write("--- meeting start ---\n")
                    f.writelines(seg)
                    f.write("--- meeting end ---\n")
                created.append(meeting_name)

            # 元ファイルから分割済み行を削除（一時ファイル→rename で安全に書き戻し）
            tmp_fd, tmp_path = tempfile.mkstemp(dir=output_dir, prefix=".transcript-", suffix=".tmp")
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    f.writelines(remaining_lines)
                os.replace(tmp_path, t_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            # 翻訳ファイルを各セグメントのタイムスタンプ範囲で分割
            tr_path = os.path.join(output_dir, _src_tn.translation_filename(lang)) if _src_tn else None
            if tr_path and os.path.exists(tr_path):
                for meeting_name, seg in zip(created, segments):
                    seg_ts_list = [ts_pattern.match(l).group(1) for l in seg if ts_pattern.match(l)]
                    if not seg_ts_list:
                        continue
                    _mtg_tn = TranscriptName.parse(meeting_name)
                    meeting_tr_path = os.path.join(output_dir, _mtg_tn.translation_filename(lang)) if _mtg_tn else None
                    self._extract_translation_lines(tr_path, meeting_tr_path, min(seg_ts_list), max(seg_ts_list), is_new=True)

        # 元ファイルがマーカー行・空行のみになった場合は関連ファイルごと削除
        source_deleted = self._check_and_cleanup_empty_transcript(t_path)

        # 自動要約・翻訳トリガー
        created_paths = [os.path.join(output_dir, name) for name in created]
        self._trigger_auto_jobs_for_meetings(created_paths, is_new=True)

        resp: dict = {
            "status": "ok",
            "message": t("dash.extract_split_success", count=len(created)),
        }
        if source_deleted:
            resp["source_deleted"] = source_deleted
        self._send_json(resp)

    @staticmethod
    def _remove_lines_from_file(path: str, raw_lines: list[str]) -> bool:
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
    def _remove_lines_from_file_by_ts(path: str, timestamps: list[str]) -> bool:
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
    def _get_file_size(path: str) -> int:
        """ファイルサイズを返す（存在しない場合は0）"""
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

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
                    self.recorder._translate_loop(mp)
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
        from shadow_clerk import CONFIG_FILE
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
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
            new_name = data.get("name", "").strip()
        except (json.JSONDecodeError, ValueError):
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
