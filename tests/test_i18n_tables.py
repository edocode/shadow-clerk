"""i18n の分割テーブル（本体と話者・声紋）を結合したときに、キーが重複・欠落しないこと"""
from __future__ import annotations

from shadow_clerk._i18n_en import STRINGS_EN
from shadow_clerk._i18n_en_speakers import STRINGS_EN_SPEAKERS
from shadow_clerk._i18n_ja import STRINGS_JA
from shadow_clerk._i18n_ja_speakers import STRINGS_JA_SPEAKERS
from shadow_clerk.i18n import STRINGS


def test_speaker_tables_do_not_shadow_main_tables() -> None:
    assert not set(STRINGS_JA) & set(STRINGS_JA_SPEAKERS)
    assert not set(STRINGS_EN) & set(STRINGS_EN_SPEAKERS)


def test_speaker_tables_have_same_keys_in_both_languages() -> None:
    assert set(STRINGS_JA_SPEAKERS) == set(STRINGS_EN_SPEAKERS)


def test_merged_tables_contain_every_key() -> None:
    assert STRINGS["ja"] == {**STRINGS_JA, **STRINGS_JA_SPEAKERS}
    assert STRINGS["en"] == {**STRINGS_EN, **STRINGS_EN_SPEAKERS}
    assert "dash.naming_undo" in STRINGS["ja"] and "dash.speakers_title" in STRINGS["en"]
