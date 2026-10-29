"""マイクの声から自分の声紋を取るテスト（daemon・音声デバイス不要。fixture は test_recorder_identify と共有）"""
from __future__ import annotations

import io
import json
import os

import numpy as np
import pytest

import shadow_clerk._daemon_dashboard_ops_voiceprints as ops_mod
import shadow_clerk._daemon_recorder_transcribe as rec_mod
from test_recorder_identify import _Rec, _basis, _near_alice, cfg  # noqa: F401
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import SELF_ENROLL_SEC, SELF_VOICEPRINT_INTERVAL_SEC
from shadow_clerk._daemon_dashboard_ops_voiceprints import _DashboardHandlerVoiceprintOps
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore
from shadow_clerk.domain.voiceprint import PersonName, SampleOrigin, VoiceSample

ME = PersonName("alice")


class _SelfRec(_Rec):
    def __init__(self, out_dir: str) -> None:
        super().__init__(out_dir)
        self._self_voiceprint_at = -SELF_VOICEPRINT_INTERVAL_SEC
        self._self_enroll_until = 0.0
        self.voice = _near_alice()
        self.diarizer.extract_embedding = lambda seg: self.voice

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


def _origins(store: VoiceprintStore) -> list[tuple[SampleOrigin, str]]:
    return [(s.origin, s.recorded_at) for s in store.samples(ME)]


def _enroll(rec: _SelfRec, n: int = 3) -> None:
    """「自分の声を登録」で基準を n 件取り、登録の時間と自動の間隔を過ぎるまで進める"""
    rec.start_self_enroll()
    for i in range(n):
        rec.speak(f"2026-10-23 09:00:0{i}")
    rec.now[0] += max(SELF_ENROLL_SEC, SELF_VOICEPRINT_INTERVAL_SEC)


def test_enroll_button_takes_every_utterance_as_baseline(rec) -> None:
    rec.speak("2026-10-23 08:59:00")  # 基準が無いうちは自動では取らない
    rec.start_self_enroll()
    rec.speak("2026-10-23 09:00:00")
    rec.voice = _basis(1)  # 登録中は照合しない（意図して話している）
    rec.speak("2026-10-23 09:00:05")
    rec.speak("2026-10-23 09:00:08", sec=1.0)  # 短い発話は取らない
    assert _origins(rec.voiceprints) == [(SampleOrigin.ENROLLED, "2026-10-23 09:00:00"),
                                        (SampleOrigin.ENROLLED, "2026-10-23 09:00:05")]
    assert json.load(open(rec.voiceprints.path, encoding="utf-8"))["people"]["alice"]["samples"][0]["origin"] == \
        "enroll"


def test_auto_sample_once_per_interval_after_baseline(rec) -> None:
    _enroll(rec)
    rec.speak("2026-10-23 10:00:00")
    rec.speak("2026-10-23 10:00:10")  # 間隔が空いていない
    rec.now[0] += SELF_VOICEPRINT_INTERVAL_SEC
    rec.speak("2026-10-23 10:01:10")
    got = [s for s in rec.voiceprints.samples(ME) if s.origin is SampleOrigin.MIC]
    assert [(s.recorded_at, s.source) for s in got] == [("2026-10-23 10:00:00", "transcript-202610231000.txt"),
                                                       ("2026-10-23 10:01:10", "transcript-202610231000.txt")]


def test_auto_sample_needs_enough_baseline(rec) -> None:
    _enroll(rec, n=2)
    rec.speak("2026-10-23 10:00:00")
    assert [o for o, _ in _origins(rec.voiceprints)] == [SampleOrigin.ENROLLED] * 2


@pytest.mark.parametrize("voice,others", [
    (_basis(1), {}),  # 自分の基準から遠い声（同じ部屋の人など）
    (_near_alice(), {"bob": _near_alice()}),  # 他の登録済みの人と区別がつかない
    (_basis(0), {"bob": _basis(0)}),
])
def test_auto_sample_skips_voices_that_are_not_mine(rec, voice, others) -> None:
    _enroll(rec)
    rec.voiceprints.add({PersonName(n): [VoiceSample(e, "2026-10-01 10:00:00", "t.txt")] for n, e in others.items()})
    rec.voice = voice
    rec.speak("2026-10-23 10:00:00")
    assert [o for o, _ in _origins(rec.voiceprints)] == [SampleOrigin.ENROLLED] * 3


def test_named_and_imported_voiceprints_count_as_baseline(rec) -> None:
    rec.voiceprints.add({ME: [VoiceSample(_near_alice(), f"2026-10-01 10:00:0{i}", "t.txt") for i in range(3)]})
    rec.speak("2026-10-23 10:00:00")
    assert _origins(rec.voiceprints)[-1] == (SampleOrigin.MIC, "2026-10-23 10:00:00")


@pytest.mark.parametrize("over", [{"self_name": ""}, {"self_name": "自分"}, {"speaker_enrollment": False},
                                  {"speaker_diarization": False}])
def test_no_enrollment_without_settings(rec, cfg, over) -> None:
    cfg.update(over)
    rec.start_self_enroll()
    rec.speak("2026-10-23 10:00:00")
    assert rec.voiceprints.people() == {}


def test_own_caps_do_not_push_out_other_origins(tmp_path, cfg) -> None:
    store = VoiceprintStore(str(tmp_path / "voiceprints.json"))
    store.add({ME: [VoiceSample(_basis(0), "2026-10-01 10:00:00", "t.txt"),
                    VoiceSample(_basis(0), "2026-10-02 10:00:00", "e.txt", origin=SampleOrigin.ENROLLED)]})
    for i in range(4):
        store.add_own_sample(ME, VoiceSample(_basis(0), f"2026-10-23 10:00:0{i}", "m.txt", origin=SampleOrigin.MIC), 2)
    assert [(s.origin, s.recorded_at) for s in store.samples(ME)] == [
        (SampleOrigin.HEARD, "2026-10-01 10:00:00"), (SampleOrigin.ENROLLED, "2026-10-02 10:00:00"),
        (SampleOrigin.MIC, "2026-10-23 10:00:02"), (SampleOrigin.MIC, "2026-10-23 10:00:03")]


class _VH(_DashboardHandlerVoiceprintOps):
    def __init__(self, rec: object) -> None:
        self.client_address = ("127.0.0.1", 1)
        self.headers = {"Content-Length": "2"}
        self.rfile = io.BytesIO(b"{}")
        self.recorder = rec
        self.sent: dict = {}

    def _send_json(self, d: dict) -> None:
        self.sent = d

    def _speaker_error(self, key: str) -> None:
        self.sent = {"status": "error", "message": t(key)}


@pytest.mark.parametrize("over,error", [({}, None), ({"self_name": "自分"}, "dash.vp_enroll_no_name"),
                                        ({"speaker_enrollment": False}, "dash.vp_enroll_off")])
def test_enroll_endpoint(rec, cfg, monkeypatch, over, error) -> None:
    cfg.update(over)
    monkeypatch.setattr(ops_mod, "load_config", lambda: cfg)
    h = _VH(rec)
    h._start_self_enroll()
    if error:
        assert h.sent["message"] == t(error) and rec._self_enroll_until == 0.0
    else:
        assert h.sent["seconds"] == int(SELF_ENROLL_SEC) and rec._self_enroll_until == rec.now[0] + SELF_ENROLL_SEC


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
