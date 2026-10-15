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
    assert book.names() == []
    assert not os.path.exists(book.path)


def test_add_dedupes_and_sorts(book: SpeakerNameBook) -> None:
    book.add([PersonName("次郎"), PersonName("太郎")])
    book.add([PersonName("太郎"), PersonName("三郎")])
    assert book.names() == sorted(["次郎", "太郎", "三郎"])
    assert len(book.names()) == 3


def test_remove(book: SpeakerNameBook) -> None:
    book.add([PersonName("太郎")])
    assert book.remove("太郎") is True
    assert book.remove("太郎") is False
    assert book.names() == []


def test_default_path_is_resolved_at_call_time(monkeypatch: pytest.MonkeyPatch, book: SpeakerNameBook) -> None:
    import shadow_clerk._daemon_speaker_names as mod
    monkeypatch.setattr(mod, "SPEAKER_NAMES_FILE", book.path)
    assert SpeakerNameBook().path == book.path


@pytest.mark.parametrize("content", ["{not json", "[]", '{"names": "x"}', '{"names": [1]}'])
def test_broken_file_raises_and_is_never_overwritten(book: SpeakerNameBook, content: str) -> None:
    with open(book.path, "w", encoding="utf-8") as f:
        f.write(content)
    with pytest.raises(SpeakerNameBookError):
        book.names()
    with pytest.raises(SpeakerNameBookError):
        book.add([PersonName("太郎")])
    with pytest.raises(SpeakerNameBookError):
        book.remove("太郎")
    with open(book.path, encoding="utf-8") as f:
        assert f.read() == content


def test_write_is_atomic_and_leaves_no_temp_files(book: SpeakerNameBook) -> None:
    book.add([PersonName("太郎")])
    assert os.listdir(os.path.dirname(book.path)) == ["speaker_names.json"]
