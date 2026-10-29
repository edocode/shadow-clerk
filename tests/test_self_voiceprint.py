"""マイクの声から自分の声紋を取るテスト（daemon・音声デバイス不要。fixture は test_recorder_identify と共有）"""
from __future__ import annotations

import json
import os

import numpy as np
import pytest

import shadow_clerk._daemon_recorder_transcribe as rec_mod
from test_recorder_identify import _Rec, _basis, _near_alice, cfg  # noqa: F401
from shadow_clerk._daemon_constants import SELF_VOICEPRINT_INTERVAL_SEC
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore
from shadow_clerk.domain.voiceprint import PersonName, SampleOrigin, VoiceSample

ME = PersonName("alice")


class _SelfRec(_Rec):
    def __init__(self, out_dir: str) -> None:
        super().__init__(out_dir)
        self._self_voiceprint_at = -SELF_VOICEPRINT_INTERVAL_SEC
        self.diarizer.extract_embedding = lambda seg: _near_alice()

    def _extract_command_body(self, text: str) -> None:
        return None

    def speak(self, ts: str, sec: float = 4.0) -> None:
        self._process_transcribe_item(np.zeros(int(16000 * sec), dtype=np.float32), ts, 0.0,
                                      "mic", False, {"mic": "自分", "monitor": "相手"}, None)


@pytest.fixture
def rec(tmp_path, cfg, monkeypatch) -> _SelfRec:
    cfg["self_name"] = ME.value
    now = [1000.0]
    monkeypatch.setattr(rec_mod.time, "monotonic", lambda: now[0])
    r = _SelfRec(str(tmp_path))
    r.now = now
    return r


def _mic(store: VoiceprintStore) -> list[VoiceSample]:
    return [s for s in store.samples(ME) if s.origin is SampleOrigin.MIC]


def test_mic_voice_enrolls_self_once_per_interval(rec) -> None:
    rec.speak("2026-10-23 10:00:00")
    rec.speak("2026-10-23 10:00:10")  # 間隔が空いていない
    rec.now[0] += SELF_VOICEPRINT_INTERVAL_SEC
    rec.speak("2026-10-23 10:01:10")
    got = _mic(rec.voiceprints)
    assert [(s.recorded_at, s.source) for s in got] == [("2026-10-23 10:00:00", "transcript-202610231000.txt"),
                                                       ("2026-10-23 10:01:10", "transcript-202610231000.txt")]
    assert json.load(open(rec.voiceprints.path, encoding="utf-8"))["people"]["alice"]["samples"][0]["origin"] == "mic"


@pytest.mark.parametrize("over", [{"self_name": ""}, {"self_name": "自分"}, {"speaker_enrollment": False},
                                  {"speaker_diarization": False}])
def test_no_enrollment_without_settings(rec, cfg, over) -> None:
    cfg.update(over)
    rec.speak("2026-10-23 10:00:00")
    assert rec.voiceprints.people() == {}


def test_short_utterance_is_skipped_without_using_the_interval(rec) -> None:
    rec.speak("2026-10-23 10:00:00", sec=1.0)
    rec.speak("2026-10-23 10:00:05")
    assert [s.recorded_at for s in _mic(rec.voiceprints)] == ["2026-10-23 10:00:05"]


def test_mic_cap_does_not_push_out_heard_samples(tmp_path, cfg) -> None:
    store = VoiceprintStore(str(tmp_path / "voiceprints.json"))
    store.add({ME: [VoiceSample(_basis(0), "2026-10-01 10:00:00", "t.txt")]})
    for i in range(4):
        store.add_mic_sample(ME, VoiceSample(_basis(0), f"2026-10-23 10:00:0{i}", "m.txt", origin=SampleOrigin.MIC), 2)
    got = store.samples(ME)
    assert [(s.origin, s.recorded_at) for s in got] == [
        (SampleOrigin.HEARD, "2026-10-01 10:00:00"), (SampleOrigin.MIC, "2026-10-23 10:00:02"),
        (SampleOrigin.MIC, "2026-10-23 10:00:03")]


def test_self_counts_as_attendee(tmp_path, cfg) -> None:
    """出席者の分かる会議でも、自分の名前は出席者外の上乗せを受けない"""
    r = _SelfRec(str(tmp_path))
    r.voiceprints.add({ME: [VoiceSample(_near_alice(), f"2026-10-01 10:00:0{i}", "t.txt") for i in range(3)]})
    with open(os.path.join(str(tmp_path), "transcript-202610231000.attendees.json"), "w", encoding="utf-8") as f:
        json.dump({"attendees": ["bob"]}, f)
    cfg.update(self_name=ME.value, voiceprint_high=1.5, voiceprint_non_attendee_penalty=0.6)
    r.say(3)
    assert r.labels() == ["相手A", "alice?", "alice?"]
    cfg["self_name"] = ""
    r.diarizer.clusters.clear()
    r.say(2)
    assert r.labels()[-1] == "相手A"
