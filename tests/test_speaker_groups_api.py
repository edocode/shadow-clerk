"""グループ・話者一覧 API のテスト（daemon 不要。実データディレクトリに触れない）"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import threading

DATA = tempfile.mkdtemp(prefix="shadow-clerk-groups-")
os.environ["SHADOW_CLERK_DATA_DIR"] = DATA

import pytest  # noqa: E402

from shadow_clerk._daemon_dashboard_ops import _DashboardHandlerOps  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_speaker_groups import _DashboardHandlerSpeakerGroupOps  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_speakers import _DashboardHandlerSpeakerOps  # noqa: E402
from shadow_clerk._daemon_speaker_names import SpeakerNameBook  # noqa: E402
from shadow_clerk.domain.speaker_group import GROUP_PALETTE, GroupName  # noqa: E402
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore  # noqa: E402
from shadow_clerk.domain.voiceprint import PersonName, VoiceSample  # noqa: E402

MTG = "transcript-202610151000@週次定例.txt"
CFG = {"self_group": "自社"}


class _Rec:
    def __init__(self) -> None:
        self._output_dir = DATA
        self.output_path = ""
        self.transcript_lock = threading.Lock()

    def is_translating(self, path: str) -> bool:
        return False


class _H(_DashboardHandlerSpeakerGroupOps, _DashboardHandlerSpeakerOps, _DashboardHandlerOps):
    def __init__(self, body: object = None, path: str = "/", client: str = "127.0.0.1") -> None:
        raw = json.dumps(body if body is not None else {}).encode("utf-8")
        self.client_address = (client, 1)
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.path = path
        self.recorder = _Rec()
        self.file_watcher = None
        self.sent: dict = {}

    def _send_json(self, d: dict) -> None:
        self.sent = d


@pytest.fixture(autouse=True)
def sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    import shadow_clerk._daemon_speaker_names as names_mod
    import shadow_clerk._daemon_dashboard_ops_speaker_groups as groups_mod
    for f in os.listdir(DATA):
        os.remove(os.path.join(DATA, f))
    monkeypatch.setattr(names_mod, "SPEAKER_NAMES_FILE", os.path.join(DATA, "speaker_names.json"))
    import shadow_clerk._daemon_voiceprint_store as store_mod
    monkeypatch.setattr(store_mod, "VOICEPRINTS_FILE", os.path.join(DATA, "voiceprints.json"))
    monkeypatch.setattr(groups_mod, "load_config", lambda: dict(CFG))
    assert os.path.dirname(SpeakerNameBook().path) == DATA
    with open(os.path.join(DATA, MTG), "w", encoding="utf-8") as f:
        f.write("[2026-10-15 10:00:01] [太郎] よろしく\n[2026-10-15 10:00:02] [自分] どうも\n")


def test_speaker_groups_includes_self_group_color() -> None:
    SpeakerNameBook().set_entry(PersonName("太郎"), GroupName("acme"), True)
    h = _H(path="/api/speaker-groups")
    h._serve_speaker_groups()
    assert h.sent["status"] == "ok"
    assert h.sent["names"] == {"太郎": "acme"} and h.sent["persons"] == {"太郎": True}
    assert h.sent["groups"] == {"acme": GROUP_PALETTE[0], "自社": GROUP_PALETTE[1]}
    assert h.sent["self_group"] == "自社"


def test_set_group() -> None:
    SpeakerNameBook().set_entry(PersonName("太郎"), None, True)
    h = _H({"name": "太郎", "group": "acme"})
    h._set_speaker_group()
    assert h.sent == {"status": "ok"}
    assert SpeakerNameBook().entries()["太郎"].group == "acme"
    for body in ({"name": "いない", "group": "acme"}, {"name": "太郎", "group": "[x]"}, {"name": 3}):
        h = _H(body)
        h._set_speaker_group()
        assert h.sent["status"] == "error", body


def test_set_group_for_voiceprint_only_name_creates_book_entry() -> None:
    VoiceprintStore().add({PersonName("次郎"): [VoiceSample([0.1, 0.2], "x", "y")]})
    assert "次郎" not in SpeakerNameBook().entries()
    h = _H({"name": "次郎", "group": "acme"})
    h._set_speaker_group()
    assert h.sent == {"status": "ok"}
    e = SpeakerNameBook().entries()["次郎"]
    assert e.group == "acme" and e.person is True
    h = _H({"name": "三郎", "group": "acme"})
    h._set_speaker_group()
    assert h.sent["status"] == "error" and "三郎" not in SpeakerNameBook().entries()


def test_roster_endpoint_and_localhost_guard() -> None:
    SpeakerNameBook().set_entry(PersonName("太郎"), GroupName("acme"), True)
    h = _H(path=f"/api/speaker-roster?file={MTG}")
    h._serve_speaker_roster()
    assert h.sent["self_group"] == "自社"
    assert h.sent["speakers"] == [
        {"label": "太郎", "group": "acme", "self": False, "person": True},
        {"label": "自分", "group": "自社", "self": True, "person": True},
    ]
    h = _H(path=f"/api/speaker-roster?file={MTG}", client="192.0.2.1")
    h._serve_speaker_roster()
    assert h.sent["status"] == "error"
