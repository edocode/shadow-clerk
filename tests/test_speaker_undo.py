"""名前付けの履歴と取り消し API のテスト（daemon・音声デバイス不要。fixture は test_speaker_api と共有）"""
from __future__ import annotations

import sys

import pytest

from test_speaker_api import MTG, TR, _H, _Rec, _p, _read, _vec, isolated, meeting  # noqa: F401
from shadow_clerk.i18n import t
from shadow_clerk._daemon_voice_sidecar import append_voice, read_voices
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore
from shadow_clerk.domain.voiceprint import PersonName

HIST = "transcript-202610091000@週次定例.naming.jsonl"
A1, B1, B2 = "2026-10-09 10:00:01", "2026-10-09 10:00:02", "2026-10-09 10:00:06"


def _history(name: str = MTG) -> list[dict]:
    h = _H(path=f"/api/speakers?file={name}")
    h._serve_speakers()
    assert h.sent["status"] == "ok", h.sent
    return h.sent["history"]


def _rec_id(label: str, name: str = MTG) -> str:
    return next(r["id"] for r in _history(name) if r["label"] == label and not r["undone"])


def _undo(rec_id: str, name: str = MTG, rec: _Rec | None = None) -> dict:
    h = _H({"file": name, "id": rec_id}, rec=rec)
    h._undo_naming()
    return h.sent


def _keys(name: str) -> set[tuple[str, str]]:
    return {s.key for s in VoiceprintStore().samples(PersonName(name))}


def _assign(mapping: dict) -> dict:
    h = _H({"file": MTG, "mapping": mapping})
    h._assign_speakers()
    assert h.sent["status"] == "ok", h.sent
    return h.sent


def _second_b() -> None:
    with open(_p(MTG), "a", encoding="utf-8") as f:
        f.write(f"[{B2}] [相手B] もう一行\n")
    append_voice(_p(MTG), B2, "相手B", _vec(6))


def test_assign_records_history_per_label() -> None:
    _assign({"相手A": "alice", "相手B": "alice"})
    hist = _history()
    assert [(r["label"], r["name"], r["person"], r["lines"], r["added"], r["undone"]) for r in hist] == \
        [("相手B", "alice", True, 1, 1, False), ("相手A", "alice", True, 1, 1, False)]
    from shadow_clerk._daemon_naming_history import read_history
    recs = {r.label: r for r in read_history(_p(MTG))}
    assert recs["相手A"].lines == (A1,) and recs["相手A"].added == (A1,) and recs["相手A"].removed == ()
    assert recs["相手B"].lines == (B1,) and recs["相手B"].added == (B1,)


def test_history_is_newest_first() -> None:
    _assign({"相手A": "alice"})
    _assign({"相手B": "bob"})
    assert [r["label"] for r in _history()] == ["相手B", "相手A"]


def test_group_only_change_not_recorded() -> None:
    _assign({"相手A": "alice"})
    h = _H({"file": MTG, "mapping": {"alice": {"name": "alice", "group": "acme"}}})
    h._assign_speakers()
    assert h.sent["status"] == "ok" and h.sent["renamed"] == 0, h.sent
    assert len(_history()) == 1


def test_undo_restores_labels_and_removes_samples() -> None:
    with open(_p(TR), "a", encoding="utf-8") as f:
        f.write(f"[{B1}] [相手B] The material is shared\n")
    _assign({"相手A": "alice", "相手B": "alice"})
    r = _undo(_rec_id("相手B"))
    assert r["status"] == "ok", r
    assert (r["restored_lines"], r["removed_samples"], r["restored_samples"], r["lost_samples"]) == (1, 1, 0, 0)
    assert r["message"] == t("dash.naming_undone", label="相手B", lines=1, removed=1)
    assert "has_summary" in r
    assert "[相手B] 資料は共有済みです" in _read(MTG) and "[alice] 来週のリリースの件ですが" in _read(MTG)
    assert "[相手B] The material is shared" in _read(TR) and "[alice] About next week's release" in _read(TR)
    assert [e.label for e in read_voices(_p(MTG))] == ["alice", "相手B", "相手C"]
    assert _keys("alice") == {(MTG, A1)}
    assert [x["undone"] for x in _history() if x["label"] == "相手B"] == [True]
    _assign({"相手B": "bob"})
    assert "[bob] 資料は共有済みです" in _read(MTG) and _keys("bob") == {(MTG, B1)}


