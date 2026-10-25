"""Shadow-clerk: i18n 文字列テーブル (en) — 会議ごとの設定"""
# pylint: disable=duplicate-code  # 日英テーブルは同一プレースホルダ構造を持つため
from __future__ import annotations

STRINGS_EN_MEETING: dict[str, str] = {
    "ms.title": "Meeting settings",
    "ms.filter_ph": "Filter by meeting name",
    "ms.col_name": "Meeting",
    "ms.col_publish": "Publish",
    "ms.col_dest": "Destination",
    "ms.publish": "Publish (allow minutes on external services)",
    "ms.keep": "Keep as is",
    "ms.publish_on": "Public",
    "ms.publish_off": "Private",
    "ms.workdir": "Working directory",
    "ms.workdir_keep": "(blank keeps it)",
    "ms.dest": "Destination",
    "ms.apply": "Apply",
    "ms.config_file": "Config file: {path}",
    "ms.uses_defaults": "Uses the defaults",
    "ms.shared_rule": "Matches rule '{rule}' (changing it adds a rule for this meeting)",
    "ms.edit_one": "Settings for this meeting",
    "ms.title_one": "Settings — {name}",
    "ms.title_many": "Change {n} meetings",
    "ms.pick": "Pick meetings on the left",
    "ms.notion_url_required": "Enter the Notion URL (https://…)",
    "ms.nothing": "Nothing to change",
    "ms.advice": "AI analysis Advice",
    "ms.advice_on": "Include when publishing",
    "ms.advice_off": "Leave out",
}
