"""Shadow-clerk daemon: ダッシュボード ファイル操作エンドポイント"""
# pylint: disable=duplicate-code  # POST ボディ解析・パス解決の定型は各ハンドラで共通形
from __future__ import annotations
import collections
import json
import logging
import os
import re
import tempfile
import threading
from shadow_clerk.i18n import t
from shadow_clerk._daemon_config import load_config
from shadow_clerk._transcript_name import TranscriptName

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
            old_offset = self._read_translate_offset(t_path)
            # transcript から行削除
            removed, old_lines = self._remove_lines_from_file(t_path, raw_lines)
            if not removed:
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

        # FileWatcher の SSE オフセットは新サイズに合わせる
        self._reset_watch_offsets(
            [("transcript", t_path), ("translation", tr_path)], [])
        # translate_offset は「削除した翻訳済みバイト分」だけ縮める。
        # 新サイズへのリセットだと未翻訳の末尾を翻訳済みと誤認しスキップするため
        if old_offset is not None:
            self._write_translate_offset(
                t_path, self._shrink_translate_offset(old_lines, removed, old_offset))

        # transcript がマーカー行・空行のみになった場合は関連ファイルごと削除
        cleaned = self._check_and_cleanup_empty_transcript(t_path)
        if cleaned:
            self._send_json({"status": "ok", "deleted": cleaned})
            return

        self._send_json({"status": "ok"})

    @staticmethod
    def _related_file_names(t_path: str, tn: TranscriptName | None,
                            all_files: set[str]) -> list[str]:
        """t_path に付随する関連ファイル（翻訳・summary・offset）の basename 一覧を返す。

        削除処理（_cleanup_transcript_files）と削除確認モーダルの表示で
        同じ集合を使い、「確認に出ていないファイルが消える」不一致を防ぐ。
        all_files はディレクトリ内ファイル名の集合。
        """
        base = os.path.basename(t_path)
        related: list[str] = []
        if tn:
            for f in sorted(all_files):
                if f != base and f.startswith(tn.stem + "-") and f.endswith(".txt"):
                    related.append(f)
            if tn.summary_filename in all_files:
                related.append(tn.summary_filename)
        offset_name = base + ".translate_offset"
        if offset_name in all_files:
            related.append(offset_name)
        return related

    def _cleanup_transcript_files(self, t_path: str, tn: TranscriptName | None) -> list[str]:
        """transcript ファイルと関連ファイルを削除し、削除ファイル名リストを返す。
        transcript 本体の削除に失敗した場合は空リストを返す。"""
        output_dir = os.path.dirname(t_path)
        try:
            all_files = set(os.listdir(output_dir))
        except OSError:
            all_files = set()
        deleted: list[str] = []
        try:
            os.remove(t_path)
            deleted.append(os.path.basename(t_path))
        except OSError:
            return []
        for name in self._related_file_names(t_path, tn, all_files):
            try:
                os.remove(os.path.join(output_dir, name))
                deleted.append(name)
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
            # マージ前の日次ファイルの翻訳進捗を記録（マージは並べ替え挿入のため
            # バイトオフセットの部分的な引き継ぎができない）
            old_daily_offset = self._read_translate_offset(daily_path)
            old_daily_size = self._get_file_size(daily_path)
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

        # マージは日次ファイルの途中に行を挿入するため、FileWatcher の SSE オフセットは
        # 新サイズに合わせる（無関係なバイト範囲の再配信を防ぐ）
        self._reset_watch_offsets(
            [("transcript", daily_path)] + [("translation", p) for p in merged_translations],
            [])
        # translate_offset: マージは並べ替えのため部分オフセットを引き継げない。
        # 追いついていた場合のみ新サイズ（翻訳ファイルも一緒にマージ済み＝翻訳済み）、
        # 追いついていなければ 0 から再翻訳（未翻訳末尾のスキップを避ける）
        if old_daily_offset is not None:
            self._write_translate_offset(
                daily_path,
                self._get_file_size(daily_path) if old_daily_offset >= old_daily_size else 0)

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
    def _remove_lines_from_file(cls, path: str, raw_lines: list[str]) -> tuple[list[int], list[str]]:
        """ファイルから完全一致する行を各1件ずつ削除する。

        (削除した旧インデックスのリスト, 削除前の全行リスト) を返す。
        1件も削除しなかった/エラー時は削除インデックスが空リスト。
        呼び出し側が translate_offset のバイト調整に旧行情報を使う。
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return [], []
        targets = collections.Counter(ln.rstrip("\n") + "\n" for ln in raw_lines)
        new_lines: list[str] = []
        removed: list[int] = []
        for i, line in enumerate(lines):
            if targets.get(line, 0) > 0:
                targets[line] -= 1
                removed.append(i)
                continue
            new_lines.append(line)
        if not removed:
            return [], lines
        try:
            cls._atomic_write_lines(path, new_lines)
        except OSError:
            return [], lines
        return removed, lines

    @staticmethod
    def _shrink_translate_offset(old_lines: list[str], removed_indices: list[int],
                                 old_offset: int) -> int:
        """行削除後の translate_offset（翻訳済み境界のバイト位置）を算出する。

        削除された行のうち旧オフセットより前（＝翻訳済み領域）にあった分の
        バイト数だけオフセットを縮める。単純に新ファイルサイズへリセットすると、
        削除時点で未翻訳だった末尾を「翻訳済み」と誤認して恒久的にスキップして
        しまうため、翻訳済み領域だけを正確に縮める。
        """
        removed = set(removed_indices)
        new_offset = old_offset
        pos = 0
        for i, line in enumerate(old_lines):
            blen = len(line.encode("utf-8"))
            if i in removed:
                if pos + blen <= old_offset:
                    new_offset -= blen
                elif pos < old_offset:  # オフセットが行の途中（通常起きない）
                    new_offset -= (old_offset - pos)
            pos += blen
        return max(0, new_offset)

    @staticmethod
    def _read_translate_offset(path: str) -> int | None:
        """path の .translate_offset を読む。ファイルがなければ None（翻訳未開始）。"""
        try:
            with open(path + ".translate_offset", "r", encoding="utf-8") as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _write_translate_offset(path: str, value: int) -> None:
        try:
            with open(path + ".translate_offset", "w", encoding="utf-8") as f:
                f.write(str(value))
        except OSError:
            pass

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
            if os.path.exists(p + ".translate_offset"):
                self._write_translate_offset(p, self._get_file_size(p))

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

