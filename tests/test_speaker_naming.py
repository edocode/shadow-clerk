"""名前付けの純粋な処理のテスト"""
from __future__ import annotations

from shadow_clerk._daemon_speaker_naming import (
    LabelSummary, relabel_lines_where, remap_offset, summarize_labels,
)
from shadow_clerk.domain.transcript_line import TranscriptLine
from shadow_clerk.domain.voiceprint import PersonName

LINES = [
    "--- 会議開始 2026-10-09 10:00 ---\n",
    "[2026-10-09 10:00:01] [相手B] はい\n",
    "[2026-10-09 10:00:02] [相手A] 来週のリリースの件ですが\n",
    "[2026-10-09 10:00:03] [自分] どうぞ\n",
    "[2026-10-09 10:00:04] [相手A] 短い\n",
    "[2026-10-09 10:00:05] [相手?] うん\n",
    "[2026-10-09 10:00:06] [相手27] それでお願いします\n",
    "[2026-10-09 10:00:07] [相手C] 資料は共有済みです\n",
    "[2026-10-09 10:00:08] [次郎] 了解\n",
    "[2026-10-09 10:00:09] [相手] 分離なし\n",
]


def test_summarize_labels() -> None:
    assert summarize_labels(LINES) == [
        LabelSummary("相手A", 2, "来週のリリースの件ですが"),
        LabelSummary("相手B", 1, "はい"),
        LabelSummary("相手C", 1, "資料は共有済みです"),
        LabelSummary("相手27", 1, "それでお願いします"),
        LabelSummary("次郎", 1, "了解", True),
    ]


def test_summarize_labels_includes_named_after_numbered() -> None:
    lines = LINES + ["[2026-10-09 10:00:10] [太郎] 長い方の発話です\n",
                     "[2026-10-09 10:00:11] [太郎] 短\n"]
    got = summarize_labels(lines)
    assert [(s.label, s.named) for s in got] == [
        ("相手A", False), ("相手B", False), ("相手C", False), ("相手27", False),
        ("太郎", True), ("次郎", True)]
    assert got[-2] == LabelSummary("太郎", 2, "長い方の発話です", True)
    assert not any(s.label in {"相手?", "相手"} for s in got)


def test_relabel_many_to_one() -> None:
    taro = PersonName("太郎")
    new, n = relabel_lines_where(LINES, lambda tl: taro.value if tl.speaker_label in {"相手A", "相手C"} else None)
    assert n == 3 and len(new) == len(LINES)
    assert new[0] == LINES[0] and new[3] == LINES[3] and new[5] == LINES[5]
    parsed = TranscriptLine.parse(new[2])
    assert parsed is not None and parsed.speaker_label == "太郎" and parsed.text == "来週のリリースの件ですが"
    assert new[7] == "[2026-10-09 10:00:07] [太郎] 資料は共有済みです\n"


def _bytes(lines: list[str]) -> int:
    return sum(len(x.encode("utf-8")) for x in lines)


def test_remap_offset() -> None:
    new, _ = relabel_lines_where(LINES, lambda tl: "太郎" if tl.speaker_label == "相手A" else None)
    assert remap_offset(LINES, new, 0) == 0
    assert remap_offset(LINES, new, _bytes(LINES)) == _bytes(new)
    assert remap_offset(LINES, new, _bytes(LINES[:3])) == _bytes(new[:3])
    assert remap_offset(LINES, new, _bytes(LINES[:2])) == _bytes(new[:2])
    mid = _bytes(LINES[:2]) + 5
    assert remap_offset(LINES, new, mid) == _bytes(new[:2]) + 5


from shadow_clerk._daemon_speaker_naming import (  # noqa: E402
    Assignment, Decision, decide_assignment, line_target_picker, parse_assignment, relabel_lines_where,
)
from shadow_clerk.domain.speaker_group import SpeakerEntry  # noqa: E402
import pytest  # noqa: E402


def test_line_target_picker_only_targets() -> None:
    lines = [
        "[2026-10-09 10:00:01] [相手A] 一\n",
        "[2026-10-09 10:00:01] [相手B] 同じ時刻の別人\n",
        "[2026-10-09 10:00:02] [相手A] 二\n",
        "[2026-10-09 10:00:02] [自分] 自分の行\n",
        "[2026-10-09 10:00:03] [相手] 分離なし\n",
        "[2026-10-09 10:00:04] [Claude] 応答\n",
    ]
    targets = {("2026-10-09 10:00:01", "相手A"), ("2026-10-09 10:00:02", "自分"), ("2026-10-09 10:00:03", "相手"),
               ("2026-10-09 10:00:04", "Claude")}
    new, n = relabel_lines_where(lines, line_target_picker(targets, "太郎"))
    assert n == 3
    assert new[0] == "[2026-10-09 10:00:01] [太郎] 一\n"
    assert new[1:3] == lines[1:3]
    assert new[3] == "[2026-10-09 10:00:02] [太郎] 自分の行\n"
    assert new[4] == "[2026-10-09 10:00:03] [太郎] 分離なし\n"
    assert new[5] == lines[5]


def test_parse_assignment() -> None:
    assert parse_assignment(" 太郎 ") == Assignment(PersonName("太郎"))
    assert parse_assignment({"name": "acme", "group": " acme ", "person": False}) == \
        Assignment(PersonName("acme"), "acme", False)
    assert parse_assignment({"name": "太郎", "group": ""}).group == ""
    assert parse_assignment({"name": "太郎", "confirm": True}).confirm is True
    assert parse_assignment({"name": "太郎"}).confirm is False
    for bad in [3, {"group": "acme"}, {"name": "太郎", "group": 1}, {"name": "太郎", "person": "no"},
                {"name": "太郎", "confirm": "yes"},
                {"name": "太郎", "group": "[x]"}, {"name": "自分"}]:
        with pytest.raises(ValueError):
            parse_assignment(bad)


def test_decide_assignment_defaults() -> None:
    entries = {"太郎": SpeakerEntry("acme", True), "acme営業": SpeakerEntry("acme", False)}
    groups = {"acme": "#e57373"}
    assert decide_assignment(Assignment(PersonName("太郎")), entries, groups) == Decision(PersonName("太郎"), "acme", True)
    assert decide_assignment(Assignment(PersonName("acme営業")), entries, groups).person is False
    assert decide_assignment(Assignment(PersonName("acme")), entries, groups).person is False  # グループ名と同じ
    assert decide_assignment(Assignment(PersonName("次郎")), entries, groups) == Decision(PersonName("次郎"), "", True)
    assert decide_assignment(Assignment(PersonName("太郎"), "", None), entries, groups).group == ""


def test_decision_changes() -> None:
    entries = {"太郎": SpeakerEntry("acme", True)}
    d = Decision(PersonName("太郎"), "acme", True)
    assert not d.changes("太郎", entries)
    assert d.changes("相手A", entries)
    assert Decision(PersonName("太郎"), "自社", True).changes("太郎", entries)


def test_tentative_label() -> None:
    from shadow_clerk.domain.voiceprint import tentative_name
    assert [tentative_name(x) for x in ("alice?", "alice", "相手?", "相手A?", "?", "自分?")] == \
        ["alice", None, None, None, None, None]
    got = summarize_labels(["[2026-10-09 10:00:01] [alice?] たぶん\n", "[2026-10-09 10:00:02] [alice] 確か\n"])
    assert [(s.label, s.named, s.tentative, s.suggested) for s in got] == \
        [("alice", True, False, None), ("alice?", True, True, "alice")]
