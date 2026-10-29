"""声紋の書き出し・取り込みのテスト（daemon・音声デバイス不要。fixture は test_speaker_api と共有）"""
from __future__ import annotations

import json

import pytest

from test_speaker_api import _H, _vec, isolated, meeting  # noqa: F401
import shadow_clerk._daemon_voiceprint_clusters as cluster_mod
from shadow_clerk.i18n import t
from shadow_clerk._daemon_dashboard_ops_voiceprints import _DashboardHandlerVoiceprintOps
from shadow_clerk._daemon_speaker_diarization import EMBEDDING_MODEL
from shadow_clerk._daemon_speaker_names import SpeakerNameBook
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore
from shadow_clerk._util_voiceprints import cmd_voiceprints_export, cmd_voiceprints_import
from shadow_clerk.domain.speaker_group import GroupName
from shadow_clerk.domain.voiceprint import IMPORT_SOURCE, PersonName, SampleOrigin, SampleStatus, VoiceSample
from shadow_clerk.domain.voiceprint_export import VoiceprintExport

MTG2 = "transcript-202610101000@週次定例.txt"


class _VH(_DashboardHandlerVoiceprintOps, _H):
    pass


@pytest.fixture(autouse=True)
def cluster_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cluster_mod, "load_config", lambda: {})


def _call(method: str, body: object) -> dict:
    h = _VH(body)
    getattr(h, method)()
    return h.sent


def _seed() -> None:
    """alice は acme（色付き）、bob は名前帳に無い。alice の 1 件は除外中"""
    store, book = VoiceprintStore(), SpeakerNameBook()
    store.add({PersonName("alice"): [VoiceSample(_vec(i), f"2026-10-10 10:00:0{i}", MTG2) for i in range(3)],
               PersonName("bob"): [VoiceSample(_vec(9), "2026-10-10 10:00:09", MTG2)]})
    store.set_status("alice", {(MTG2, "2026-10-10 10:00:02")}, SampleStatus.OUTLIER)
    book.ensure_group(GroupName("acme"), "#123456")
    book.set_entry(PersonName("alice"), GroupName("acme"), True)


def _export(names: list[str]) -> dict:
    sent = _call("_export_voiceprints", {"names": names})
    assert sent["status"] == "ok", sent
    return sent


def _receive() -> None:
    """取り込む側に作り直す（書き出した側のデータを消す）"""
    VoiceprintStore().delete("alice")
    VoiceprintStore().delete("bob")
    SpeakerNameBook().remove("alice")


def test_export_skips_outliers_meeting_names_and_people_without_voiceprints() -> None:
    _seed()
    sent = _export(["alice", "bob", "nobody"])
    data = sent["data"]
    assert sent["filename"].startswith("voiceprints-") and sent["message"] == t("dash.vp_exported", count=2)
    assert data["model"] == EMBEDDING_MODEL and "週次定例" not in json.dumps(data, ensure_ascii=False)
    people = {p["name"]: p for p in data["people"]}
    assert set(people) == {"alice", "bob"}
    assert [s["recorded_at"] for s in people["alice"]["samples"]] == ["2026-10-10 10:00:00", "2026-10-10 10:00:01"]
    assert (people["alice"]["group"], people["alice"]["color"], people["bob"]["group"]) == ("acme", "#123456", "")


def test_export_requires_someone_with_voiceprints() -> None:
    assert _call("_export_voiceprints", {"names": ["nobody"]})["message"] == t("dash.vp_export_none")
    assert _call("_export_voiceprints", {"names": []})["status"] == "error"


def test_import_new_person_brings_group_and_color() -> None:
    _seed()
    data = _export(["alice"])["data"]
    _receive()
    sent = _call("_import_voiceprints", {"data": data, "mapping": {"alice": "alice"}})
    assert sent["status"] == "ok" and sent["added"] == {"alice": 2}
    assert sent["message"] == t("dash.vp_imported", people=1, count=2)
    got = VoiceprintStore().samples(PersonName("alice"))
    assert {(s.source, s.origin) for s in got} == {(IMPORT_SOURCE, SampleOrigin.IMPORTED)}
    book = SpeakerNameBook()
    assert book.entries()["alice"].group == "acme" and book.groups()["acme"] == "#123456"
    # 同じファイルをもう一度取り込んでも増えない
    assert _call("_import_voiceprints", {"data": data, "mapping": {"alice": "alice"}})["added"] == {"alice": 0}


def test_import_renamed_into_existing_person_keeps_their_group() -> None:
    _seed()
    data = _export(["alice", "bob"])["data"]
    _receive()
    VoiceprintStore().add({PersonName("アリス"): [VoiceSample(_vec(50), "2026-10-20 10:00:00", MTG2)]})
    SpeakerNameBook().set_entry(PersonName("アリス"), GroupName("自社"), True)
    sent = _call("_import_voiceprints", {"data": data, "mapping": {"alice": "アリス"}})  # bob は選ばない
    assert sent["added"] == {"アリス": 2}
    assert VoiceprintStore().people() == {"アリス": 3}
    assert SpeakerNameBook().entries()["アリス"].group == "自社"


def test_import_refuses_other_model_bad_names_and_broken_files() -> None:
    _seed()
    data = _export(["alice"])["data"]
    _receive()
    other = {**data, "model": "other/model.onnx"}
    assert _call("_import_voiceprints", {"data": other, "mapping": {"alice": "alice"}})["message"] == \
        t("dash.vp_import_model", model="other/model.onnx")
    assert _call("_import_voiceprints", {"data": data, "mapping": {"alice": "相手A"}})["message"] == \
        t("dash.vp_import_bad_name", name="相手A")
    assert _call("_import_voiceprints", {"data": {"format": "x"}, "mapping": {"alice": "a"}})["message"] == \
        t("dash.vp_import_invalid")
    assert VoiceprintStore().people() == {}


def test_domain_rejects_duplicate_names_and_bad_colors() -> None:
    _seed()
    data = _export(["alice"])["data"]
    with pytest.raises(ValueError):
        VoiceprintExport.parse({**data, "people": data["people"] * 2})
    exp = VoiceprintExport.parse({**data, "people": [{**data["people"][0], "color": "red;"}]})
    assert exp.people[0].color == "" and exp.people[0].group == "acme"
    assert VoiceprintExport.parse(exp.to_dict()).people[0].samples[0][1] == "2026-10-10 10:00:00"


def test_cli_export_and_import_with_rename(tmp_path, capsys) -> None:
    _seed()
    out = str(tmp_path / "vp.json")
    cmd_voiceprints_export([out])  # 名前を省くと声紋のある全員
    assert {p["name"] for p in json.load(open(out, encoding="utf-8"))["people"]} == {"alice", "bob"}
    _receive()
    cmd_voiceprints_import([out, "alice=アリス"])
    assert VoiceprintStore().people() == {"アリス": 2} and "アリス: +2" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cmd_voiceprints_import([out, "carol"])
    assert VoiceprintStore().people() == {"アリス": 2}