def test_undo_skips_lines_moved_later() -> None:
    _second_b()
    _assign({"相手B": "alice"})
    h = _H({"file": MTG, "lines": [{"ts": B2, "label": "alice"}], "name": "bob"})
    h._assign_lines()
    assert h.sent["status"] == "ok", h.sent
    r = _undo(_rec_id("相手B"))
    assert r["status"] == "ok" and r["restored_lines"] == 1 and r["removed_samples"] == 1, r
    assert r["lost_samples"] == 1
    body = _read(MTG)
    assert "[相手B] 資料は共有済みです" in body and "[bob] もう一行" in body
    assert [(e.timestamp, e.label) for e in read_voices(_p(MTG))][-1] == (B2, "bob")
    assert VoiceprintStore().people() == {"bob": 1} and _keys("bob") == {(MTG, B2)}


def test_undo_reports_evicted_samples(monkeypatch: pytest.MonkeyPatch) -> None:
    store_mod = sys.modules["shadow_clerk._daemon_voiceprint_store"]
    monkeypatch.setattr(store_mod, "load_config", lambda: {"speaker_enrollment": True, "voiceprint_max_samples": 1})
    _assign({"相手A": "alice"})
    _assign({"相手B": "alice"})
    assert _keys("alice") == {(MTG, B1)}
    r = _undo(_rec_id("相手A"))
    assert r["status"] == "ok" and r["restored_lines"] == 1 and r["removed_samples"] == 0, r
    assert r["lost_samples"] == 1 and t("dash.naming_undo_lost", count=1) in r["message"]
    assert "[相手A] 来週のリリースの件ですが" in _read(MTG) and _keys("alice") == {(MTG, B1)}


def test_undo_refuses_broken_history() -> None:
    _assign({"相手A": "alice"})
    rec_id = _rec_id("相手A")
    with open(_p(HIST), "a", encoding="utf-8") as f:
        f.write("{broken\n")
    with open(_p(MTG), "rb") as f:
        before = f.read()
    assert _undo(rec_id) == {"status": "error", "message": t("dash.naming_history_error")}
    h = _H({"file": MTG, "mapping": {"相手B": "bob"}})
    h._assign_speakers()
    assert h.sent == {"status": "error", "message": t("dash.naming_history_error")}
    with open(_p(MTG), "rb") as f:
        assert f.read() == before
    assert VoiceprintStore().people() == {"alice": 1}


