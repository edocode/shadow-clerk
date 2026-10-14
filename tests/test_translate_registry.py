"""one-shot 翻訳の実行中レジストリのテスト（翻訳そのものは走らせない）"""
from __future__ import annotations

import os
import threading

import pytest

import shadow_clerk._daemon_recorder_translate as tr
from shadow_clerk._daemon_recorder_translate import _RecorderTranslateMixin


class _Boom(BaseException):
    pass


class _Rec(_RecorderTranslateMixin):
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self._translate_stop_event = threading.Event()
        self.translate_target_path = None
        self._translating_paths: set[str] = set()
        self._translating_lock = threading.Lock()
        self._translate_thread: threading.Thread | None = None
        self.output_path = ""


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
    rec._translating_paths |= {os.path.abspath(a), os.path.abspath(b)}
    rec._translating_paths.discard(os.path.abspath(a))
    assert not rec.is_translating(a) and rec.is_translating(b)


def test_continuous_loop_counts_for_its_output_file(tmp_path) -> None:
    rec = _Rec()
    rec.output_path = str(tmp_path / "transcript-20261009.txt")
    other = str(tmp_path / "transcript-20261008.txt")
    assert not rec.is_translating(rec.output_path)
    stop = threading.Event()
    rec._translate_thread = threading.Thread(target=stop.wait)
    rec._translate_thread.start()
    try:
        assert rec.is_translating(rec.output_path) and not rec.is_translating(other)
        rec.translate_target_path = other  # one-shot が走っている間は継続ループ扱いにしない
        assert not rec.is_translating(rec.output_path)
    finally:
        stop.set()
        rec._translate_thread.join()
    rec.translate_target_path = None
    assert not rec.is_translating(rec.output_path)
