"""議事録の再生成の作り方選択のテスト（コンソール・LLM は呼ばない）"""
from __future__ import annotations

import os
import tempfile
import threading

os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-regen-")

import pytest  # noqa: E402

import shadow_clerk._daemon_summary_regen as regen  # noqa: E402

MTG = "transcript-202610151000@週次定例.txt"


class _Rec:
    def __init__(self) -> None:
        self.done = threading.Event()
        self.paths: list[str] = []

    def _auto_summarize(self, path: str) -> None:
        self.paths.append(path)
        self.done.set()


class _Console:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_after_ready(self, text: str) -> None:
        self.sent.append(text)


@pytest.fixture
def meeting(tmp_path) -> str:
    p = tmp_path / MTG
    p.write_text("[2026-10-15 10:00:01] [太郎] よろしく\n", encoding="utf-8")
    return str(p)


def _patch(monkeypatch: pytest.MonkeyPatch, started: bool | Exception) -> _Console:
    console = _Console()
    def fake_start(path: str, auto: bool = False, send_prompt: bool = True) -> bool:
        assert send_prompt is False
        if isinstance(started, Exception):
            raise started
        return started
    monkeypatch.setattr(regen, "start_console_for", fake_start)
    monkeypatch.setattr(regen, "get_console", lambda: console)
    return console


def test_regenerate_uses_console_when_advice_exists(meeting: str, monkeypatch: pytest.MonkeyPatch) -> None:
    open(os.path.join(os.path.dirname(meeting), "advice-202610151000@週次定例.md"), "w").close()
    console = _patch(monkeypatch, True)
    rec = _Rec()
    assert regen.summary_method(meeting) == "console"
    assert regen.regenerate_summary(rec, meeting) == "console"
    assert len(console.sent) == 1 and "/api/speaker-roster?file=" + MTG in console.sent[0]
    assert "summary-202610151000@週次定例.md" in console.sent[0] and console.sent[0].endswith("\r")
    assert rec.paths == []


def test_regenerate_uses_llm_without_assistant_files(meeting: str, monkeypatch: pytest.MonkeyPatch) -> None:
    console = _patch(monkeypatch, True)
    rec = _Rec()
    assert regen.summary_method(meeting) == "llm"
    assert regen.regenerate_summary(rec, meeting) == "llm"
    assert rec.done.wait(5) and rec.paths == [meeting] and console.sent == []


@pytest.mark.parametrize("started", [False, RuntimeError("boom")])
def test_regenerate_falls_back_to_llm(meeting: str, monkeypatch: pytest.MonkeyPatch, started: bool | Exception) -> None:
    open(os.path.join(os.path.dirname(meeting), "analysis-202610151000@週次定例.md"), "w").close()
    console = _patch(monkeypatch, started)
    rec = _Rec()
    assert regen.regenerate_summary(rec, meeting) == "llm"
    assert rec.done.wait(5) and console.sent == []