def test_undo_refuses_broken_store() -> None:
    _assign({"相手A": "alice"})
    rec_id = _rec_id("相手A")
    with open(_p("voiceprints.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    before = _read(MTG)
    assert _undo(rec_id) == {"status": "error", "message": t("dash.voiceprint_store_error")}
    assert _read(MTG) == before and not _history()[0]["undone"]


def test_undo_returns_removed_samples_to_previous_person() -> None:
    _assign({"相手A": "alice"})
    _assign({"alice": "bob"})
    assert VoiceprintStore().people() == {"bob": 1}
    r = _undo(_rec_id("alice"))
    assert r["status"] == "ok" and (r["restored_lines"], r["removed_samples"], r["restored_samples"]) == (1, 1, 1), r
    assert "[alice] 来週のリリースの件ですが" in _read(MTG)
    assert VoiceprintStore().people() == {"alice": 1} and _keys("alice") == {(MTG, A1)}


def test_undo_does_not_revive_deleted_person() -> None:
    _assign({"相手A": "alice"})
    _assign({"alice": "bob"})
    h = _H({"name": "alice"})
    h._delete_voiceprint()
    assert h.sent["status"] == "ok", h.sent
    r = _undo(_rec_id("alice"))
    assert r["status"] == "ok" and r["restored_samples"] == 0 and r["removed_samples"] == 1, r
    assert VoiceprintStore().people() == {}


def test_undo_does_not_revive_sample_deleted_from_clusters() -> None:
    from shadow_clerk._daemon_dashboard_ops_voiceprints import _DashboardHandlerVoiceprintOps

    class _VH(_DashboardHandlerVoiceprintOps, _H):
        pass
    _assign({"相手A": "alice"})
    _assign({"alice": "bob"})
    h = _VH({"name": "bob", "keys": [[MTG, A1]]})
    h._delete_voiceprint_samples()
    assert h.sent["removed"] == 1, h.sent
    r = _undo(_rec_id("alice"))
    assert r["status"] == "ok" and r["restored_samples"] == 0 and r["lost_samples"] == 1, r
    assert VoiceprintStore().people() == {}
    assert t("dash.naming_undo_lost", count=1) in r["message"]


def test_undo_message_mentions_samples_given_back() -> None:
    _assign({"相手A": "alice"})
    _assign({"alice": "bob"})
    r = _undo(_rec_id("alice"))
    assert t("dash.naming_undo_restored", count=1) in r["message"], r


def test_history_error_flag() -> None:
    _assign({"相手A": "alice"})
    assert "history_error" not in _H_speakers()
    with open(_p(HIST), "a", encoding="utf-8") as f:
        f.write("{broken\n")
    sent = _H_speakers()
    assert sent["history"] == [] and sent["history_error"] is True


def _H_speakers() -> dict:
    h = _H(path=f"/api/speakers?file={MTG}")
    h._serve_speakers()
    return h.sent


def test_assign_warns_when_history_not_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    from shadow_clerk._daemon_naming_history import NamingHistoryError
    mod = sys.modules["shadow_clerk._daemon_dashboard_ops_speakers"]

    def fail(*_a: object) -> None:
        raise NamingHistoryError("x")
    monkeypatch.setattr(mod, "append_history", fail)
    r = _assign({"相手A": "alice"})
    assert t("dash.naming_history_not_saved") in r["message"] and "[alice]" in _read(MTG)


def _enrollment(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    monkeypatch.setattr(sys.modules["shadow_clerk._daemon_dashboard_ops_speakers"], "load_config",
                        lambda: {"speaker_enrollment": on})


def test_undo_does_not_create_samples_the_person_never_had(monkeypatch: pytest.MonkeyPatch) -> None:
    _enrollment(monkeypatch, False)
    _assign({"相手A": "alice"})
    _enrollment(monkeypatch, True)
    _assign({"alice": "bob"})
    assert VoiceprintStore().people() == {"bob": 1}
    r = _undo(_rec_id("alice"))
    assert r["status"] == "ok" and r["restored_samples"] == 0 and r["removed_samples"] == 1, r
    assert "[alice] 来週のリリースの件ですが" in _read(MTG) and VoiceprintStore().people() == {}


def test_undo_keeps_sample_that_existed_before_naming() -> None:
    from shadow_clerk.domain.voiceprint import VoiceSample
    VoiceprintStore().add({PersonName("alice"): [VoiceSample(_vec(0), A1, MTG)]})
    _assign({"相手A": "alice"})
    assert _history()[0]["added"] == 0
    r = _undo(_rec_id("相手A"))
    assert r["status"] == "ok" and r["removed_samples"] == 0 and r["lost_samples"] == 0, r
    assert _keys("alice") == {(MTG, A1)}


def test_undo_restores_previous_person_even_with_enrollment_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _assign({"相手A": "alice"})
    _assign({"alice": "bob"})
    _enrollment(monkeypatch, False)
    r = _undo(_rec_id("alice"))
    assert r["status"] == "ok" and r["restored_samples"] == 1 and r["removed_samples"] == 1, r
    assert VoiceprintStore().people() == {"alice": 1} and _keys("alice") == {(MTG, A1)}


def test_undo_twice_refused() -> None:
    _assign({"相手A": "alice"})
    rec_id = _rec_id("相手A")
    assert _undo(rec_id)["status"] == "ok"
    before = _read(MTG)
    assert _undo(rec_id) == {"status": "error", "message": t("dash.speakers_invalid")}
    assert _undo("no-such-id")["status"] == "error"
    assert _read(MTG) == before


def test_undo_overlapping_namings_in_any_order() -> None:
    _assign({"相手A": "alice"})
    _assign({"alice": "bob"})
    first, second = _rec_id("相手A"), _rec_id("alice")
    r = _undo(first)
    assert r["status"] == "ok" and r["restored_lines"] == 0, r
    assert _undo(second)["status"] == "ok"
    assert "[alice] 来週のリリースの件ですが" in _read(MTG)
    assert all(x["undone"] for x in _history())


def test_undo_after_rename() -> None:
    _assign({"相手A": "alice"})
    h = _H({"file": MTG, "name": "acme"})
    h._rename_meeting()
    new = h.sent["new_file"]
    r = _undo(_rec_id("相手A", new), new)
    assert r["status"] == "ok" and r["restored_lines"] == 1 and r["removed_samples"] == 1, r
    assert "[相手A] 来週のリリースの件ですが" in _read(new) and VoiceprintStore().people() == {}


def test_undo_refused_while_active_or_translating() -> None:
    _assign({"相手A": "alice"})
    rec_id = _rec_id("相手A")
    before = _read(MTG)
    assert _undo(rec_id, rec=_Rec(active=MTG)) == {"status": "error", "message": t("dash.speakers_active")}
    rec = _Rec()
    rec.translating.add(_p(MTG))
    assert _undo(rec_id, rec=rec) == {"status": "error", "message": t("dash.speakers_translating")}
    assert _read(MTG) == before and VoiceprintStore().people() == {"alice": 1}
