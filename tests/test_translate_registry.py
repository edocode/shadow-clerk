"""one-shot 翻訳の実行中レジストリのテスト（翻訳そのものは走らせない）"""
from __future__ import annotations

import os
import threading
from collections import Counter

import pytest

import shadow_clerk._daemon_recorder_translate as tr
from shadow_clerk._daemon_recorder_translate import _RecorderTranslateMixin
from shadow_clerk.domain import TranscriptRewriteJournal


class _Boom(BaseException):
    pass


class _Rec(_RecorderTranslateMixin):
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self._translate_stop_event = threading.Event()
        self.translate_target_path = None
        self._translating_paths: Counter[str] = Counter()
        self._translating_lock = threading.Lock()
        self._translate_thread: threading.Thread | None = None
        self.output_path = ""
        self.transcript_lock = threading.Lock()
        self.rewrite_journal = TranscriptRewriteJournal()


def _setup(tmp_path, monkeypatch, seen: list[bool], rec: _Rec, exc: BaseException | None):
    t = tmp_path / "transcript-202610091000.txt"
    t.write_text("[2026-10-09 10:00:01] [相手A] a\n", encoding="utf-8")
    monkeypatch.setattr(tr, "load_config", lambda: {})
    monkeypatch.setattr(tr, "get_translation_provider", lambda c: "api")

    def fake_run(*a, **k):
        seen.append(rec.is_translating(str(t)))
        if exc:
            raise exc
        raise RuntimeError("stop")  # one-shot はエラーで終了する
    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    return str(t)


def test_registered_during_and_removed_after(tmp_path, monkeypatch) -> None:
    rec, seen = _Rec(), []
    t = _setup(tmp_path, monkeypatch, seen, rec, None)
    assert not rec.is_translating(t)
    rec._translate_loop(t, threading.Event())
    assert seen == [True] and not rec.is_translating(t)


def test_removed_even_on_exception(tmp_path, monkeypatch) -> None:
    rec, seen = _Rec(), []
    t = _setup(tmp_path, monkeypatch, seen, rec, _Boom())
    with pytest.raises(_Boom):
        rec._translate_loop(t, threading.Event())
    assert seen == [True] and not rec.is_translating(t)


def test_concurrent_jobs_tracked_independently(tmp_path) -> None:
    rec = _Rec()
    a, b = str(tmp_path / "a.txt"), str(tmp_path / "b.txt")
    for p in (a, b):
        rec._register_translating(p)
    rec._unregister_translating(a)
    assert not rec.is_translating(a) and rec.is_translating(b)


class _Res:
    returncode = 0
    stdout = "x\n"
    stderr = ""


def _continuous(tmp_path, monkeypatch, step) -> tuple[_Rec, str, threading.Event]:
    """継続ループを 1 チャンクだけ回す。step(rec, x) は翻訳の最中に呼ばれる（subprocess を差し替え）"""
    rec = _Rec()
    x = str(tmp_path / "transcript-20261009.txt")
    (tmp_path / "transcript-20261009.txt").write_text("[2026-10-09 10:00:01] [相手A] a\n", encoding="utf-8")
    rec.output_path = x
    stop = threading.Event()
    monkeypatch.setattr(tr, "load_config", lambda: {})
    monkeypatch.setattr(tr, "get_translation_provider", lambda c: "api")

    def fake_run(*a, **k):
        stop.set()
        step(rec, x)
        return _Res()
    monkeypatch.setattr(tr.subprocess, "run", fake_run)
    return rec, x, stop


def test_continuous_chunk_registers_its_file_across_rollover(tmp_path, monkeypatch) -> None:
    seen: list[bool] = []

    def step(rec: _Rec, x: str) -> None:
        rec.output_path = str(tmp_path / "transcript-20261010.txt")  # 日付変更
        seen.append(rec.is_translating(x))
        seen.append(rec.is_translating(rec.output_path))
    rec, x, stop = _continuous(tmp_path, monkeypatch, step)
    assert not rec.is_translating(x)
    rec._translate_loop(None, stop)
    assert seen == [True, False] and not rec.is_translating(x)


def test_continuous_chunk_registered_even_if_thread_dropped(tmp_path, monkeypatch) -> None:
    seen: list[bool] = []

    def step(rec: _Rec, x: str) -> None:
        rec._translate_thread = None  # translate_stop の join がタイムアウトした状態
        seen.append(rec.is_translating(x))
    rec, x, stop = _continuous(tmp_path, monkeypatch, step)
    rec._translate_loop(None, stop)
    assert seen == [True] and not rec.is_translating(x)


def test_continuous_chunk_unregistered_on_exception(tmp_path, monkeypatch) -> None:
    def step(rec: _Rec, x: str) -> None:
        raise _Boom()
    rec, x, stop = _continuous(tmp_path, monkeypatch, step)
    with pytest.raises(_Boom):
        rec._translate_loop(None, stop)
    assert not rec.is_translating(x)


def test_same_path_registrations_are_counted(tmp_path) -> None:
    rec = _Rec()
    a = str(tmp_path / "a.txt")
    rec._register_translating(a)
    rec._register_translating(a)
    rec._unregister_translating(a)
    assert rec.is_translating(a)
    rec._unregister_translating(a)
    assert not rec.is_translating(a)


def test_background_job_does_not_take_over_watched_target(tmp_path, monkeypatch) -> None:
    """会議切り出しの自動翻訳 (watch=False) は、ユーザーが見ている one-shot の監視先を奪わない"""
    rec, seen = _Rec(), []
    t = _setup(tmp_path, monkeypatch, seen, rec, None)
    rec.translate_target_path = "/watched/transcript-20260101.txt"
    rec._translate_loop(t, threading.Event(), watch=False)
    assert rec.translate_target_path == "/watched/transcript-20260101.txt"


def test_watched_job_publishes_and_clears_target(tmp_path, monkeypatch) -> None:
    rec, seen = _Rec(), []
    t = _setup(tmp_path, monkeypatch, seen, rec, None)
    rec._translate_loop(t, threading.Event())
    assert rec.translate_target_path is None
