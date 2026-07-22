"""Shadow-clerk daemon: ダッシュボード 会議切り出し・沈黙分割エンドポイント"""
from __future__ import annotations
import json
import os
import re
from shadow_clerk.i18n import t
from shadow_clerk._daemon_config import load_config
from shadow_clerk._transcript_name import TranscriptName, sanitize_meeting_name


class _DashboardHandlerMeetingOps:
    """会議切り出し・沈黙分割（ミックスイン）"""

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
            name = sanitize_meeting_name(data.get("name") or "")
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
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
            self._atomic_write_lines(t_path, remaining)

            # 翻訳ファイルも同様に処理
            config = load_config()
            lang = config.get("translate_language", "ja")
            _src_tn = TranscriptName.parse(os.path.basename(t_path))
            _mtg_tn = TranscriptName.parse(meeting_name)
            tr_path = os.path.join(output_dir, _src_tn.translation_filename(lang)) if _src_tn else None
            meeting_tr_path = os.path.join(output_dir, _mtg_tn.translation_filename(lang)) if _mtg_tn else None
            # meeting_tr_path が None（会議ファイル名がパース不能）の場合は
            # open(None) で落とさず翻訳の移動をスキップする
            if tr_path and meeting_tr_path and os.path.exists(tr_path):
                self._extract_translation_lines(
                    tr_path, meeting_tr_path, start_ts, end_ts,
                    is_new=(target == "new"),
                )

        # FileWatcher オフセット・translate_offset リセット
        self._reset_watch_offsets(
            [("transcript", t_path), ("translation", tr_path)],
            [t_path, meeting_path])

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

    @classmethod
    def _extract_translation_lines(cls, tr_path: str, meeting_tr_path: str, start_ts: str, end_ts: str, is_new: bool = True) -> None:
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
        cls._atomic_write_lines(tr_path, remaining)

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
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
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
            # 行は all_lines の index とペアで保持し、最終的にセグメントへ入らなかった
            # 行（未確定 candidate・孤立発話・範囲外）をすべて元ファイルに残す
            if start_ts and end_ts:
                target_lines = [
                    (i, l) for i, l in enumerate(all_lines)
                    if (m := ts_pattern.match(l)) and start_ts <= m.group(1) <= end_ts
                ]
            else:
                target_lines = list(enumerate(all_lines))

            # 沈黙期間でセグメントに分割
            # ルール:
            #   - N分以上の沈黙後の最初の発話が会議開始候補 (candidate)
            #   - 候補中に1分超のギャップ → 候補失格 → idle
            #   - 候補開始から3分以上、1分以内ギャップが続いたら会議確定 (active)
            #   - active中: 3分以上の沈黙で会議終了
            CONFIRM_WINDOW_SEC = 3 * 60   # 確認ウィンドウ: 3分
            MAX_CANDIDATE_GAP_SEC = 60    # 候補中の最大ギャップ: 1分
            MEETING_END_SEC = 3 * 60      # 会議終了閾値: 3分

            segments: list[list[tuple[int, str]]] = []
            current_segment: list[tuple[int, str]] = []
            last_dt: datetime | None = None
            state = "idle"  # idle | candidate | active
            candidate_start_dt: datetime | None = None

            for idx, line in target_lines:
                m = ts_pattern.match(line)
                if not m:
                    if state in ("candidate", "active"):
                        current_segment.append((idx, line))
                    continue
                dt = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                if last_dt is None:
                    # ファイル先頭 → 会議開始候補
                    current_segment = [(idx, line)]
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
                            current_segment = [(idx, line)]
                            candidate_start_dt = dt
                            state = "candidate"
                    else:
                        current_segment.append((idx, line))
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
                            current_segment = [(idx, line)]
                            candidate_start_dt = dt
                            state = "candidate"
                    else:
                        current_segment.append((idx, line))
                else:  # idle
                    if gap >= min_silence_sec:
                        current_segment = [(idx, line)]
                        candidate_start_dt = dt
                        state = "candidate"
                last_dt = dt

            # active のまま終了した場合は保存（candidate は未確定のため破棄）
            if state == "active" and current_segment:
                segments.append(current_segment)

            if len(segments) < 2:
                self._send_json({"status": "error", "message": t("dash.extract_split_no_segments")})
                return

            # セグメントに採用されなかった行（未確定 candidate・孤立発話・範囲外）は
            # どのファイルにも書かれず消失しないよう、すべて元ファイルに残す
            consumed = {i for seg in segments for i, _ in seg}
            remaining_lines = [l for i, l in enumerate(all_lines) if i not in consumed]

            # 各セグメントを会議ファイルとして作成
            config = load_config()
            lang = config.get("translate_language", "ja")
            _src_tn = TranscriptName.parse(os.path.basename(t_path))
            created: list[str] = []

            for seg in segments:
                first_ts = next((ts_pattern.match(l).group(1) for _, l in seg if ts_pattern.match(l)), None)
                if not first_ts:
                    continue
                meeting_ts = first_ts.replace("-", "").replace(" ", "").replace(":", "")[:12]
                meeting_name = TranscriptName(meeting_ts, None).filename
                meeting_path = os.path.join(output_dir, meeting_name)
                with open(meeting_path, "w", encoding="utf-8") as f:
                    f.write("--- meeting start ---\n")
                    f.writelines(l for _, l in seg)
                    f.write("--- meeting end ---\n")
                created.append(meeting_name)

            # 元ファイルから分割済み行を削除（一時ファイル→rename で安全に書き戻し）
            self._atomic_write_lines(t_path, remaining_lines)

            # 翻訳ファイルを各セグメントのタイムスタンプ範囲で分割
            tr_path = os.path.join(output_dir, _src_tn.translation_filename(lang)) if _src_tn else None
            if tr_path and os.path.exists(tr_path):
                for meeting_name, seg in zip(created, segments):
                    seg_ts_list = [ts_pattern.match(l).group(1) for _, l in seg if ts_pattern.match(l)]
                    if not seg_ts_list:
                        continue
                    _mtg_tn = TranscriptName.parse(meeting_name)
                    meeting_tr_path = os.path.join(output_dir, _mtg_tn.translation_filename(lang)) if _mtg_tn else None
                    self._extract_translation_lines(tr_path, meeting_tr_path, min(seg_ts_list), max(seg_ts_list), is_new=True)

        # FileWatcher オフセット・translate_offset リセット
        # （縮小した元ファイルへの生バイト diff 配信・翻訳オフセットずれを防ぐ）
        self._reset_watch_offsets(
            [("transcript", t_path), ("translation", tr_path)], [t_path])

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

