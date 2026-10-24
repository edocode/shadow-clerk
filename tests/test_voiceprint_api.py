"""声紋の塊 API（表示・消す・移す・戻す）のテスト（daemon・音声デバイス不要。fixture は test_speaker_api と共有）"""
from __future__ import annotations

import numpy as np
import pytest

from test_speaker_api import MTG, TR, _H, _Rec, _p, _read, _vec, isolated, meeting  # noqa: F401
import shadow_clerk._daemon_voiceprint_clusters as cluster_mod
from shadow_clerk.i18n import t
from shadow_clerk._daemon_dashboard_ops_voiceprints import _DashboardHandlerVoiceprintOps
from shadow_clerk._daemon_voice_sidecar import append_voice, read_voices
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore
from shadow_clerk.domain.voiceprint import PersonName, SampleStatus, VoiceSample

MTG2 = "transcript-202610101000@週次定例.txt"
A1, B1, X1, X2 = "2026-10-09 10:00:01", "2026-10-09 10:00:02", "2026-10-10 10:00:01", "2026-10-10 10:00:02"


class _VH(_DashboardHandlerVoiceprintOps, _H):
    pass


@pytest.fixture(autouse=True)
def cluster_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cluster_mod, "load_config", lambda: {})


def _call(method: str, body: object = None, path: str = "/", rec: _Rec | None = None) -> dict:
    h = _VH(body, path=path, rec=rec)
    getattr(h, method)()
    return h.sent


def _assign(file: str, mapping: dict) -> None:
    sent = _call("_assign_speakers", {"file": file, "mapping": mapping})
    assert sent["status"] == "ok", sent


def _clusters(name: str) -> dict:
    return _call("_serve_voiceprint_clusters", path=f"/api/voiceprints/clusters?name={name}")


def _keys(name: str) -> set[tuple[str, str]]:
    return {s.key for s in VoiceprintStore().samples(PersonName(name))}


def _second_meeting() -> None:
    with open(_p(MTG2), "w", encoding="utf-8") as f:
        f.write(f"[{X1}] [相手A] 見積もりを送ります\n[{X2}] [相手B] 確認します\n")
    append_voice(_p(MTG2), X1, "相手A", _vec(11))
    append_voice(_p(MTG2), X2, "相手B", _vec(12))


def _near(base: np.ndarray, seed: int) -> np.ndarray:
    v = base + 0.02 * np.random.default_rng(seed).normal(size=base.shape).astype(np.float32)
    return v / np.linalg.norm(v)


def test_clusters_endpoint_shapes_and_example() -> None:
    main, other = _vec(100), _vec(200)
    ts = [f"2026-10-10 10:00:{i:02d}" for i in range(12)]
    lines = [f"[{ts[i]}] [alice] {'長い発言です' * (2 if i == 3 else 1)}{i}\n" for i in range(10)]
    lines += [f"[{ts[10]}] [bob] これは別の人の行でとても長い本文です\n", f"[{ts[11]}] [alice] 短い\n"]
    with open(_p(MTG2), "w", encoding="utf-8") as f:
        f.writelines(lines)
    samples = [VoiceSample(_near(main, i), ts[i], MTG2) for i in range(10)]
    samples += [VoiceSample(_near(other, i), ts[i], MTG2) for i in (10, 11)]
    samples.append(VoiceSample(np.ones(8, dtype=np.float32), "2026-10-10 11:00:00", MTG2))  # 次元違いは塊に入れない
    VoiceprintStore().add({PersonName("alice"): samples})
    r = _clusters("alice")
    assert r["status"] == "ok" and r["name"] == "alice", r
    assert [(c["kind"], c["count"]) for c in r["clusters"]] == [("main", 10), ("different", 2)]
    m, d = r["clusters"]
    assert m["similarity"] == 1.0 and d["similarity"] < 0.5
    assert m["keys"] == [[MTG2, x] for x in ts[:10]] and d["keys"] == [[MTG2, ts[10]], [MTG2, ts[11]]]
    assert m["sources"] == [{"file": MTG2, "count": 10, "labels": []}]
    assert m["example"] == "長い発言です長い発言です3"
    assert d["example"] == "短い"  # bob の行は ts が当たっても使わない


def test_clusters_example_empty_without_line() -> None:
    VoiceprintStore().add({PersonName("alice"): [VoiceSample(_vec(1), "2026-10-09 12:00:00", "transcript-202601010000.txt")]})
    c = _clusters("alice")["clusters"]
    assert [(x["kind"], x["count"], x["example"]) for x in c] == [("main", 1, "")]


def test_clusters_show_original_label_from_history() -> None:
    _second_meeting()
    _assign(MTG, {"相手A": "alice", "相手B": "alice"})
    _assign(MTG2, {"相手B": "alice"})
    r = _clusters("alice")
    assert r["status"] == "ok", r
    [c] = r["clusters"]
    assert c["count"] == 3 and c["kind"] == "main"
    assert c["sources"] == [{"file": MTG, "count": 2, "labels": ["相手A", "相手B"]},
                            {"file": MTG2, "count": 1, "labels": ["相手B"]}]
    assert c["example"] == "来週のリリースの件ですが"


