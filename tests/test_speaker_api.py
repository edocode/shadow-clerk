"""名前付け・声紋 API のテスト（daemon・音声デバイス不要）"""
from __future__ import annotations

import io
import json
import os
import tempfile
import threading

# **import より前に差し替えること。** DATA_DIR / CONFIG_FILE / VOICEPRINTS_FILE は import 時に決まる
DATA = tempfile.mkdtemp(prefix="shadow-clerk-speakers-")
os.environ["SHADOW_CLERK_DATA_DIR"] = DATA
with open(os.path.join(DATA, "config.yaml"), "w", encoding="utf-8") as _f:
    _f.write("speaker_enrollment: true\n")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

from shadow_clerk._daemon_dashboard_ops import _DashboardHandlerOps  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_meeting import _DashboardHandlerMeetingOps  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_speakers import _DashboardHandlerSpeakerOps  # noqa: E402
from shadow_clerk._daemon_voice_sidecar import append_voice, read_voices  # noqa: E402
from shadow_clerk._daemon_voiceprint_store import VOICEPRINTS_FILE, VoiceprintStore  # noqa: E402

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
def meeting() -> None:
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


def test_assign_remaps_translate_offset() -> None:
    size = os.path.getsize(_p(MTG))
    with open(_p(MTG) + ".translate_offset", "w", encoding="utf-8") as f:
        f.write(str(size))
    _H({"file": MTG, "mapping": {"相手A": "太郎"}})._assign_speakers()
    with open(_p(MTG) + ".translate_offset", encoding="utf-8") as f:
        assert int(f.read()) == os.path.getsize(_p(MTG))


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
    with open(VOICEPRINTS_FILE, "w", encoding="utf-8") as f:
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
    assert h.sent == {"status": "ok", "deleted": True}
    assert VoiceprintStore().people() == {}


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
