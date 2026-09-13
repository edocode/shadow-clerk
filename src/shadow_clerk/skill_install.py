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


def resolve_target(name_or_path: str) -> tuple[str, pathlib.Path]:
    """ターゲット名または任意パスを、実際の配布先ディレクトリに解決する"""
    base = BUILTIN_TARGETS.get(name_or_path, name_or_path)
    return name_or_path, pathlib.Path(os.path.expanduser(base)) / SKILL_NAME


def install(name_or_path: str, *, link: bool = False, force: bool = False) -> dict:
    """同梱スキルを配布先へ置く。戻り値はバージョンの変化を含む記録"""
    name, dest = resolve_target(name_or_path)
    src = bundled_skill_dir()
    before = read_skill_version(dest)
    if dest.exists() and before is None and not force:
        raise InstallRefused(str(dest))
    if link and os.name == "nt":
        raise InstallRefused("--link は POSIX 専用です")
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.is_dir():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if link:
        os.symlink(src, dest, target_is_directory=True)
    else:
        shutil.copytree(src, dest)
    after = read_skill_version(dest)
    logger.info("スキルを配布: %s -> %s (%s -> %s)", src, dest, before, after)
    remember_target(name)
    return {"target": name, "path": str(dest), "before": before,
            "after": after, "mode": "link" if link else "copy"}


def remembered_targets() -> list[str]:
    from shadow_clerk._daemon_config import load_config
    return [str(t) for t in (load_config().get("skill_install_targets") or [])]


def remember_target(name: str) -> None:
    """任意パスの配布先を覚える。次回以降は更新対象に自動で入る。

    記憶を install() の中で行うのは、CLI と API のどちらから配っても同じに
    するため。呼び出し側に任せると片方で忘れる。組み込み名は常に status に
    出るので覚える必要がない
    """
    if name in BUILTIN_TARGETS:
        return
    config = _load_config_file()
    if config is None:
        return
    targets = list(config.get("skill_install_targets") or [])
    if name in targets:
        return
    targets.append(name)
    config["skill_install_targets"] = targets
    _save_config_file(config)


def _load_config_file() -> dict | None:
    """config.yaml を素で読む。読めない・壊れている場合は None（書き換えない）"""
    from shadow_clerk import CONFIG_FILE
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    except OSError:
        config = {}
    except yaml.YAMLError:
        return None
    return config if isinstance(config, dict) else None


def _save_config_file(config: dict) -> None:
    from shadow_clerk import CONFIG_FILE
    os.makedirs(os.path.dirname(CONFIG_FILE) or ".", exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    # FileWatcher が毎秒読むので、truncate 中の部分 YAML を読ませない
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
    os.replace(tmp, CONFIG_FILE)


# 改名前のスキル呼び出し。設定に直接書かれているので既定値の変更では直らない
_LEGACY_COMMANDS = ("/mtg",)


def migrate_init_prompt() -> bool:
    """設定に残った旧スキル名の呼び出しを新しい名前に直す。

    ai_assistant_init_prompt は利用者が明示的に持っている値なので、既定値を
    変えても効かない。放置すると会議のたびに存在しないコマンドが送られ、
    しかも失敗が AI コンソールの中にしか出ないので気づけない
    """
    config = _load_config_file()
    if not config:
        return False
    prompt = config.get("ai_assistant_init_prompt")
    if not isinstance(prompt, str):
        return False
    for legacy in _LEGACY_COMMANDS:
        if prompt == legacy or prompt.startswith(legacy + " "):
            config["ai_assistant_init_prompt"] = f"/{SKILL_NAME}" + prompt[len(legacy):]
            _save_config_file(config)
            logger.info("スキル呼び出しを移行しました: %r -> %r",
                        prompt, config["ai_assistant_init_prompt"])
            return True
    return False


def _as_tuple(version: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in version.split("."))


def skill_status(remembered: list[str]) -> dict:
    """組み込み2つ＋記憶した配布先の状態を返す。

    組み込みを常に含めるのは、まだどこにも配っていない利用者にも
    モーダルから配布先を選ばせるため
    """
    bundled = read_skill_version(bundled_skill_dir())
    names = list(BUILTIN_TARGETS) + [r for r in remembered if r not in BUILTIN_TARGETS]
    targets = []
    for name in names:
        _, dest = resolve_target(name)
        installed = read_skill_version(dest)
        if installed is None:
            state = "missing"
        elif bundled is not None and _as_tuple(installed) < _as_tuple(bundled):
            state = "outdated"
        else:
            state = "current"
        targets.append({"name": name, "path": str(dest),
                        "installed": installed, "state": state})
    return {"bundled": bundled, "targets": targets}
