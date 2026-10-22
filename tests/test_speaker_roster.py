"""話者一覧と議事録プロンプトのテスト"""
from __future__ import annotations

import os
import tempfile

os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-roster-")

import pytest  # noqa: E402

import shadow_clerk._daemon_speaker_names as names_mod  # noqa: E402
from shadow_clerk._daemon_speaker_roster import (  # noqa: E402
    RosterEntry, build_roster, load_roster, roster_prompt_block,
)
from shadow_clerk.domain.speaker_group import SpeakerEntry  # noqa: E402
from shadow_clerk.i18n import nt  # noqa: E402

LINES = [
    "--- 会議開始 2026-10-15 10:00 ---\n",
    "[2026-10-15 10:00:01] [太郎] よろしくお願いします\n",
    "[2026-10-15 10:00:02] [自分] こちらこそ\n",
    "[2026-10-15 10:00:03] [acme営業] 資料を送ります\n",
    "[2026-10-15 10:00:04] [相手A] はい\n",
    "[2026-10-15 10:00:05] [相手?] うん\n",
    "[2026-10-15 10:00:06] [相手] 分離なし\n",
    "[2026-10-15 10:00:07] [Claude] 補足です\n",
    "[2026-10-15 10:00:08] [太郎] 以上です\n",
]
ENTRIES = {"太郎": SpeakerEntry("acme", True), "acme営業": SpeakerEntry("acme", False)}


def test_build_roster() -> None:
    assert build_roster(LINES, ENTRIES, "自社") == [
        RosterEntry("太郎", "acme", False, True),
        RosterEntry("自分", "自社", True, True),
        RosterEntry("acme営業", "acme", False, False),
        RosterEntry("相手A", "", False, False),
    ]


def test_roster_to_dict() -> None:
    assert RosterEntry("太郎", "acme", False, True).to_dict() == \
        {"label": "太郎", "group": "acme", "self": False, "person": True, "tentative": False}


def test_prompt_block_empty_without_groups() -> None:
    roster = build_roster(LINES, {}, "")
    assert roster_prompt_block(roster, "") == ""


def test_prompt_block_single_group_has_no_group_instruction() -> None:
    block = roster_prompt_block(build_roster(LINES, ENTRIES, ""), "")
    assert "- 太郎: acme" in block
    assert nt("llm.summary_groups_instruction") not in block


def test_prompt_block_multi_group_adds_instruction() -> None:
    block = roster_prompt_block(build_roster(LINES, ENTRIES, "自社"), "自社")
    assert "- 自分: 自社" + nt("llm.summary_speakers_self_mark") in block
    assert "- 相手A: " + nt("llm.summary_speakers_unknown_group") in block
    assert block.endswith(nt("llm.summary_groups_instruction"))


def test_load_roster_tolerates_broken_book(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "speaker_names.json"
    p.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(names_mod, "SPEAKER_NAMES_FILE", str(p))
    assert load_roster(LINES, "")[0] == RosterEntry("太郎", "", False, False)
    assert p.read_text(encoding="utf-8") == "{broken"


def test_llm_context_block(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from shadow_clerk import _llm_summarize
    monkeypatch.setattr(names_mod, "SPEAKER_NAMES_FILE", str(tmp_path / "speaker_names.json"))
    names_mod.SpeakerNameBook().set_entry(names_mod.PersonName("太郎"), names_mod.GroupName("acme"), True)
    t = tmp_path / "transcript-202610151000@週次定例.txt"
    t.write_text("".join(LINES), encoding="utf-8")
    block = _llm_summarize._load_context_block(str(t), "".join(LINES), {"self_group": "自社"})
    assert "- 太郎: acme" in block and nt("llm.summary_groups_instruction") in block
    assert _llm_summarize._load_context_block(str(t), "".join(LINES), {"self_group": None}).count("- 太郎: acme") == 1


def test_roster_treats_tentative_as_unconfirmed() -> None:
    lines = ["[2026-10-15 10:00:01] [太郎?] たぶん太郎\n", "[2026-10-15 10:00:02] [相手?] うん\n"]
    roster = build_roster(lines, ENTRIES, "自社")
    assert roster == [RosterEntry("太郎?", "", False, False, tentative=True)]
    assert roster[0].to_dict()["tentative"] is True
    assert "- 太郎?: " + nt("llm.summary_speakers_unknown_group") + nt("llm.summary_speakers_tentative_mark") \
        in roster_prompt_block(roster, "自社")
