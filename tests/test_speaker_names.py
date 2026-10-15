"""話者名の名簿 (SpeakerNameBook) のテスト"""
from __future__ import annotations

import os
import tempfile

import pytest

from shadow_clerk._daemon_speaker_names import SpeakerNameBook, SpeakerNameBookError
from shadow_clerk.domain.voiceprint import PersonName


@pytest.fixture
def book() -> SpeakerNameBook:
    return SpeakerNameBook(os.path.join(tempfile.mkdtemp(prefix="shadow-clerk-names-"), "speaker_names.json"))


def test_missing_file_is_empty(book: SpeakerNameBook) -> None:
    assert book.entries() == {}
    assert not os.path.exists(book.path)


def test_set_entry_dedupes_and_saves_sorted(book: SpeakerNameBook) -> None:
    for n in ("次郎", "太郎", "太郎", "三郎"):
        book.set_entry(PersonName(n), None, True)
    assert list(book.entries()) == sorted(["次郎", "太郎", "三郎"])


def test_remove(book: SpeakerNameBook) -> None:
    book.set_entry(PersonName("太郎"), None, True)
    assert book.remove("太郎") is True
    assert book.remove("太郎") is False
    assert book.entries() == {}


def test_default_path_is_resolved_at_call_time(monkeypatch: pytest.MonkeyPatch, book: SpeakerNameBook) -> None:
    import shadow_clerk._daemon_speaker_names as mod
    monkeypatch.setattr(mod, "SPEAKER_NAMES_FILE", book.path)
    assert SpeakerNameBook().path == book.path


@pytest.mark.parametrize("content", ["{not json", "[]", '{"names": "x"}', '{"names": [1]}'])
def test_broken_file_raises_and_is_never_overwritten(book: SpeakerNameBook, content: str) -> None:
    with open(book.path, "w", encoding="utf-8") as f:
        f.write(content)
    with pytest.raises(SpeakerNameBookError):
        book.entries()
    with pytest.raises(SpeakerNameBookError):
        book.set_entry(PersonName("太郎"), None, True)
    with pytest.raises(SpeakerNameBookError):
        book.remove("太郎")
    with open(book.path, encoding="utf-8") as f:
        assert f.read() == content


def test_write_is_atomic_and_leaves_no_temp_files(book: SpeakerNameBook) -> None:
    book.set_entry(PersonName("太郎"), None, True)
    assert os.listdir(os.path.dirname(book.path)) == ["speaker_names.json"]


import json

from shadow_clerk.domain.speaker_group import GROUP_PALETTE, GroupName, SpeakerEntry


def test_v1_file_is_migrated_on_write(book: SpeakerNameBook) -> None:
    with open(book.path, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "names": ["太郎", "次郎"]}, f, ensure_ascii=False)
    assert book.entries() == {"太郎": SpeakerEntry(), "次郎": SpeakerEntry()}
    book.set_entry(PersonName("三郎"), GroupName("acme"), True)
    with open(book.path, encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == 2
    assert set(data["names"]) == {"太郎", "次郎", "三郎"}
    assert data["names"]["三郎"] == {"group": "acme", "person": True}


def test_set_entry_assigns_persistent_colors(book: SpeakerNameBook) -> None:
    book.set_entry(PersonName("太郎"), GroupName("acme"), True)
    book.set_entry(PersonName("acme営業"), GroupName("acme"), False)
    book.set_entry(PersonName("次郎"), GroupName("自社"), True)
    assert book.groups() == {"acme": GROUP_PALETTE[0], "自社": GROUP_PALETTE[1]}
    assert book.entries()["acme営業"] == SpeakerEntry("acme", False)
    book.set_entry(PersonName("太郎"), None, True)
    assert book.entries()["太郎"] == SpeakerEntry("", True)
    assert book.groups()["acme"] == GROUP_PALETTE[0]  # 誰も使わなくなっても色は保つ


def test_set_group_keeps_person_and_rejects_unknown(book: SpeakerNameBook) -> None:
    book.set_entry(PersonName("acme営業"), None, False)
    assert book.set_group("acme営業", GroupName("acme")) is True
    assert book.entries()["acme営業"] == SpeakerEntry("acme", False)
    assert book.set_group("いない人", GroupName("acme")) is False


def test_ensure_group(book: SpeakerNameBook) -> None:
    c = book.ensure_group(GroupName("自社"))
    assert c == GROUP_PALETTE[0]
    assert book.ensure_group(GroupName("自社")) == c
    assert book.entries() == {}


def test_set_entry_keeps_other_entries(book: SpeakerNameBook) -> None:
    book.set_entry(PersonName("太郎"), GroupName("acme"), False)
    book.set_entry(PersonName("次郎"), None, True)
    assert book.entries() == {"太郎": SpeakerEntry("acme", False), "次郎": SpeakerEntry()}


@pytest.mark.parametrize("content", [
    '{"version": 2, "names": {"太郎": "x"}}',
    '{"version": 2, "names": {"太郎": {"person": "yes"}}}',
    '{"version": 2, "names": {}, "groups": {"acme": "red"}}',
    '{"version": 2, "names": {}, "groups": []}',
])
def test_broken_v2_file_is_never_overwritten(book: SpeakerNameBook, content: str) -> None:
    with open(book.path, "w", encoding="utf-8") as f:
        f.write(content)
    for call in (book.entries, book.groups,
                 lambda: book.set_entry(PersonName("太郎"), None, True),
                 lambda: book.ensure_group(GroupName("acme")),
                 lambda: book.remove("太郎")):
        with pytest.raises(SpeakerNameBookError):
            call()
    with open(book.path, encoding="utf-8") as f:
        assert f.read() == content
