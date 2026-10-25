"""i18n の分割テーブル（本体と話者・声紋、会議ごとの設定）を結合したときに、キーが重複・欠落しないこと"""
from __future__ import annotations

from shadow_clerk._i18n_en import STRINGS_EN
from shadow_clerk._i18n_en_meeting import STRINGS_EN_MEETING
from shadow_clerk._i18n_en_speakers import STRINGS_EN_SPEAKERS
from shadow_clerk._i18n_ja import STRINGS_JA
from shadow_clerk._i18n_ja_meeting import STRINGS_JA_MEETING
from shadow_clerk._i18n_ja_speakers import STRINGS_JA_SPEAKERS
from shadow_clerk.i18n import STRINGS


def test_split_tables_do_not_shadow_each_other() -> None:
    for main, *parts in ((STRINGS_JA, STRINGS_JA_SPEAKERS, STRINGS_JA_MEETING),
                         (STRINGS_EN, STRINGS_EN_SPEAKERS, STRINGS_EN_MEETING)):
        keys = [set(main), *map(set, parts)]
        assert sum(map(len, keys)) == len(set().union(*keys))


def test_split_tables_have_same_keys_in_both_languages() -> None:
    assert set(STRINGS_JA_SPEAKERS) == set(STRINGS_EN_SPEAKERS)
    assert set(STRINGS_JA_MEETING) == set(STRINGS_EN_MEETING)


def test_merged_tables_contain_every_key() -> None:
    assert STRINGS["ja"] == {**STRINGS_JA, **STRINGS_JA_SPEAKERS, **STRINGS_JA_MEETING}
    assert STRINGS["en"] == {**STRINGS_EN, **STRINGS_EN_SPEAKERS, **STRINGS_EN_MEETING}
    assert "dash.naming_undo" in STRINGS["ja"] and "ms.title" in STRINGS["en"]
