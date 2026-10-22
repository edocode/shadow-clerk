"""Shadow-clerk daemon: ダッシュボード — 登録済みの人の声紋の塊（表示・消す・移す・戻す）"""
from __future__ import annotations

import logging
import os
from collections import defaultdict
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from shadow_clerk.i18n import t
from shadow_clerk._daemon_dashboard_base import read_local_json_body
from shadow_clerk._daemon_naming_history import NamingHistoryError, read_history
from shadow_clerk._daemon_speaker_naming import relabel_lines_where
from shadow_clerk._daemon_voice_sidecar import mark_no_enroll
from shadow_clerk._daemon_voiceprint_clusters import cluster_samples, majority_shape
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore, VoiceprintStoreError
from shadow_clerk.domain.transcript_line import TranscriptLine
from shadow_clerk.domain.voiceprint import PersonName, SampleStatus, VoiceEntry

logger = logging.getLogger("shadow-clerk")

_EXAMPLE_KEYS = 20  # 発言例を探すのは塊の先頭からこの件数のキーまで


def _parse_keys(raw: object) -> set[tuple[str, str]] | None:
    """[[source, recorded_at], ...]（空でない）。形が違えば None"""
    if not isinstance(raw, list) or not raw or not all(
            isinstance(k, list) and len(k) == 2 and all(isinstance(x, str) for x in k) for k in raw):
        return None
    return {(k[0], k[1]) for k in raw}


