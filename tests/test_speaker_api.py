"""名前付け・声紋 API のテスト（daemon・音声デバイス不要）"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading

# **import より前に差し替えること。** DATA_DIR / CONFIG_FILE / VOICEPRINTS_FILE は import 時に決まる
DATA = tempfile.mkdtemp(prefix="shadow-clerk-speakers-")
os.environ["SHADOW_CLERK_DATA_DIR"] = DATA
with open(os.path.join(DATA, "config.yaml"), "w", encoding="utf-8") as _f:
    _f.write("speaker_enrollment: true\n")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from shadow_clerk.i18n import t  # noqa: E402
from shadow_clerk._daemon_dashboard_ops import _DashboardHandlerOps  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_meeting import _DashboardHandlerMeetingOps  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_speakers import _DashboardHandlerSpeakerOps  # noqa: E402
from shadow_clerk._daemon_voice_sidecar import append_voice, read_voices  # noqa: E402
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore  # noqa: E402

MTG = "transcript-202610091000@週次定例.txt"
TR = "transcript-202610091000@週次定例-en.txt"
LINES = [
    "--- 会議開始 2026-10-09 10:00 ---\n",
    "[2026-10-09 10:00:01] [相手A] 来週のリリースの件ですが\n",
    "[2026-10-09 10:00:02] [相手B] 資料は共有済みです\n",
    "[2026-10-09 10:00:03] [相手C] それでお願いします\n",
    "[2026-10-09 10:00:04] [自分] 了解です\n",
]


class _Rec:
    def __init__(self, active: str = "") -> None:
        self._output_dir = DATA
        self.output_path = os.path.join(DATA, active) if active else ""
        self.transcript_lock = threading.Lock()
        self.translating: set[str] = set()

    def is_translating(self, path: str) -> bool:
        return os.path.abspath(path) in self.translating


class _H(_DashboardHandlerSpeakerOps, _DashboardHandlerMeetingOps, _DashboardHandlerOps):
    def __init__(self, body: object = None, path: str = "/", rec: _Rec | None = None) -> None:
        raw = json.dumps(body if body is not None else {}).encode("utf-8")
        self.client_address = ("127.0.0.1", 1)
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.path = path
        self.recorder = rec or _Rec()
        self.file_watcher = None
        self.sent: dict = {}

    def _send_json(self, d: dict) -> None:
        self.sent = d

    def send_error(self, code: int) -> None:
        self.sent = {"http_error": code}

    def _trigger_auto_jobs_for_meetings(self, meeting_paths: list[str], *, is_new: bool) -> None:
        pass


def _vec(seed: int) -> np.ndarray:
    v = np.random.default_rng(seed).normal(size=256).astype(np.float32)
    return v / np.linalg.norm(v)


def _p(name: str) -> str:
    return os.path.join(DATA, name)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """他のテストが先に shadow_clerk を import 済みでも、実 DATA_DIR / config に触れない"""
    import shadow_clerk._daemon_dashboard_ops_speakers as speakers_mod
    import shadow_clerk._daemon_voiceprint_store as store_mod
    monkeypatch.setattr(store_mod, "VOICEPRINTS_FILE", _p("voiceprints.json"))
    for mod in (speakers_mod, store_mod, sys.modules["shadow_clerk._daemon_dashboard_ops_meeting"]):
        monkeypatch.setattr(mod, "load_config", lambda: {"speaker_enrollment": True})
    assert os.path.dirname(VoiceprintStore().path) == DATA, "store path leaked outside the test data dir"


@pytest.fixture(autouse=True)
def meeting(isolated: None) -> None:
    for f in os.listdir(DATA):
        if f != "config.yaml":
            os.remove(_p(f))
    with open(_p(MTG), "w", encoding="utf-8") as f:
        f.writelines(LINES)
    with open(_p(TR), "w", encoding="utf-8") as f:
        f.write("[2026-10-09 10:00:01] [相手A] About next week's release\n")
    with open(_p("transcript-202610091000@週次定例.attendees.json"), "w", encoding="utf-8") as f:
        json.dump({"attendees": ["次郎", "太郎"]}, f, ensure_ascii=False)
    for i, (ts, lbl) in enumerate([("10:00:01", "相手A"), ("10:00:02", "相手B"), ("10:00:03", "相手C")]):
        append_voice(_p(MTG), f"2026-10-09 {ts}", lbl, _vec(i))


def _read(name: str) -> str:
    with open(_p(name), encoding="utf-8") as f:
        return f.read()


def test_default_store_path_is_resolved_at_call_time() -> None:
    assert VoiceprintStore().path == _p("voiceprints.json")


def test_serve_speakers() -> None:
    from shadow_clerk.domain.voiceprint import PersonName, VoiceSample
    VoiceprintStore().add({PersonName("三郎"): [VoiceSample(_vec(9), "x", "y")]})
    h = _H(path=f"/api/speakers?file={MTG}")
    h._serve_speakers()
    assert h.sent["status"] == "ok"
    assert [(x["label"], x["count"], x["samples"]) for x in h.sent["labels"]] == \
        [("相手A", 1, 1), ("相手B", 1, 1), ("相手C", 1, 1)]
    assert h.sent["suggestions"] == ["次郎", "太郎", "三郎"]
    assert h.sent["active"] is False and h.sent["enrollment"] is True


def test_serve_speakers_lists_named_and_suggests_them() -> None:
    from shadow_clerk.domain.voiceprint import PersonName, VoiceSample
    with open(_p(MTG), "a", encoding="utf-8") as f:
        f.write("[2026-10-09 10:00:05] [四郎] 追加です\n")
    VoiceprintStore().add({PersonName("三郎"): [VoiceSample(_vec(9), "x", "y")],
                           PersonName("次郎"): [VoiceSample(_vec(8), "x", "z")]})
    h = _H(path=f"/api/speakers?file={MTG}")
    h._serve_speakers()
    assert [(x["label"], x["named"]) for x in h.sent["labels"]] == \
        [("相手A", False), ("相手B", False), ("相手C", False), ("四郎", True)]
    assert h.sent["suggestions"] == ["次郎", "太郎", "四郎", "三郎"]


def test_rename_named_speaker_moves_voiceprints() -> None:
    _H({"file": MTG, "mapping": {"相手A": "太郎"}})._assign_speakers()
    assert VoiceprintStore().people() == {"太郎": 1}
    h = _H({"file": MTG, "mapping": {"太郎": "次郎"}})
    h._assign_speakers()
    assert h.sent["status"] == "ok" and h.sent["renamed"] == 1 and h.sent["enrolled"] == {"次郎": 1}
    assert "[次郎] 来週のリリースの件ですが" in _read(MTG) and "[太郎]" not in _read(MTG)
    assert "[次郎] About next week's release" in _read(TR)
    assert [e.label for e in read_voices(_p(MTG))] == ["次郎", "相手B", "相手C"]
    assert VoiceprintStore().people() == {"次郎": 1}


def test_assign_same_name_is_nothing_to_assign() -> None:
    _H({"file": MTG, "mapping": {"相手A": "太郎"}})._assign_speakers()
    before = _read(MTG)
    h = _H({"file": MTG, "mapping": {"太郎": "太郎"}})
    h._assign_speakers()
    assert h.sent == {"status": "error", "message": t("dash.speakers_nothing")}
    assert _read(MTG) == before and VoiceprintStore().people() == {"太郎": 1}


def test_serve_speakers_rejects_unknown_file() -> None:
    for f in ["", "../config.yaml", "transcript-209901011000.txt", TR]:
        h = _H(path=f"/api/speakers?file={f}")
        h._serve_speakers()
        assert h.sent["status"] == "error", f


def test_assign_many_to_one() -> None:
    h = _H({"file": MTG, "mapping": {"相手A": "太郎", "相手C": " 太郎 ", "相手B": ""}})
    h._assign_speakers()
    assert h.sent["status"] == "ok" and h.sent["renamed"] == 2 and h.sent["enrolled"] == {"太郎": 2}
    body = _read(MTG)
    assert "[太郎] 来週のリリースの件ですが" in body and "[太郎] それでお願いします" in body
    assert "[相手B] 資料は共有済みです" in body and "[自分] 了解です" in body
    assert "[太郎] About next week's release" in _read(TR)
    assert [e.label for e in read_voices(_p(MTG))] == ["太郎", "相手B", "太郎"]
    assert VoiceprintStore().people() == {"太郎": 2}


def test_assign_enrolls_only_entries_still_in_transcript() -> None:
    append_voice(_p(MTG), "2026-10-09 09:00:00", "相手A", _vec(7))
    h = _H({"file": MTG, "mapping": {"相手A": "太郎"}})
    h._assign_speakers()
    assert h.sent["status"] == "ok" and h.sent["enrolled"] == {"太郎": 1}
    assert VoiceprintStore().people() == {"太郎": 1}


def test_assign_write_error_is_reported_and_retry_does_not_double_enroll(monkeypatch) -> None:
    h = _H({"file": MTG, "mapping": {"相手A": "太郎"}})

    def boom(path: str, lines: list[str]) -> None:
        raise OSError("disk full")
    with monkeypatch.context() as m:
        m.setattr(h, "_atomic_write_lines", boom)
        h._assign_speakers()
    assert h.sent["status"] == "error" and h.sent["message"] == t("dash.speakers_write_error")
    _H({"file": MTG, "mapping": {"相手A": "太郎"}})._assign_speakers()
    assert VoiceprintStore().people() == {"太郎": 1}


def test_assign_remaps_translate_offset() -> None:
    size = os.path.getsize(_p(MTG))
    with open(_p(MTG) + ".translate_offset", "w", encoding="utf-8") as f:
        f.write(str(size))
    _H({"file": MTG, "mapping": {"相手A": "太郎"}})._assign_speakers()
    with open(_p(MTG) + ".translate_offset", encoding="utf-8") as f:
        assert int(f.read()) == os.path.getsize(_p(MTG))


def test_assign_remaps_translate_offset_mid_file() -> None:
    first_two = len("".join(LINES[:2]).encode("utf-8"))
    with open(_p(MTG) + ".translate_offset", "w", encoding="utf-8") as f:
        f.write(str(first_two))
    _H({"file": MTG, "mapping": {"相手B": "次郎"}})._assign_speakers()
    with open(_p(MTG) + ".translate_offset", encoding="utf-8") as f:
        new_offset = int(f.read())
    assert new_offset == len("".join(_read(MTG).splitlines(keepends=True)[:2]).encode("utf-8"))
    assert new_offset == first_two  # 相手A の行は変わらない


def test_assign_mid_file_offset_after_renamed_line() -> None:
    first_three = len("".join(LINES[:3]).encode("utf-8"))
    with open(_p(MTG) + ".translate_offset", "w", encoding="utf-8") as f:
        f.write(str(first_three))
    _H({"file": MTG, "mapping": {"相手A": "太郎"}})._assign_speakers()
    with open(_p(MTG) + ".translate_offset", encoding="utf-8") as f:
        new_offset = int(f.read())
    assert new_offset == len("".join(_read(MTG).splitlines(keepends=True)[:3]).encode("utf-8"))
    assert new_offset != first_three


def test_assign_refused_while_translating() -> None:
    rec = _Rec()
    rec.translating.add(_p(MTG))
    h = _H({"file": MTG, "mapping": {"相手A": "太郎"}}, rec=rec)
    h._assign_speakers()
    assert h.sent == {"status": "error", "message": t("dash.speakers_translating")}
    assert _read(MTG) == "".join(LINES) and VoiceprintStore().people() == {}
    assert "[相手A]" in _read(TR)
    assert [e.label for e in read_voices(_p(MTG))] == ["相手A", "相手B", "相手C"]


def test_serve_speakers_reports_translating() -> None:
    rec = _Rec()
    h = _H(path=f"/api/speakers?file={MTG}", rec=rec)
    h._serve_speakers()
    assert h.sent["translating"] is False
    rec.translating.add(_p(MTG))
    h = _H(path=f"/api/speakers?file={MTG}", rec=rec)
    h._serve_speakers()
    assert h.sent["translating"] is True


def test_assign_rejects_and_writes_nothing() -> None:
    cases = [
        ({"file": MTG, "mapping": {"相手A": "自分"}}, None),
        ({"file": MTG, "mapping": {"相手A": "[x]"}}, None),
        ({"file": MTG, "mapping": {"相手Z": "太郎"}}, None),
        ({"file": MTG, "mapping": {"相手A": 3}}, None),
        ({"file": MTG, "mapping": "相手A=太郎"}, None),
        ({"file": MTG, "mapping": {"相手A": "  "}}, None),
        ({"file": MTG, "mapping": {"相手A": "太郎"}}, _Rec(active=MTG)),
    ]
    for body, rec in cases:
        h = _H(body, rec=rec)
        h._assign_speakers()
        assert h.sent["status"] == "error", body
        assert _read(MTG) == "".join(LINES), body
        assert VoiceprintStore().people() == {}, body


def test_assign_with_broken_store_writes_nothing() -> None:
    with open(_p("voiceprints.json"), "w", encoding="utf-8") as f:
        f.write("{broken")
    h = _H({"file": MTG, "mapping": {"相手A": "太郎"}})
    h._assign_speakers()
    assert h.sent["status"] == "error"
    assert _read(MTG) == "".join(LINES)
    assert _read("voiceprints.json") == "{broken"


def test_assign_without_enrollment_only_renames(monkeypatch) -> None:
    import shadow_clerk._daemon_dashboard_ops_speakers as ops
    monkeypatch.setattr(ops, "load_config", lambda: {"speaker_enrollment": False})
    h = _H({"file": MTG, "mapping": {"相手A": "太郎"}})
    h._assign_speakers()
    assert h.sent["status"] == "ok" and h.sent["enrolled"] == {}
    assert "[太郎]" in _read(MTG) and VoiceprintStore().people() == {}


def test_voiceprints_list_and_delete() -> None:
    _H({"file": MTG, "mapping": {"相手A": "太郎"}})._assign_speakers()
    h = _H()
    h._serve_voiceprints()
    assert h.sent == {"status": "ok", "people": [{"name": "太郎", "count": 1}]}
    h = _H({"name": "太郎"})
    h._delete_voiceprint()
    assert h.sent == {"status": "ok", "deleted": True, "sidecar_entries_removed": 1}
    assert VoiceprintStore().people() == {}


def test_delete_voiceprint_also_removes_named_sidecar_entries() -> None:
    _H({"file": MTG, "mapping": {"相手A": "太郎"}})._assign_speakers()
    assert [e.label for e in read_voices(_p(MTG))] == ["太郎", "相手B", "相手C"]
    h = _H({"name": "太郎"})
    h._delete_voiceprint()
    assert h.sent == {"status": "ok", "deleted": True, "sidecar_entries_removed": 1}
    assert VoiceprintStore().people() == {}
    assert [e.label for e in read_voices(_p(MTG))] == ["相手B", "相手C"]


def test_delete_voiceprint_cleans_sidecars_even_if_store_has_no_person() -> None:
    _H({"file": MTG, "mapping": {"相手A": "太郎"}})._assign_speakers()
    VoiceprintStore().delete("太郎")
    h = _H({"name": "太郎"})
    h._delete_voiceprint()
    assert h.sent == {"status": "ok", "deleted": False, "sidecar_entries_removed": 1}
    assert [e.label for e in read_voices(_p(MTG))] == ["相手B", "相手C"]


def test_extract_meeting_copies_voices() -> None:
    daily = "transcript-20261009.txt"
    with open(_p(daily), "w", encoding="utf-8") as f:
        f.write("[2026-10-09 09:00:00] [相手A] 朝\n[2026-10-09 11:00:00] [相手A] 昼\n")
    append_voice(_p(daily), "2026-10-09 09:00:00", "相手A", _vec(1))
    append_voice(_p(daily), "2026-10-09 11:00:00", "相手A", _vec(2))
    h = _H({"file": daily, "start_ts": "2026-10-09 10:30:00", "end_ts": "2026-10-09 11:30:00",
            "target": "new", "name": "昼会"})
    h._extract_meeting()
    assert h.sent["status"] == "ok", h.sent
    assert [e.timestamp for e in read_voices(_p("transcript-202610091030@昼会.txt"))] == \
        ["2026-10-09 11:00:00"]