def test_clusters_invalid_name() -> None:
    assert _clusters("")["status"] == "error"


def test_delete_samples_marks_sidecar_no_enroll() -> None:
    _assign(MTG, {"相手A": "alice", "相手B": "alice"})
    r = _call("_delete_voiceprint_samples", {"name": "alice", "keys": [[MTG, A1]]})
    assert r["status"] == "ok" and r["removed"] == 1, r
    assert r["message"] == t("dash.vp_deleted_samples", count=1)
    assert _keys("alice") == {(MTG, B1)}
    assert "[alice] 来週のリリースの件ですが" in _read(MTG)
    assert [(e.label, e.no_enroll) for e in read_voices(_p(MTG))] == \
        [("alice", True), ("alice", False), ("相手C", False)]
    _assign(MTG, {"alice": "bob"})
    assert _keys("bob") == {(MTG, B1)} and VoiceprintStore().people() == {"bob": 1}


def test_move_rewrites_transcripts_across_meetings() -> None:
    _second_meeting()
    _assign(MTG, {"相手A": "alice", "相手B": "alice"})
    _assign(MTG2, {"相手A": "alice", "相手B": "alice"})
    r = _call("_move_voiceprint_samples", {"name": "alice", "keys": [[MTG, A1], [MTG2, X1]], "to": "bob"})
    assert r["status"] == "ok", r
    assert (r["moved"], r["relabeled_lines"], r["skipped_files"]) == (2, 2, 0)
    assert r["message"] == t("dash.vp_moved", count=2, name="bob", lines=2)
    assert "[bob] 来週のリリースの件ですが" in _read(MTG) and "[alice] 資料は共有済みです" in _read(MTG)
    assert "[bob] About next week's release" in _read(TR)
    assert "[bob] 見積もりを送ります" in _read(MTG2) and "[alice] 確認します" in _read(MTG2)
    assert [e.label for e in read_voices(_p(MTG2))] == ["bob", "alice"]
    assert _keys("bob") == {(MTG, A1), (MTG2, X1)} and _keys("alice") == {(MTG, B1), (MTG2, X2)}
    assert all(s.status is SampleStatus.NORMAL for s in VoiceprintStore().samples(PersonName("bob")))


def test_move_skips_active_transcript() -> None:
    _second_meeting()
    _assign(MTG, {"相手A": "alice"})
    _assign(MTG2, {"相手A": "alice"})
    rec = _Rec(active=MTG2)
    rec.translating.add(_p(MTG))
    r = _call("_move_voiceprint_samples", {"name": "alice", "keys": [[MTG, A1], [MTG2, X1]], "to": "bob"}, rec=rec)
    assert r["status"] == "ok", r
    assert (r["moved"], r["relabeled_lines"], r["skipped_files"]) == (2, 0, 2)
    assert t("dash.vp_move_skipped", count=2) in r["message"]
    assert "[alice] 見積もりを送ります" in _read(MTG2) and "[alice] 来週のリリースの件ですが" in _read(MTG)
    assert _keys("bob") == {(MTG, A1), (MTG2, X1)} and "alice" not in VoiceprintStore().people()


def test_move_missing_source_moves_samples_silently() -> None:
    gone = "transcript-202601010000.txt"
    VoiceprintStore().add({PersonName("alice"): [VoiceSample(_vec(1), A1, gone)]})
    r = _call("_move_voiceprint_samples", {"name": "alice", "keys": [[gone, A1]], "to": "bob"})
    assert (r["status"], r["moved"], r["relabeled_lines"], r["skipped_files"]) == ("ok", 1, 0, 0), r
    assert _keys("bob") == {(gone, A1)}


def test_move_to_non_person_refused() -> None:
    _assign(MTG, {"相手A": "alice"})
    before = _read(MTG)
    r = _call("_move_voiceprint_samples", {"name": "alice", "keys": [[MTG, A1]], "to": {"name": "acme", "person": False}})
    assert r == {"status": "error", "message": t("dash.vp_move_not_person")}
    assert _read(MTG) == before and _keys("alice") == {(MTG, A1)}


def test_restore_sets_kept() -> None:
    _assign(MTG, {"相手A": "alice", "相手B": "alice"})
    r = _call("_restore_voiceprint_samples", {"name": "alice", "keys": [[MTG, A1]]})
    assert r["status"] == "ok" and r["restored"] == 1, r
    status = {s.key: s.status for s in VoiceprintStore().samples(PersonName("alice"))}
    assert status == {(MTG, A1): SampleStatus.KEPT, (MTG, B1): SampleStatus.NORMAL}


