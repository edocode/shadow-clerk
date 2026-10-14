"""Shadow-clerk daemon: ダッシュボード — 話者の名前付けと声紋"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

from shadow_clerk.i18n import t
from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_dashboard_base import read_attendees, read_local_json_body
from shadow_clerk._daemon_speaker_naming import relabel_lines, remap_offset, summarize_labels
from shadow_clerk._daemon_speaker_names import SpeakerNameBook, SpeakerNameBookError
from shadow_clerk._daemon_voice_sidecar import (
    read_voices, relabeled_voice_lines, voice_lines_without_label, voices_path,
)
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore, VoiceprintStoreError
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain.transcript_line import TranscriptLine
from shadow_clerk.domain.voiceprint import PersonName, VoiceSample

logger = logging.getLogger("shadow-clerk")


class _DashboardHandlerSpeakerOps:
    """GET /api/speakers, POST /api/speakers/assign, GET /api/voiceprints, POST /api/voiceprints/delete"""

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

    def _serve_speakers(self) -> None:
        """GET /api/speakers?file= — 名前付けの対象ラベルと名前の候補"""
        params = parse_qs(urlparse(self.path).query)
        t_path = self._speaker_transcript_path(params.get("file", [None])[0])
        if t_path is None:
            self._speaker_error("dash.transcript_not_found")
            return
        samples: dict[str, int] = defaultdict(int)
        for v in read_voices(t_path):
            samples[v.label] += 1
        try:
            registered = list(VoiceprintStore().people())
        except VoiceprintStoreError:
            registered = []
        try:
            remembered = SpeakerNameBook().names()
        except SpeakerNameBookError as e:
            logger.warning("名前の名簿を読めない: %s", e)
            remembered = []
        summaries = summarize_labels(self._read_lines(t_path))
        in_transcript = [s.label for s in summaries if s.named]
        self._send_json({
            "status": "ok",
            "labels": [{"label": s.label, "count": s.count, "example": s.example, "named": s.named,
                        "samples": samples[s.label]} for s in summaries],
            "suggestions": list(dict.fromkeys(read_attendees(t_path) + in_transcript + remembered + registered)),
            "active": self._is_active_transcript(t_path),
            "translating": self.recorder.is_translating(t_path),
            "enrollment": bool(load_config().get("speaker_enrollment", False)),
        })

    def _assign_speakers(self) -> None:
        """POST /api/speakers/assign — ラベルに名前を付け、声紋に足す"""
        data = read_local_json_body(self, "speakers")
        if data is None:
            return
        t_path = self._speaker_transcript_path(data.get("file"))
        if t_path is None:
            self._speaker_error("dash.transcript_not_found")
            return
        raw = data.get("mapping")
        if not isinstance(raw, dict) or not all(isinstance(v, str) for v in raw.values()):
            self._speaker_error("dash.speakers_invalid")
            return
        try:
            mapping = {label: PersonName(name) for label, name in raw.items() if name.strip() and name.strip() != label}
        except ValueError:
            self._speaker_error("dash.speakers_invalid_name")
            return
        if not mapping:
            self._speaker_error("dash.speakers_nothing")
            return
        with self.recorder.transcript_lock:
            lines = self._read_lines(t_path)
            if self.recorder.is_translating(t_path):
                self._speaker_error("dash.speakers_translating")
                return
            summaries = summarize_labels(lines)
            if not set(mapping) <= {s.label for s in summaries}:
                self._speaker_error("dash.speakers_invalid")
                return
            named = {s.label for s in summaries if s.named}
            # 声紋を先に保存する。ストアが壊れていたら transcript には手を付けずに止める
            enrolled = self._enroll(t_path, lines, mapping, named)
            if enrolled is None:
                self._speaker_error("dash.voiceprint_store_error")
                return
            try:
                renamed = self._apply_names(t_path, lines, mapping)
            except OSError as e:
                logger.error("名前を書き込めない: %s", e)
                self._speaker_error("dash.speakers_write_error")
                return
        try:  # 名前は生体情報ではないので enrollment に関係なく覚える。失敗しても名前付けは済んでいる
            SpeakerNameBook().add(mapping.values())
        except (SpeakerNameBookError, OSError) as e:
            logger.warning("名前を名簿に足せない: %s", e)
        self._send_json({"status": "ok", "renamed": renamed, "enrolled": enrolled,
                         "message": t("dash.speakers_saved", count=renamed)})

    def _enroll(self, t_path: str, lines: list[str], mapping: dict[str, PersonName],
                named: set[str]) -> dict[str, int] | None:
        """名前付けしたラベルの埋め込みを声紋に足す（付け済みの名前の変更は元の人から移す）。ストアを読み書きできなければ None"""
        if not load_config().get("speaker_enrollment", False):
            return {}
        source = os.path.basename(t_path)
        # transcript に今もある行の埋め込みだけ（切り出しで移った行や書き換え済みの古い項目を除く）
        present = {(p.timestamp, p.speaker_label) for ln in lines if (p := TranscriptLine.parse(ln))}
        by_person: dict[PersonName, list[VoiceSample]] = defaultdict(list)
        moved: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for v in read_voices(t_path):
            if v.label in mapping and (v.timestamp, v.label) in present:
                by_person[mapping[v.label]].append(VoiceSample(v.embedding, v.timestamp, source))
                if v.label in named:
                    moved[v.label].add((source, v.timestamp))
        if not by_person:
            return {}
        try:
            VoiceprintStore().update(dict(by_person), dict(moved))
        except (VoiceprintStoreError, OSError) as e:
            logger.error("声紋を保存できない: %s", e)
            return None
        return {p.value: len(s) for p, s in by_person.items()}

    def _apply_names(self, t_path: str, lines: list[str], mapping: dict[str, PersonName]) -> int:
        """transcript・翻訳・サイドカーのラベルを名前に書き換え、書き換えた transcript の行数を返す"""
        new_lines, renamed = relabel_lines(lines, mapping)
        old_offset = self._read_translate_offset(t_path)
        self._atomic_write_lines(t_path, new_lines)
        if old_offset is not None:
            self._write_translate_offset(t_path, remap_offset(lines, new_lines, old_offset))
        translations = self._translation_paths(t_path)
        for tr in translations:
            tr_lines, n = relabel_lines(self._read_lines(tr), mapping)
            if n:
                self._atomic_write_lines(tr, tr_lines)
        # サイドカーも書き換える。残すと後で同じ 相手X が振られたとき古い人の声が混ざる
        voice_lines = relabeled_voice_lines(t_path, mapping)
        vp = voices_path(t_path)
        if voice_lines is not None and vp:
            self._atomic_write_lines(vp, voice_lines)
        self._reset_watch_offsets([("transcript", t_path)] + [("translation", p) for p in translations], [])
        return renamed

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
