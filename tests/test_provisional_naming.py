"""会議中の話者の仮登録と、会議終了時の本登録のテスト（daemon・音声デバイス不要。fixture は test_speaker_api と共有）"""
from __future__ import annotations

import os

from test_speaker_api import LINES, MTG, TR, _H, _Rec, _p, _read, isolated, meeting  # noqa: F401
from shadow_clerk.i18n import t
from shadow_clerk._daemon_provisional_naming import apply_provisional, provisional_path, read_provisional
from shadow_clerk._daemon_recorder_command import _RecorderCommandMixin
from shadow_clerk._daemon_voice_sidecar import read_voices
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore
from shadow_clerk.domain.provisional_naming import ProvisionalNaming

A1, B1, C1 = "2026-10-09 10:00:01", "2026-10-09 10:00:02", "2026-10-09 10:00:03"


def _active() -> _Rec:
    return _Rec(active=MTG)


def _assign(mapping: dict, rec: _Rec | None = None) -> dict:
    h = _H({"file": MTG, "mapping": mapping}, rec=rec or _active())
    h._assign_speakers()
    return h.sent


def _assign_lines(lines: list[tuple[str, str]], name: str, rec: _Rec | None = None, **extra: object) -> dict:
    h = _H({"file": MTG, "lines": [{"ts": ts, "label": lb} for ts, lb in lines], "name": name, **extra},
           rec=rec or _active())
    h._assign_lines()
    return h.sent


def _display() -> dict:
    h = _H(path=f"/api/speakers/provisional?file={MTG}")
    h._serve_provisional()
    return h.sent


def test_assign_during_meeting_is_provisional_and_touches_nothing() -> None:
    sent = _assign({"相手A": "太郎", "相手B": {"name": "acme", "group": "acme", "person": False}})
    assert sent == {"status": "ok", "provisional": True, "message": t("dash.speakers_provisional_saved")}
    assert _read(MTG) == "".join(LINES) and VoiceprintStore().people() == {}
    assert [e.label for e in read_voices(_p(MTG))] == ["相手A", "相手B", "相手C"]
    assert _display()["labels"] == {"相手A": "太郎", "相手B": "acme"}


def test_label_provisional_merges_and_empty_cancels() -> None:
    _assign({"相手A": "太郎", "相手B": "次郎"})
    _assign({"相手C": "三郎"})  # 👤 の「この話者の行を全部」は一部のラベルだけ送る
    _assign({"相手A": ""})
    assert _display()["labels"] == {"相手B": "次郎", "相手C": "三郎"}
    _assign({"相手B": "", "相手C": ""})
    assert not os.path.exists(provisional_path(_p(MTG)))


def test_line_provisional_and_cancel_with_empty_name() -> None:
    assert _assign_lines([(A1, "相手A")], "次郎")["provisional"]
    assert _display()["lines"] == {f"{A1}\t相手A": "次郎"}
    _assign_lines([(A1, "相手A")], "")
    assert _display()["lines"] == {}
    assert _assign_lines([(A1, "相手A")], "")["provisional"]  # 仮登録の無い行の取り消しも受け付ける
    assert _assign_lines([(A1, "相手A")], "相手X")["status"] == "error"  # 名前の検証は本登録と同じ


def test_line_provisional_range() -> None:
    _assign_lines([(A1, "相手A"), (C1, "相手C")], "次郎", scope="range")
    assert set(_display()["lines"]) == {f"{A1}\t相手A", f"{B1}\t相手B", f"{C1}\t相手C"}


def test_serve_speakers_offers_provisional_only_for_active_meeting() -> None:
    _assign({"相手A": "太郎"})
    h = _H(path=f"/api/speakers?file={MTG}", rec=_active())
    h._serve_speakers()
    assert h.sent["provisional"]["raw_labels"] == {"相手A": "太郎"}
    h = _H(path=f"/api/speakers?file={MTG}")
    h._serve_speakers()
    assert h.sent["provisional"] is None


def test_apply_lines_first_then_labels() -> None:
    _assign({"相手A": "太郎", "相手B": "次郎"})
    _assign_lines([(A1, "相手A")], "三郎")
    _assign_lines([(B1, "相手B")], "四郎")  # 相手B の行はすべて行単位で付け替わる
    rec = _Rec()  # 会議は終わった
    message = apply_provisional(rec, _p(MTG))
    assert message
    body = _read(MTG)
    assert f"[{A1}] [三郎]" in body and f"[{B1}] [四郎]" in body and f"[{C1}] [相手C]" in body
    assert "[相手A]" not in body and "[次郎]" not in body
    assert "[三郎]" in _read(TR)
    assert set(VoiceprintStore().people()) == {"三郎", "四郎"}
    assert not os.path.exists(provisional_path(_p(MTG)))


def test_apply_keeps_what_failed(monkeypatch) -> None:
    import shadow_clerk._daemon_provisional_naming as mod
    monkeypatch.setattr(mod, "TRANSLATION_WAIT_SEC", 0)
    _assign({"相手A": "太郎"})
    rec = _Rec()
    rec.translating.add(os.path.abspath(_p(MTG)))  # 翻訳が終わらないまま待ちきれなかった
    assert apply_provisional(rec, _p(MTG)) is None
    assert read_provisional(_p(MTG)).labels == {"相手A": "太郎"} and _read(MTG) == "".join(LINES)


def test_finish_meeting_applies_before_summary(monkeypatch) -> None:
    import shadow_clerk._daemon_recorder_command as cmd_mod
    order: list[str] = []
    monkeypatch.setattr(cmd_mod, "apply_provisional", lambda rec, path: order.append("apply"))
    monkeypatch.setattr(cmd_mod, "load_config", lambda: {"auto_summary": True})

    class _R(_RecorderCommandMixin):
        def _start_auto_summary(self, config: dict, path: str) -> None:
            order.append("summary")
    _R()._finish_meeting(_p(MTG))
    assert order == ["apply", "summary"]


def test_domain_round_trip_and_line_override() -> None:
    p = ProvisionalNaming().with_labels({"相手A": "太郎"}).with_lines({(A1, "相手A")}, {"name": "次郎"})
    assert ProvisionalNaming.parse(p.to_json()) == p
    assert p.with_lines({(A1, "相手A")}, {"name": "相手A"}).lines == {}  # 元のラベルに戻す指定は取り消し
    assert [(a, k) for a, k in p.line_groups()] == [({"name": "次郎"}, {(A1, "相手A")})]