def _with_outlier() -> tuple[str, list[str]]:
    """alice に、いつもの声 40 件と遠い 1 件（除外中）を入れる。遠い 1 件の時刻と全時刻を返す"""
    main = _vec(100)
    ts = [f"2026-10-10 10:{i // 60:02d}:{i % 60:02d}" for i in range(41)]
    with open(_p(MTG2), "w", encoding="utf-8") as f:
        f.writelines(f"[{x}] [alice] 発言{i}\n" for i, x in enumerate(ts))
    samples = [VoiceSample(_near(main, i), ts[i], MTG2) for i in range(40)] + [VoiceSample(_vec(999), ts[40], MTG2)]
    VoiceprintStore().add({PersonName("alice"): samples})
    return ts[40], ts


def test_clusters_include_status_and_restored_sample_leaves_outlier() -> None:
    far, ts = _with_outlier()
    before = _clusters("alice")["clusters"]
    assert [(c["kind"], c["count"]) for c in before] == [("main", 40), ("outlier", 1)]
    assert before[1]["statuses"] == ["outlier"] and set(before[0]["statuses"]) == {"normal"}
    r = _call("_restore_voiceprint_samples", {"name": "alice", "keys": [[MTG2, far]]})
    assert r["status"] == "ok" and r["restored"] == 1 and r["message"] == t("dash.vp_restored", count=1), r
    after = _clusters("alice")["clusters"]
    assert [(c["kind"], c["count"]) for c in after] == [("main", 41)]  # 戻したサンプルは「いつもの声」に入れて見せる
    assert dict(zip(map(tuple, after[0]["keys"]), after[0]["statuses"]))[(MTG2, far)] == "kept"


def test_delete_samples_restatuses_the_person() -> None:
    far, ts = _with_outlier()
    _call("_delete_voiceprint_samples", {"name": "alice", "keys": [[MTG2, x] for x in ts[:35]]})
    st = {s.key: s.status for s in VoiceprintStore().samples(PersonName("alice"))}
    assert st[(MTG2, far)] is SampleStatus.NORMAL  # 10 件未満になったので除外しない


def test_non_numeric_min_sec_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    monkeypatch.setattr(sys.modules["shadow_clerk._daemon_dashboard_ops_speakers"], "load_config",
                        lambda: {"speaker_enrollment": True, "voiceprint_min_sec": "abc"})
    _assign(MTG, {"相手A": "alice"})
    assert _keys("alice") == {(MTG, A1)}


def test_kept_sample_survives_group_change_on_named_label() -> None:
    _assign(MTG, {"相手A": "alice", "相手B": "alice"})
    VoiceprintStore().set_status("alice", {(MTG, A1)}, SampleStatus.KEPT)
    _assign(MTG, {"alice": {"name": "alice", "group": "acme"}})
    got = VoiceprintStore().samples(PersonName("alice"))
    assert [(s.key, s.status) for s in got] == [((MTG, A1), SampleStatus.KEPT), ((MTG, B1), SampleStatus.NORMAL)]


def test_invalid_keys_refused() -> None:
    for keys in (None, [], [[MTG]], [[MTG, 1]], "x"):
        assert _call("_delete_voiceprint_samples", {"name": "alice", "keys": keys}) == \
            {"status": "error", "message": t("dash.speakers_invalid")}


def test_store_unreadable_refuses_all() -> None:
    _assign(MTG, {"相手A": "alice"})
    with open(_p("voiceprints.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    before, voices = _read(MTG), _read("transcript-202610091000@週次定例.voices.jsonl")
    err = {"status": "error", "message": t("dash.voiceprint_store_error")}
    body = {"name": "alice", "keys": [[MTG, A1]]}
    assert _clusters("alice") == err
    assert _call("_delete_voiceprint_samples", body) == err
    assert _call("_move_voiceprint_samples", {**body, "to": "bob"}) == err
    assert _call("_restore_voiceprint_samples", body) == err
    assert _read(MTG) == before and _read("transcript-202610091000@週次定例.voices.jsonl") == voices
    with open(_p("voiceprints.json"), encoding="utf-8") as f:
        assert f.read() == "{broken"


def test_move_relabels_sidecar_without_transcript_line() -> None:
    _assign(MTG, {"相手A": "alice"})
    with open(_p(MTG), "w", encoding="utf-8") as f:  # 行は手で消された・別の名前に直されたが、サイドカーは alice のまま
        f.write(f"[{A1}] [carol] 来週のリリースの件ですが\n")
    r = _call("_move_voiceprint_samples", {"name": "alice", "keys": [[MTG, A1]], "to": "bob"})
    assert (r["status"], r["moved"], r["relabeled_lines"], r["skipped_files"]) == ("ok", 1, 0, 0), r
    assert [(e.timestamp, e.label) for e in read_voices(_p(MTG))][0] == (A1, "bob")
    assert "[carol] 来週のリリースの件ですが" in _read(MTG)


def test_sidecar_and_history_do_not_import_dashboard() -> None:
    import subprocess
    import sys
    code = ("import sys, shadow_clerk._daemon_voice_sidecar, shadow_clerk._daemon_naming_history;"
            "sys.exit('shadow_clerk._daemon_dashboard_ops' in sys.modules)")
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
