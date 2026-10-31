"""聞き間違いの目印（kana_hint）の検証

実行: uv run pytest tests/test_kana_hint.py
かな認識モデル（1.2GB）は読まない。ロジットを手で作った偽の認識器で通しの動作を見る。
形態素解析と torch を使うテストは kana-hint extra が無ければ飛ばす。
"""
from __future__ import annotations
import importlib.util

import pytest

from shadow_clerk import _daemon_kana_hint as kh
from shadow_clerk.domain.kana_hint import hint, strip_hints

needs_extra = pytest.mark.skipif(not kh.KanaHinter.available(), reason="kana-hint extra が無い")


def test_hint_round_trip() -> None:
    line = "きょうの午後にリプロイ" + hint("でぷろい") + "しますか"
    assert line == "きょうの午後にリプロイ(でぷろい?)しますか"
    assert strip_hints(line) == "きょうの午後にリプロイしますか"
    # 普通の括弧書きは外さない
    assert strip_hints("仕様書(案)を見る") == "仕様書(案)を見る"
    assert strip_hints("担当(たなか)") == "担当(たなか)"


def test_phonetic_keeps_positions() -> None:
    assert kh.phonetic("れびゅー") == "れびゅう"
    assert kh.phonetic("きょう") == "きょお"
    assert kh.phonetic("せんせい") == "せんせえ"
    assert kh.phonetic("を") == "お"
    for s in ("れびゅー", "きょう", "ぢづを"):
        assert len(kh.phonetic(s)) == len(s)


def test_spellings_cover_long_vowels() -> None:
    v = kh.spellings("きょお")
    assert {"きょお", "きょう", "きょー"} <= set(v)
    # 直前の文脈の母音とも長音になる
    assert "ー" in "".join(kh.spellings("お", before="こ"))
    assert kh.spellings("かき") == ["かき"]


def test_align_maps_boundaries() -> None:
    lo, hi = kh.align("ぱすたいく", "あしたいく")
    assert (lo[3], hi[3]) == (3, 3)
    # 音の側に余分な字がある境界では、最小と最大が分かれる
    lo, hi = kh.align("かき", "かあき")
    assert lo[1] < hi[1]


def _m(reading: str, pos: str = "名詞") -> tuple[str, str]:
    return reading, pos


def _morphs(*parts: tuple[str, str]) -> list:
    out, at = [], 0
    for reading, pos in parts:
        out.append(kh._Morpheme(at, at + max(len(reading), 1), reading, pos))
        at += max(len(reading), 1)
    return out


def test_runs_find_content_words_only() -> None:
    morphs = _morphs(_m("ばっじ"), _m("の", "助詞"), _m("ろご"), _m("お", "助詞"))
    runs = kh.mismatched_runs(morphs, "ばっちのろぐお")
    assert [(r.first, r.last) for r in runs] == [(0, 0), (2, 2)]
    # 助詞だけの食い違い（脱落）は拾わない
    morphs = _morphs(_m("れびゅう"), _m("お", "助詞"), _m("ねがい", "動詞"))
    assert kh.mismatched_runs(morphs, "れびゅうねがい") == []


def test_one_char_run_grows_to_the_next_particle() -> None:
    morphs = _morphs(_m("てすと"), _m("は", "助詞"), _m("ど", "副詞"), _m("おっ", "動詞"), _m("た", "助動詞"))
    runs = kh.mismatched_runs(morphs, "てすとはとおった")
    assert [(r.first, r.last) for r in runs] == [(2, 4)]


@needs_extra
def test_morphemes_give_kana_readings() -> None:
    from sudachipy import Dictionary, SplitMode

    tok = Dictionary(dict="core").tokenizer(mode=SplitMode.A)
    morphs = kh.morphemes(tok, "テストは通った。")
    assert morphs is not None
    assert "".join(m.reading for m in morphs) == "てすとはとおった"
    # 助詞の「は」は表記どおり（かなモデルも「は」と書く）
    assert [m.reading for m in morphs if m.pos == "助詞"] == ["は"]
    assert morphs[-1].reading == "" and not morphs[-1].content


