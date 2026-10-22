"""Shadow-clerk daemon: ダッシュボード — 話者の名前付けと声紋"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

from shadow_clerk.i18n import t
from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_dashboard_base import read_local_json_body
from shadow_clerk._transcript_attendees import read_attendees
from shadow_clerk._daemon_naming_history import NamingHistoryError, append_history, mark_undone, read_history
from shadow_clerk._daemon_speaker_naming import (
    Decision, decide_assignment, line_target_picker, parse_assignment, relabel_lines_where, remap_offset,
    summarize_labels,
)
from shadow_clerk._daemon_speaker_names import SpeakerNameBook, SpeakerNameBookError
from shadow_clerk._daemon_voice_sidecar import (
    clear_auto, read_voices, relabeled_voice_lines_where, set_auto, voice_lines_without_label, voices_path,
)
from shadow_clerk._daemon_voiceprint_clusters import voiceprint_number
from shadow_clerk._daemon_voiceprint_store import StoreChange, VoiceprintStore, VoiceprintStoreError
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain.naming_history import NamingRecord
from shadow_clerk.domain.transcript_line import TranscriptLine
from shadow_clerk.domain.speaker import Speaker
from shadow_clerk.domain.speaker_group import GroupName, SpeakerEntry
from shadow_clerk.domain.voiceprint import PersonName, VoiceEntry, VoiceSample, tentative_name

logger = logging.getLogger("shadow-clerk")


@dataclass(frozen=True)
class EnrollOutcome:
    """_enroll の結果。added: 元のラベル → 足したサンプルの recorded_at、
    removed: 名前付け済みラベル（人）→ 外した recorded_at、counts: 人 → 足した件数"""

    added: dict[str, list[str]] = field(default_factory=dict)
    removed: dict[str, list[str]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


class _DashboardHandlerSpeakerOps:
    """GET /api/speakers, POST /api/speakers/assign, POST /api/speakers/undo,
    GET /api/voiceprints, POST /api/voiceprints/delete"""

    def _speaker_error(self, key: str) -> None:
        self._send_json({"status": "error", "message": t(key)})

    def _speaker_transcript_path(self, file_param: object) -> str | None:
        """transcript 本体（翻訳ファイル等ではない）で、実在するものだけ受け付ける"""
        if not isinstance(file_param, str) or not file_param:
            return None
        base = os.path.basename(file_param)
        if TranscriptName.parse(base) is None:
            return None
        path = os.path.join(self.recorder._output_dir, base)
        return path if os.path.isfile(path) else None

    def _is_active_transcript(self, path: str) -> bool:
        return os.path.basename(self.recorder.output_path or "") == os.path.basename(path)

    @staticmethod
    def _read_lines(path: str) -> list[str]:
        with open(path, "r", encoding="utf-8") as f:
            return f.readlines()

    @staticmethod
    def _translation_paths(t_path: str) -> list[str]:
        base = os.path.basename(t_path)
        d = os.path.dirname(t_path)
        return [os.path.join(d, f) for f in sorted(os.listdir(d))
                if (parsed := TranscriptName.parse_translation(f)) and parsed[0].filename == base]

    @staticmethod
    def _speaker_book(strict: bool = False) -> tuple[dict[str, SpeakerEntry], dict[str, str]]:
        """名前帳の (entries, groups)。読めないとき strict なら SpeakerNameBookError、でなければ空（読み取り専用の用途）"""
        try:
            book = SpeakerNameBook()
            return book.entries(), book.groups()
        except SpeakerNameBookError as e:
            if strict:
                raise
            logger.warning("名前帳を読めない: %s", e)
            return {}, {}

    @staticmethod
    def _has_summary(t_path: str) -> bool:
        tn = TranscriptName.parse(os.path.basename(t_path))
        return bool(tn) and os.path.isfile(os.path.join(os.path.dirname(t_path), tn.summary_filename))

    @staticmethod
    def _remember(decisions: Iterable[Decision]) -> None:
        """名前・グループ・個人区分を台帳に残す。生体情報ではないので enrollment に関係なく。失敗しても付け替えは済んでいる"""
        try:
            book = SpeakerNameBook()
            for d in decisions:
                book.set_entry(d.name, GroupName(d.group) if d.group else None, d.person)
        except (SpeakerNameBookError, OSError) as e:
            logger.warning("名前帳に残せない: %s", e)

    def _decide_one(self, raw: object) -> Decision | None:
        """1件の割り当てを名簿と照らして決める。不正・名簿が読めなければ応答済みにして None"""
        try:
            a = parse_assignment(raw)
        except ValueError:
            self._speaker_error("dash.speakers_invalid_name")
            return None
        try:
            entries, groups = self._speaker_book(strict=True)
        except SpeakerNameBookError:
            self._speaker_error("dash.speaker_book_error")
            return None
        return decide_assignment(a, entries, groups)

    def _serve_speakers(self) -> None:
        """GET /api/speakers?file= — 名前付けの対象ラベルと名前の候補"""
        params = parse_qs(urlparse(self.path).query)
        t_path = self._speaker_transcript_path(params.get("file", [None])[0])
        if t_path is None:
            self._speaker_error("dash.transcript_not_found")
            return
        samples: dict[str, int] = defaultdict(int)
        autos: dict[str, int] = defaultdict(int)  # 会議中の識別で付いた、まだ確認されていない行
        for v in read_voices(t_path):
            samples[v.label] += 1
            autos[v.label] += v.auto
        try:
            registered = list(VoiceprintStore().people())
        except VoiceprintStoreError:
            registered = []
        entries, groups = self._speaker_book()
        history_error = False
        try:
            history = read_history(t_path)
        except NamingHistoryError as e:
            logger.warning("名前付けの履歴を読めない: %s", e)
            history, history_error = [], True
        summaries = summarize_labels(self._read_lines(t_path))
        in_transcript = [s.label for s in summaries if s.named and not s.tentative]
        # 「alice?」の行は、確定したときに付く alice の台帳の値を見せる
        book = {s.label: entries.get(s.suggested or s.label) for s in summaries}
        self._send_json({
            "status": "ok",
            "labels": [{"label": s.label, "count": s.count, "example": s.example, "named": s.named,
                        "samples": samples[s.label], "tentative": s.tentative, "suggested": s.suggested or "",
                        "auto": autos[s.label],
                        "group": e.group if (e := book[s.label]) else "",
                        "person": e.person if e else True}
                       for s in summaries],
            "suggestions": list(dict.fromkeys(read_attendees(t_path) + in_transcript + sorted(entries) + registered)),
            "groups": sorted(groups),
            "active": self._is_active_transcript(t_path),
            "translating": self.recorder.is_translating(t_path),
            "enrollment": bool(load_config().get("speaker_enrollment", False)),
            "history": [{"id": r.id, "at": r.at, "label": r.label, "name": r.name, "person": r.person,
                         "lines": len(r.lines), "added": len(r.added), "undone": r.undone}
                        for r in reversed(history)],
            **({"history_error": True} if history_error else {}),
        })

    def _assign_speakers(self) -> None:
        """POST /api/speakers/assign — ラベルに名前（またはグループ・個人区分）を付け、声紋を付け替える"""
        data = read_local_json_body(self, "speakers")
        if data is None:
            return
        t_path = self._speaker_transcript_path(data.get("file"))
        if t_path is None:
            self._speaker_error("dash.transcript_not_found")
            return
        raw = data.get("mapping")
        if not isinstance(raw, dict):
            self._speaker_error("dash.speakers_invalid")
            return
        try:
            parsed = {label: parse_assignment(v) for label, v in raw.items()
                      if not (isinstance(v, str) and not v.strip())}
        except ValueError:
            self._speaker_error("dash.speakers_invalid_name")
            return
        try:  # 読めない名簿の既定値で個人区分を決めると、記録済みの選択に反して声紋を登録しかねない
            entries, groups = self._speaker_book(strict=True)
        except SpeakerNameBookError:
            self._speaker_error("dash.speaker_book_error")
            return
        # 確認: 名前は変えずに、識別で付いた行（auto）を声紋に足す。「alice?」は確認ではなく alice への名前付けで扱う
        auto_rows: dict[str, list[str]] = defaultdict(list)  # ラベル → 識別で付いた行のタイムスタンプ
        for v in read_voices(t_path):
            if v.auto:
                auto_rows[v.label].append(v.timestamp)
        auto_labels = set(auto_rows)
        confirmed = {label for label, a in parsed.items() if a.confirm and a.name.value == label
                     and label in auto_labels and tentative_name(label) is None}
        decided = {label: d for label, a in parsed.items()
                   if (d := decide_assignment(a, entries, groups)).changes(label, entries) or label in confirmed}
        if not decided:
            self._speaker_error("dash.speakers_nothing")
            return
        with self.recorder.transcript_lock:
            lines = self._read_lines(t_path)
            if self._is_active_transcript(t_path):
                self._speaker_error("dash.speakers_active")
                return
            if self.recorder.is_translating(t_path):
                self._speaker_error("dash.speakers_translating")
                return
            try:  # 読めない履歴に追記すると空とみなして上書きしてしまう
                read_history(t_path)
            except NamingHistoryError:
                self._speaker_error("dash.naming_history_error")
                return
            summaries = summarize_labels(lines)
            if not set(decided) <= {s.label for s in summaries}:
                self._speaker_error("dash.speakers_invalid")
                return
            named = {s.label for s in summaries if s.named}
            mapping = {label: d.name for label, d in decided.items() if d.name.value != label}
            changed = {label for label, d in decided.items() if d.changes(label, entries)}

            def pick(v: VoiceEntry) -> Decision | None:
                # 識別で付いた行は、人が名前を付け直したか確認したときだけ声紋に足す
                take = (v.label in mapping or v.label in confirmed) if v.auto else v.label in changed
                return decided.get(v.label) if take else None
            # 声紋を先に保存する。ストアが壊れていたら transcript には手を付けずに止める
            outcome = self._enroll(t_path, lines, pick, named)
            if outcome is None:
                self._speaker_error("dash.voiceprint_store_error")
                return
            try:
                renamed = self._apply_relabel(
                    t_path, lines,
                    lambda tl: mapping[tl.speaker_label].value if tl.speaker_label in mapping else None,
                    lambda e: mapping[e.label].value if e.label in mapping else None) if mapping else 0
                cleared = clear_auto(t_path, confirmed) if confirmed else 0  # 足せなかった行も確認済みにする
            except OSError as e:
                logger.error("名前を書き込めない: %s", e)
                self._speaker_error("dash.speakers_write_error")
                return
            parsed_lines = [p for ln in lines if (p := TranscriptLine.parse(ln))]
            message = " ".join(([t("dash.speakers_saved", count=renamed)] if renamed or not cleared else [])
                               + ([t("dash.speakers_auto_confirmed", count=cleared)] if cleared else []))
            # 確認は行を書き換えないので lines は空。取り消すと足した声紋が外れ、識別で付いた印が戻る
            relabeled = {label: [p.timestamp for p in parsed_lines if p.speaker_label == label] for label in mapping}
            try:  # 名前付け自体は済んでいる。履歴だけ残せなくても成功として返す
                append_history(t_path, [
                    NamingRecord.new(label, decided[label].name.value, decided[label].person, relabeled.get(label, []),
                                     outcome.added.get(label, []), outcome.removed.get(label, []),
                                     auto_rows.get(label, []))
                    for label in [*mapping, *sorted(confirmed)]])
            except (NamingHistoryError, OSError) as e:
                logger.error("名前付けの履歴を残せない: %s", e)
                message += " " + t("dash.naming_history_not_saved")
        self._remember(decided.values())
        self._send_json({"status": "ok", "renamed": renamed, "enrolled": outcome.counts,
                         "has_summary": self._has_summary(t_path), "message": message})

    def _assign_lines(self) -> None:
        """POST /api/speakers/assign-lines — 選んだ行だけ別の話者（人・会社名・役割名）に付け替える"""
        data = read_local_json_body(self, "speakers")
        if data is None:
            return
        t_path = self._speaker_transcript_path(data.get("file"))
        if t_path is None:
            self._speaker_error("dash.transcript_not_found")
            return
        raw_lines = data.get("lines")
        if (not isinstance(raw_lines, list) or not raw_lines
                or not all(isinstance(x, dict) and isinstance(x.get("ts"), str) and isinstance(x.get("label"), str)
                           for x in raw_lines)):
            self._speaker_error("dash.speakers_invalid")
            return
        targets = {(x["ts"], x["label"]) for x in raw_lines}
        if any(label in (Speaker.SELF.value, Speaker.CLAUDE.value) for _, label in targets):
            self._speaker_error("dash.speakers_invalid")
            return
        d = self._decide_one({k: data[k] for k in ("name", "group", "person") if k in data})
        if d is None:
            return
        pick_line = line_target_picker(targets, d.name.value)
        with self.recorder.transcript_lock:
            lines = self._read_lines(t_path)
            if self._is_active_transcript(t_path):
                self._speaker_error("dash.speakers_active")
                return
            if self.recorder.is_translating(t_path):
                self._speaker_error("dash.speakers_translating")
                return
            if relabel_lines_where(lines, pick_line)[1] == 0:
                self._speaker_error("dash.speakers_invalid")
                return
            named = {s.label for s in summarize_labels(lines) if s.named}
            outcome = self._enroll(t_path, lines, lambda v: d if (v.timestamp, v.label) in targets else None, named)
            if outcome is None:
                self._speaker_error("dash.voiceprint_store_error")
                return
            try:
                renamed = self._apply_relabel(t_path, lines, pick_line,
                                              lambda e: d.name.value if (e.timestamp, e.label) in targets else None)
            except OSError as e:
                logger.error("話者を書き込めない: %s", e)
                self._speaker_error("dash.speakers_write_error")
                return
        self._remember([d])
        self._send_json({"status": "ok", "renamed": renamed, "enrolled": outcome.counts,
                         "has_summary": self._has_summary(t_path),
                         "message": t("dash.speakers_relabel_saved", count=renamed)})

    def _enroll(self, t_path: str, lines: list[str], decide: Callable[[VoiceEntry], Decision | None],
                named: set[str]) -> EnrollOutcome | None:
        """付け替える行の埋め込みを、元の人から外し、新しいラベルが個人なら足す。ストアを読み書きできなければ None"""
        cfg = load_config()
        if not cfg.get("speaker_enrollment", False):
            return EnrollOutcome()
        min_sec = voiceprint_number(cfg, "voiceprint_min_sec")
        source = os.path.basename(t_path)
        # transcript に今もある行の埋め込みだけ（切り出しで移った行や書き換え済みの古い項目を除く）
        present = {(p.timestamp, p.speaker_label) for ln in lines if (p := TranscriptLine.parse(ln))}
        add: dict[PersonName, list[VoiceSample]] = defaultdict(list)
        remove: dict[str, set[tuple[str, str]]] = defaultdict(set)
        label_of: dict[tuple[str, tuple[str, str]], str] = {}  # (人, キー) → 元のラベル
        for v in read_voices(t_path):
            d = decide(v)
            if d is None or (v.timestamp, v.label) not in present:
                continue
            if v.label in named:
                remove[v.label].add((source, v.timestamp))
            if d.person and not v.no_enroll and (v.duration is None or v.duration >= min_sec):
                add[d.name].append(VoiceSample(v.embedding, v.timestamp, source))
                label_of[(d.name.value, (source, v.timestamp))] = v.label
        if not add and not remove:
            return EnrollOutcome()
        try:
            change = VoiceprintStore().update(dict(add), dict(remove))
        except (VoiceprintStoreError, OSError) as e:
            logger.error("声紋を保存できない: %s", e)
            return None
        # 履歴には実際に足した・外したものだけ残す。取り消しが、元々なかった声紋を作ったり、前からあった声紋を消したりしないように
        added: dict[str, list[str]] = defaultdict(list)
        for person, keys in change.added.items():
            for key in sorted(keys):
                added[label_of[(person, key)]].append(key[1])
        return EnrollOutcome(dict(added), {label: sorted(ts for _, ts in keys) for label, keys in change.removed.items()},
                             {p.value: len(s) for p, s in add.items()})

    def _apply_relabel(self, t_path: str, lines: list[str], pick_line: Callable[[TranscriptLine], str | None],
                       pick_voice: Callable[[VoiceEntry], str | None]) -> int:
        """transcript・翻訳・サイドカーのラベルを書き換え、書き換えた transcript の行数を返す"""
        new_lines, renamed = relabel_lines_where(lines, pick_line)
        old_offset = self._read_translate_offset(t_path)
        self._atomic_write_lines(t_path, new_lines)
        if old_offset is not None:
            self._write_translate_offset(t_path, remap_offset(lines, new_lines, old_offset))
        translations = self._translation_paths(t_path)
        for tr in translations:
            tr_lines, n = relabel_lines_where(self._read_lines(tr), pick_line)
            if n:
                self._atomic_write_lines(tr, tr_lines)
        # サイドカーも書き換える。残すと後で同じ 相手X が振られたとき古い人の声が混ざる
        voice_lines = relabeled_voice_lines_where(t_path, pick_voice)
        vp = voices_path(t_path)
        if voice_lines is not None and vp:
            self._atomic_write_lines(vp, voice_lines)
        self._reset_watch_offsets([("transcript", t_path)] + [("translation", p) for p in translations], [])
        return renamed

    def _undo_naming(self) -> None:
        """POST /api/speakers/undo — 名前付け 1 件を取り消す。今も付けた名前のままの行だけ元のラベルに戻し、
        足した声紋を外し、元の人から外した声紋を戻す（削除ボタンで消された人には戻さない）"""
        data = read_local_json_body(self, "speakers")
        if data is None:
            return
        t_path = self._speaker_transcript_path(data.get("file"))
        if t_path is None:
            self._speaker_error("dash.transcript_not_found")
            return
        record_id = data.get("id")
        if not isinstance(record_id, str) or not record_id:
            self._speaker_error("dash.speakers_invalid")
            return
        try:
            entries, _ = self._speaker_book(strict=True)
        except SpeakerNameBookError:
            self._speaker_error("dash.speaker_book_error")
            return
        with self.recorder.transcript_lock:
            if self._is_active_transcript(t_path):
                self._speaker_error("dash.speakers_active")
                return
            if self.recorder.is_translating(t_path):
                self._speaker_error("dash.speakers_translating")
                return
            try:
                rec = next((r for r in read_history(t_path) if r.id == record_id and not r.undone), None)
            except NamingHistoryError:
                self._speaker_error("dash.naming_history_error")
                return
            if rec is None:
                self._speaker_error("dash.speakers_invalid")
                return
            store = VoiceprintStore()
            try:
                people = store.people()
            except VoiceprintStoreError:
                self._speaker_error("dash.voiceprint_store_error")
                return
            lines = self._read_lines(t_path)
            targets = set(rec.lines)

            def pick_line(tl: TranscriptLine) -> str | None:
                return rec.label if tl.timestamp in targets and tl.speaker_label == rec.name else None
            reverted = {p.timestamp for ln in lines if (p := TranscriptLine.parse(ln)) and pick_line(p)}
            source = os.path.basename(t_path)
            # 名簿にもストアにもいない＝削除ボタンで消された人、noenroll＝塊の「消す」で消したサンプル。
            # 明示的に消した生体情報は戻さない。戻すのは既にあったデータなので speaker_enrollment には関係なく戻す
            entry = entries.get(rec.label)
            restore = [VoiceSample(v.embedding, v.timestamp, source) for v in read_voices(t_path)
                       if v.timestamp in reverted and v.timestamp in rec.removed and v.label == rec.name
                       and not v.no_enroll] \
                if (entry.person if entry else rec.label in people) else []
            remove = {rec.name: {(source, ts) for ts in rec.added}} if rec.added else {}
            try:
                change = store.update({PersonName(rec.label): restore} if restore else {}, remove) \
                    if remove or restore else StoreChange()
            except (VoiceprintStoreError, OSError) as e:
                logger.error("声紋を保存できない: %s", e)
                self._speaker_error("dash.voiceprint_store_error")
                return
            try:
                restored = self._apply_relabel(
                    t_path, lines, pick_line,
                    lambda e: rec.label if e.timestamp in targets and e.label == rec.name else None) if reverted else 0
                # 印を戻さないと、後のグループ変更などで確認していない行が声紋に足されてしまう
                if rec.auto_cleared:
                    set_auto(t_path, rec.label, set(rec.auto_cleared))
                mark_undone(t_path, rec.id)
            except (OSError, NamingHistoryError) as e:
                logger.error("取り消しを書き込めない: %s", e)
                self._speaker_error("dash.speakers_write_error")
                return
        removed, lost = len(change.removed.get(rec.name, ())), len(rec.added) - len(change.removed.get(rec.name, ()))
        given_back = len(change.added.get(rec.label, ()))
        message = " ".join([t("dash.naming_undone", label=rec.label, lines=restored, removed=removed)]
                           + ([t("dash.naming_undo_restored", count=given_back)] if given_back else [])
                           + ([t("dash.naming_undo_lost", count=lost)] if lost else []))
        self._send_json({"status": "ok", "restored_lines": restored, "removed_samples": removed,
                         "restored_samples": given_back, "lost_samples": lost,
                         "has_summary": self._has_summary(t_path), "message": message})

    def _serve_voiceprints(self) -> None:
        """GET /api/voiceprints — 登録済みの人と件数"""
        try:
            people = VoiceprintStore().people()
        except VoiceprintStoreError:
            self._speaker_error("dash.voiceprint_store_error")
            return
        self._send_json({"status": "ok", "people": [{"name": n, "count": c} for n, c in people.items()]})

    def _delete_voiceprint(self) -> None:
        """POST /api/voiceprints/delete — その人の声紋と名簿の名前と、各サイドカーに残る名前付きの埋め込みを全部消す"""
        data = read_local_json_body(self, "voiceprints")
        if data is None:
            return
        name = data.get("name")
        if not isinstance(name, str) or not name:
            self._speaker_error("dash.speakers_invalid")
            return
        try:
            deleted = VoiceprintStore().delete(name)
        except (VoiceprintStoreError, OSError):
            self._speaker_error("dash.voiceprint_store_error")
            return
        try:
            name_removed = SpeakerNameBook().remove(name)
        except (SpeakerNameBookError, OSError) as e:
            logger.warning("名前を名簿から消せない: %s", e)
            name_removed = False
        self._send_json({"status": "ok", "deleted": deleted, "name_removed": name_removed,
                         "sidecar_entries_removed": self._purge_sidecar_label(name)})

    def _purge_sidecar_label(self, name: str) -> int:
        """全サイドカーから name の埋め込みを消し、消した件数を返す"""
        removed = 0
        with self.recorder.transcript_lock:
            for f in sorted(os.listdir(self.recorder._output_dir)):
                if not f.endswith(".voices.jsonl"):
                    continue
                vp = os.path.join(self.recorder._output_dir, f)
                try:
                    kept = voice_lines_without_label(vp, name)
                    if kept is None:
                        continue
                    n = len(self._read_lines(vp)) - len(kept)
                    self._atomic_write_lines(vp, kept)
                    removed += n
                except OSError as e:
                    logger.error("サイドカーから声紋を消せない: %s", e)
        return removed
