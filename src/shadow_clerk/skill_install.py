"""同梱スキルの配布

配布ロジックをここ1か所に置く。CLI (`clerk-util install-skill`) と
ダッシュボードの API が同じ関数を呼ぶ。両方に同じ規則を書くと、片方だけ
直したときに黙ってずれる。
"""
from __future__ import annotations
import logging
import os
import pathlib
import shutil
import sys

import yaml

logger = logging.getLogger("shadow-clerk")

SKILL_NAME = "clerk-meeting-helper"

# 配布先。~/.agents/skills はベンダー中立の共有場所で Codex 固有ではないため、
# ターゲット名は codex ではなく agents とする。他のエージェントが同じ場所を
# 読むようになったとき codex という名前は嘘になる。
# 両方とも ~ 相対で形が同じなので expanduser が Windows の
# C:\Users\<user>\... まで解決する。OS 分岐は要らない
BUILTIN_TARGETS = {
    "claude": "~/.claude/skills",
    "agents": "~/.agents/skills",
}


class InstallRefused(Exception):
    """配布先に素性の分からないスキルがある。--force なしでは触らない"""


def bundled_skill_dir() -> pathlib.Path:
    """同梱されているスキルの場所。バイナリでも通常インストールでも引ける"""
    if getattr(sys, "frozen", False):          # PyInstaller
        base = pathlib.Path(getattr(sys, "_MEIPASS")) / "shadow_clerk"
    else:
        import importlib.resources
        base = pathlib.Path(str(importlib.resources.files("shadow_clerk")))
    return base / "skills" / SKILL_NAME


def read_skill_version(skill_dir: pathlib.Path) -> str | None:
    """SKILL.md の frontmatter から metadata.version を読む。

    仕様上 SKILL.md に version フィールドは無く、独自キーを足すと claude.ai への
    アップロード時に hard error になる。自由形式が許された metadata を使う。
    読めない場合に None を返すのは、配布先が自分の書いたものかを判別するため——
    素性の分からない配布先を黙って上書きしない。
    """
    try:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    front, sep, _ = text[3:].partition("\n---")
    if not sep:
        return None
    try:
        data = yaml.safe_load(front)
    except yaml.YAMLError:
        return None
    meta = data.get("metadata") if isinstance(data, dict) else None
    if not isinstance(meta, dict) or "version" not in meta:
        return None
    return str(meta["version"])