def _timestamps_by_source(keys: set[tuple[str, str]] | list[tuple[str, str]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = defaultdict(set)
    for source, ts in keys:
        out[os.path.basename(source)].add(ts)
    return dict(sorted(out.items()))


def _relabel_pickers(timestamps: set[str], old: str, new: str
                     ) -> tuple[Callable[[TranscriptLine], str | None], Callable[[VoiceEntry], str | None]]:
    """ts ∈ timestamps で今も old のままの transcript 行・サイドカー行だけ new にする"""
    return (lambda tl: new if tl.timestamp in timestamps and tl.speaker_label == old else None,
            lambda e: new if e.timestamp in timestamps and e.label == old else None)


class _DashboardHandlerVoiceprintOps:
    """GET /api/voiceprints/clusters, POST /api/voiceprints/delete-samples,
    POST /api/voiceprints/move, POST /api/voiceprints/restore"""

    def _voiceprint_request(self) -> tuple[str, set[tuple[str, str]], dict] | None:
        """{name, keys} を読む。不正なら応答済みにして None"""
        data = read_local_json_body(self, "voiceprints")
        if data is None:
            return None
        keys = _parse_keys(data.get("keys"))
        try:
            name = PersonName(data.get("name")).value
        except ValueError:
            name = None
        if name is None or keys is None:
            self._speaker_error("dash.speakers_invalid")
            return None
        return name, keys, data

    def _line_texts(self, source: str, name: str) -> dict[str, str]:
        """source の transcript で name の行の、時刻 → 一番長い本文。transcript が無ければ空"""
        t_path = self._speaker_transcript_path(source)
        out: dict[str, str] = {}
        for ln in self._read_lines(t_path) if t_path else []:
            if (tl := TranscriptLine.parse(ln)) and tl.speaker_label == name and len(tl.text) > len(out.get(tl.timestamp, "")):
                out[tl.timestamp] = tl.text
        return out

    def _history_labels(self, source: str, name: str, timestamps: set[str]) -> list[str]:
        """名前付け履歴から分かる、そのサンプルを name に足したときの元のラベル。履歴が無い・読めなければ空"""
        try:
            records = read_history(os.path.join(self.recorder._output_dir, source))
        except NamingHistoryError as e:
            logger.warning("名前付けの履歴を読めない: %s", e)
            return []
        return sorted({r.label for r in records if r.name == name and not r.undone and timestamps & set(r.added)})

    def _serve_voiceprint_clusters(self) -> None:
        """GET /api/voiceprints/clusters?name= — その人の声紋の塊と、塊ごとの件数・出どころ・発言例"""
        try:
            name = PersonName(parse_qs(urlparse(self.path).query).get("name", [""])[0])
        except ValueError:
            self._speaker_error("dash.speakers_invalid")
            return
        try:
            samples = VoiceprintStore().samples(name)
        except VoiceprintStoreError:
            self._speaker_error("dash.voiceprint_store_error")
            return
        samples = [samples[i] for i in majority_shape([s.embedding for s in samples])]
        texts: dict[str, dict[str, str]] = {}  # source → 時刻 → 本文（会議ごとに 1 回だけ読む）

        def text_at(source: str, ts: str) -> str:
            if (base := os.path.basename(source)) not in texts:
                texts[base] = self._line_texts(base, name.value)
            return texts[base].get(ts, "")

        clusters = []
        for c in cluster_samples([s.embedding for s in samples]):
            members = [samples[i] for i in c.members]
            by_source = _timestamps_by_source([s.key for s in members])
            examples = [text_at(*s.key) for s in members[:_EXAMPLE_KEYS]]
            clusters.append({
                "kind": c.kind.value, "count": len(members), "similarity": round(c.similarity, 3),
                "keys": [list(s.key) for s in members],
                "sources": [{"file": f, "count": len(ts), "labels": self._history_labels(f, name.value, ts)}
                            for f, ts in by_source.items()],
                "example": max(examples, key=len, default=""),
            })
        self._send_json({"status": "ok", "name": name.value, "clusters": clusters})

    def _delete_voiceprint_samples(self) -> None:
        """POST /api/voiceprints/delete-samples — ストアからだけ外す。文字起こしは元の人の名前のまま。
        その声がサイドカーから再び声紋に入らないよう、各サイドカーの該当行に印を付ける"""
        req = self._voiceprint_request()
        if req is None:
            return
        name, keys, _ = req
        try:
            removed = VoiceprintStore().remove_samples(name, keys)
        except (VoiceprintStoreError, OSError):
            self._speaker_error("dash.voiceprint_store_error")
            return
        with self.recorder.transcript_lock:
            for source, ts in _timestamps_by_source(keys).items():
                try:
                    mark_no_enroll(os.path.join(self.recorder._output_dir, source), name, ts)
                except OSError as e:
                    logger.error("サイドカーに印を付けられない: %s", e)
        self._send_json({"status": "ok", "removed": removed, "message": t("dash.vp_deleted_samples", count=removed)})

    def _move_voiceprint_samples(self) -> None:
        """POST /api/voiceprints/move — サンプルを別の人へ移し、今も元の人の名前のままの該当行を書き換える。
        記録中・翻訳中の会議は書き換えずに数える（声紋は移す）"""
        req = self._voiceprint_request()
        if req is None:
            return
        name, keys, data = req
        d = self._decide_one(data.get("to"))
        if d is None:
            return
        if not d.person:
            self._speaker_error("dash.vp_move_not_person")
            return
        if d.name.value == name:
            self._speaker_error("dash.speakers_invalid")
            return
        try:
            moved = VoiceprintStore().move_samples(name, d.name, keys)
        except (VoiceprintStoreError, OSError):
            self._speaker_error("dash.voiceprint_store_error")
            return
        relabeled = skipped = 0
        for source, ts in _timestamps_by_source(keys).items():
            t_path = self._speaker_transcript_path(source)
            if t_path is None:  # 会議ファイルが消えている。声紋だけ移す
                continue
            pick_line, pick_voice = _relabel_pickers(ts, name, d.name.value)
            with self.recorder.transcript_lock:
                if self._is_active_transcript(t_path) or self.recorder.is_translating(t_path):
                    skipped += 1
                    continue
                lines = self._read_lines(t_path)
                if relabel_lines_where(lines, pick_line)[1] == 0:
                    continue
                try:
                    relabeled += self._apply_relabel(t_path, lines, pick_line, pick_voice)
                except OSError as e:
                    logger.error("移した話者を書き込めない: %s", e)
                    self._speaker_error("dash.speakers_write_error")
                    return
        self._remember([d])
        message = t("dash.vp_moved", count=moved, name=d.name.value, lines=relabeled)
        self._send_json({"status": "ok", "moved": moved, "relabeled_lines": relabeled, "skipped_files": skipped,
                         "message": f"{message} {t('dash.vp_move_skipped', count=skipped)}" if skipped else message})

    def _restore_voiceprint_samples(self) -> None:
        """POST /api/voiceprints/restore — 除外中のサンプルを照合に戻す。以後の自動判定で除外しない"""
        req = self._voiceprint_request()
        if req is None:
            return
        name, keys, _ = req
        try:
            restored = VoiceprintStore().set_status(name, keys, SampleStatus.KEPT)
        except (VoiceprintStoreError, OSError):
            self._speaker_error("dash.voiceprint_store_error")
            return
        self._send_json({"status": "ok", "restored": restored})
