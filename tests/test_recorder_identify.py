"""録音中の声紋照合（会議内クラスタ → 表示ラベル）のテスト"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from collections.abc import Iterator

import numpy as np
import pytest

# ユーザーの config.yaml に左右されないよう空のデータディレクトリを使う
os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-identify-")

import shadow_clerk._daemon_recorder_transcribe as rec_mod  # noqa: E402
import shadow_clerk._daemon_voiceprint_clusters as cluster_mod  # noqa: E402
import shadow_clerk._daemon_voiceprint_match as match_mod  # noqa: E402
import shadow_clerk._daemon_voiceprint_store as store_mod  # noqa: E402
from shadow_clerk._daemon_recorder_transcribe import _RecorderTranscribeMixin  # noqa: E402
from shadow_clerk._daemon_voice_sidecar import read_voices  # noqa: E402
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore  # noqa: E402
from shadow_clerk.domain import TranscriptLine  # noqa: E402
from shadow_clerk.domain.voiceprint import PersonName, VoiceSample  # noqa: E402

D = 256
MTG = "transcript-202610231000.txt"


def _basis(i: int) -> np.ndarray:
    v = np.zeros(D, dtype=np.float32)
    v[i] = 1.0
    return v


def _near_alice() -> np.ndarray:
    return (0.8 * _basis(0) + 0.6 * _basis(100)).astype(np.float32)


class _Diarizer:
    """毎回 相手A と決まった埋め込みを返す"""

    def __init__(self) -> None:
        self.clusters: dict[str, list[np.ndarray]] = {}

    def bind_output(self, path: str) -> None:
        pass

    def identify_speaker(self, segment: np.ndarray) -> tuple[str, np.ndarray]:
        emb = _near_alice()
        self.clusters.setdefault("相手A", []).append(emb)
        return "相手A", emb

    def cluster_embeddings(self, label: str) -> list[np.ndarray]:
        return list(self.clusters.get(label, []))


class _Talk:
    active = False

    def is_suppressed(self, source: str) -> bool:
        return False

    def is_echo(self, *a: object) -> bool:
        return False

    def on_self_line(self, line: TranscriptLine) -> None:
        pass

    def on_other_line(self, line: TranscriptLine) -> None:
        pass


class _Rec(_RecorderTranscribeMixin):
    def __init__(self, out_dir: str) -> None:
        self.mute_mic = self.mute_monitor = False
        self._explicit_output = True
        self.output_path = os.path.join(out_dir, MTG)
        self.transcript_lock = threading.Lock()
        self.transcriber = type("_T", (), {"language": "ja", "transcribe": staticmethod(lambda seg: "これはテストです")})()
        self.word_replacer = type("_W", (), {"apply": staticmethod(lambda text, lang: text)})()
        self.talk = _Talk()
        self.pronounce = type("_P", (), {"offer": staticmethod(lambda *a: None)})()
        self.diarizer = _Diarizer()
        self.voiceprints = VoiceprintStore(os.path.join(out_dir, "voiceprints.json"))
        self._voiceprint_warned_path = None

    def say(self, n: int = 1) -> None:
        for i in range(n):
            self._process_transcribe_item(np.zeros(32000, dtype=np.float32), f"2026-10-23 10:00:0{i}", 0.0,
                                          "monitor", False, {"mic": "自分", "monitor": "相手"}, None)

    def labels(self) -> list[str | None]:
        with open(self.output_path, encoding="utf-8") as f:
            return [TranscriptLine.parse(ln).speaker_label for ln in f if ln.strip()]


def _config(**over: object) -> dict:
    return {"speaker_diarization": True, "speaker_enrollment": True, **over}


@pytest.fixture
def cfg(monkeypatch) -> Iterator[dict]:
    c = _config()
    for mod in (rec_mod, match_mod, store_mod, cluster_mod):
        monkeypatch.setattr(mod, "load_config", lambda: c)
    yield c


@pytest.fixture
def rec(tmp_path, cfg) -> _Rec:
    r = _Rec(str(tmp_path))
    r.voiceprints.add({PersonName("alice"): [VoiceSample(_basis(0), f"2026-10-01 10:00:0{i}", "t.txt")
                                             for i in range(3)],
                       PersonName("bob"): [VoiceSample(_basis(1), "2026-10-01 10:00:09", "t.txt")]})
    with open(os.path.join(str(tmp_path), "transcript-202610231000.attendees.json"), "w", encoding="utf-8") as f:
        json.dump({"attendees": ["alice"]}, f)
    return r


def test_recorder_writes_display_label_and_cluster(rec) -> None:
    rec.say(3)
    assert rec.labels() == ["相手A", "alice", "alice"]
    v = read_voices(rec.output_path)
    assert [(e.label, e.cluster, e.auto) for e in v] == [("相手A", "相手A", False), ("alice", "相手A", True),
                                                        ("alice", "相手A", True)]


def test_broken_store_falls_back_to_cluster_label(rec, caplog) -> None:
    with open(rec.voiceprints.path, "w", encoding="utf-8") as f:
        f.write("{broken")
    with caplog.at_level(logging.WARNING, logger="shadow-clerk"):
        rec.say(3)
    assert rec.labels() == ["相手A"] * 3
    assert [(e.label, e.cluster, e.auto) for e in read_voices(rec.output_path)] == [("相手A", "相手A", False)] * 3
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_enrollment_off_no_identification(rec, cfg) -> None:
    cfg["speaker_enrollment"] = False
    rec.say(3)
    assert rec.labels() == ["相手A"] * 3
    assert read_voices(rec.output_path) == []


def test_diarization_off_no_identification(rec, cfg) -> None:
    cfg["speaker_diarization"] = False
    rec.say(2)
    assert rec.labels() == [None, None]