class _FakeTokenizer:
    def __init__(self) -> None:
        self.vocab = {"[PAD]": 0, "|": 1}
        for c in "でぷろいりしますかきょうのごにわ":
            self.vocab.setdefault(c, len(self.vocab))
        self.pad_token_id = 0

    def get_vocab(self) -> dict[str, int]:
        return self.vocab

    def decode(self, ids: list[int]) -> str:
        inv = {i: c for c, i in self.vocab.items()}
        out, prev = [], None
        for i in ids:
            if i != prev and i != 0:
                out.append(" " if i == 1 else inv[i])
            prev = i
        return "".join(out)


class _FakeRecogniser:
    """「heard」と言った音の、はっきりしたロジットを返す"""

    def __init__(self, heard: str) -> None:
        self.heard = heard
        self.loaded = True
        self.processor = type("_P", (), {"tokenizer": _FakeTokenizer()})()

    def logits(self, pcm: object) -> object:
        import torch

        vocab = self.processor.tokenizer.vocab
        frames = []
        for c in self.heard:
            frames += [vocab[c], 0]
        x = torch.full((1, len(frames), len(vocab)), -10.0)
        for t, i in enumerate(frames):
            x[0, t, i] = 10.0
        return x

    def unload(self) -> None:
        self.loaded = False


def _hinter(heard: str, monkeypatch: pytest.MonkeyPatch, enabled: bool = True) -> kh.KanaHinter:
    from sudachipy import Dictionary, SplitMode

    monkeypatch.setattr(kh, "load_config", lambda: {"kana_hint": enabled})
    h = kh.KanaHinter(_FakeRecogniser(heard))
    h._tokenizer = Dictionary(dict="core").tokenizer(mode=SplitMode.A)
    return h


@needs_extra
def test_annotate_marks_the_misheard_word(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _hinter("きょうのごごにでぷろいしますか", monkeypatch)
    assert h.annotate("きょうの午後にリプロイしますか", None, "ja") == "きょうの午後にリプロイ(でぷろい?)しますか"
    # 音と合っている行には何も足さない
    assert h.annotate("きょうの午後にデプロイしますか", None, "ja") == "きょうの午後にデプロイしますか"


@needs_extra
def test_annotate_is_japanese_only(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _hinter("きょうのごごにでぷろいしますか", monkeypatch)
    for language in ("en", None):
        assert h.annotate("きょうの午後にリプロイしますか", None, language) == "きょうの午後にリプロイしますか"


@needs_extra
def test_disabled_does_nothing_and_unloads(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _hinter("きょうのごごにでぷろいしますか", monkeypatch, enabled=False)
    assert h.annotate("きょうの午後にリプロイしますか", None, "ja") == "きょうの午後にリプロイしますか"
    assert not h._recogniser.loaded


@needs_extra
def test_failure_keeps_the_line(monkeypatch: pytest.MonkeyPatch) -> None:
    h = _hinter("きょう", monkeypatch)

    def boom(pcm: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(h._recogniser, "logits", boom)
    assert h.annotate("きょうの午後にリプロイ", None, "ja") == "きょうの午後にリプロイ"


def test_missing_extra_never_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kh, "load_config", lambda: {"kana_hint": True})
    monkeypatch.setattr(kh.KanaHinter, "available", staticmethod(lambda: False))
    rec = _FakeRecogniser("")
    rec.loaded = False
    h = kh.KanaHinter(rec)
    assert h.annotate("テスト", None, "ja") == "テスト"
    assert not h._loading


def test_importing_does_not_pull_torch() -> None:
    # daemon 起動時に torch を読まない
    assert importlib.util.find_spec("shadow_clerk._daemon_kana_hint") is not None
    import subprocess
    import sys

    code = "import sys, shadow_clerk._daemon_kana_hint as k; k.KanaHinter(); print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "False"
