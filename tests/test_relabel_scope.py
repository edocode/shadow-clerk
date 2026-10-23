"""選んだ行の話者変更の範囲指定（assign-lines の scope）のテスト（daemon・音声デバイス不要。fixture は test_speaker_api と共有）"""
from __future__ import annotations

from test_speaker_api import MTG, TR, _H, _p, _read, isolated, meeting  # noqa: F401
from shadow_clerk.i18n import t

UNK, A2 = "2026-10-09 10:00:05", "2026-10-09 10:00:06"


def _more_lines() -> None:
    with open(_p(MTG), "a", encoding="utf-8") as f:
        f.write(f"[{UNK}] [相手?] うん\n[{A2}] [相手A] もう一行\n")


def _range(lines: list[dict], **extra: object) -> dict:
    h = _H({"file": MTG, "lines": lines, "name": "bob", "scope": "range", **extra})
    h._assign_lines()
    return h.sent


def test_range_relabels_every_remote_line_between() -> None:
    _more_lines()
    r = _range([{"ts": UNK, "label": "相手?"}, {"ts": "2026-10-09 10:00:02", "label": "相手B"}])
    assert r["status"] == "ok" and r["renamed"] == 3, r
    body = _read(MTG)
    assert "[bob] 資料は共有済みです" in body and "[bob] それでお願いします" in body and "[bob] うん" in body
    assert "[相手A] 来週のリリースの件ですが" in body and "[相手A] もう一行" in body and "[自分] 了解です" in body
    assert "[相手A] About next week's release" in _read(TR)


def test_range_needs_exactly_two_lines() -> None:
    _more_lines()
    before = _read(MTG)
    one = [{"ts": "2026-10-09 10:00:02", "label": "相手B"}]
    three = one + [{"ts": "2026-10-09 10:00:03", "label": "相手C"}, {"ts": UNK, "label": "相手?"}]
    for lines in (one, three):
        assert _range(lines) == {"status": "error", "message": t("dash.speakers_invalid")}, lines
    assert _range(one, scope="label")["status"] == "error"
    assert _read(MTG) == before


def test_range_rejects_missing_endpoint() -> None:
    before = _read(MTG)
    r = _range([{"ts": "2026-10-09 10:00:01", "label": "相手A"}, {"ts": "2026-10-09 10:00:09", "label": "相手C"}])
    assert r["status"] == "error" and _read(MTG) == before, r


def test_scope_omitted_is_selected_lines_only() -> None:
    _more_lines()
    h = _H({"file": MTG, "lines": [{"ts": "2026-10-09 10:00:02", "label": "相手B"}, {"ts": UNK, "label": "相手?"}],
            "name": "bob"})
    h._assign_lines()
    assert h.sent["status"] == "ok" and h.sent["renamed"] == 2, h.sent
    assert "[相手C] それでお願いします" in _read(MTG)
