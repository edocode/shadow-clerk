"""mtg スキルの設定ファイル（会議ごとの起動ディレクトリ）"""
from __future__ import annotations
import logging
import os
import re
import shutil
from dataclasses import dataclass

import yaml

from shadow_clerk import DATA_DIR

logger = logging.getLogger("shadow-clerk")

# スキル側の get-config.sh と同じ探索順。どちらから編集しても同じファイルを見る
_SEARCH_PATHS = (
    lambda: os.environ.get("MTG_CONFIG") or "",
    lambda: os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "mtg", "config.yaml"),
    lambda: os.path.expanduser("~/.config/mtg/config.yaml"),
    lambda: os.path.join(DATA_DIR, "mtg.yaml"),
)

# 設定が無いときの書き込み先。探索順の最後と揃える
_DEFAULT_WRITE_PATH = os.path.join(DATA_DIR, "mtg.yaml")


@dataclass(frozen=True)
class MtgRule:
    """会議名パターンと、その会議での起動ディレクトリ"""

    pattern: str
    workdir: str


class MtgConfig:
    """mtg スキルの config.yaml。shadow-clerk は workdir だけを読み書きする"""

    def __init__(self, path: str, raw: dict) -> None:
        self.path = path
        self.raw = raw

    @classmethod
    def locate(cls) -> str | None:
        for get in _SEARCH_PATHS:
            path = get()
            if path and os.path.isfile(path):
                return path
        return None

    @classmethod
    def load(cls, path: str | None = None) -> "MtgConfig":
        target = path or cls.locate() or _DEFAULT_WRITE_PATH
        raw: dict = {}
        try:
            with open(target, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if isinstance(loaded, dict):
                raw = loaded
        except OSError:
            pass  # 未作成。空の設定として扱う
        except yaml.YAMLError as e:
            logger.warning("mtg 設定の読み込みに失敗: %s (%s)", e, target)
        return cls(target, raw)

    # --- 読み ---

    def _meetings(self) -> list[dict]:
        entries = self.raw.get("meetings")
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []

    def rules(self) -> list[MtgRule]:
        return [MtgRule(str(e.get("pattern") or ""), str(e.get("workdir") or ""))
                for e in self._meetings() if e.get("pattern")]

    #: 設定が無くても動くための組み込み既定。get-config.sh と同じ値
    DEFAULTS = {"analyze": True, "verbosity": "normal", "interval": 25,
                "publish": True, "workdir": "", "history": 3}

    def resolve(self, meeting_name: str) -> dict:
        """会議名に対する設定を解決する。

        `meetings[]` を上から照合し、最初に一致したルールを `defaults` に重ねる。
        判定をここ 1 か所に持つ——同じ規則を shell と Python の両方に置くと、
        片方だけ直したときに黙ってずれる。
        """
        resolved = dict(self.DEFAULTS)
        defaults = self.raw.get("defaults")
        if isinstance(defaults, dict):
            resolved.update({k: v for k, v in defaults.items() if k in self.DEFAULTS})
        matched, note = "(defaults)", ""
        for entry in self._meetings():
            pattern = entry.get("pattern")
            if not pattern:
                continue
            try:
                hit = re.search(str(pattern), meeting_name, re.IGNORECASE)
            except re.error as e:
                # 人が手で書く設定なので壊れたパターンは起こりうる。
                # 全体を落とさず、そのルールだけ飛ばして次を見る
                logger.warning("mtg 設定の pattern が不正です %r: %s", pattern, e)
                continue
            if hit:
                matched = str(pattern)
                note = str(entry.get("note") or "")
                resolved.update({k: v for k, v in entry.items() if k in self.DEFAULTS})
                break
        resolved["workdir"] = (os.path.expanduser(str(resolved["workdir"]))
                               if resolved["workdir"] else "")
        glossary = self.raw.get("glossary")
        return {**resolved, "matched": matched, "note": note,
                "config_path": self.path,
                "glossary": os.path.expanduser(str(glossary)) if glossary else ""}

    def resolve_workdir(self, meeting_name: str) -> str:
        """会議名に一致する最初のルールの workdir を返す。無ければ defaults、それも無ければ空"""
        for entry in self._meetings():
            pattern = entry.get("pattern")
            if not pattern:
                continue
            try:
                matched = re.search(str(pattern), meeting_name, re.IGNORECASE)
            except re.error as e:
                # 人が手で書く設定なので不正なパターンは起こりうる。
                # 全体を落とさず、そのルールだけ飛ばして次を見る
                logger.warning("mtg 設定の pattern が不正です %r: %s", pattern, e)
                continue
            if matched:
                return str(entry.get("workdir") or self._default_workdir())
        return self._default_workdir()

    def _default_workdir(self) -> str:
        defaults = self.raw.get("defaults")
        if isinstance(defaults, dict):
            return str(defaults.get("workdir") or "")
        return ""

    # --- 書き ---

    def upsert(self, pattern: str, workdir: str) -> None:
        """pattern のルールの workdir を更新する。無ければ末尾に足す。

        既存ルールの他のキー (publish / verbosity / note …) はスキル側が読む値なので
        触らない。ここで扱うのは workdir だけ。
        """
        entries = self.raw.setdefault("meetings", [])
        if not isinstance(entries, list):
            entries = []
            self.raw["meetings"] = entries
        for entry in entries:
            if isinstance(entry, dict) and str(entry.get("pattern") or "") == pattern:
                entry["workdir"] = workdir
                return
        entries.append({"pattern": pattern, "workdir": workdir})

    def remove(self, pattern: str) -> None:
        entries = self.raw.get("meetings")
        if not isinstance(entries, list):
            return
        self.raw["meetings"] = [
            e for e in entries
            if not (isinstance(e, dict) and str(e.get("pattern") or "") == pattern)]

    def save(self, path: str | None = None) -> str:
        """一時ファイル → os.replace でアトミックに書く。書いたパスを返す"""
        target = path or self.path
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        self._backup_if_foreign(target)
        tmp = f"{target}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.raw, f, default_flow_style=False, allow_unicode=True,
                           sort_keys=False)
        os.replace(tmp, target)
        self.path = target
        return target

    def _backup_if_foreign(self, target: str) -> None:
        """shadow-clerk が作ったのではない既存ファイルを初めて書き換える前に、
        隣へ <path>.bak を残す。

        ~/.config/mtg/config.yaml はユーザーが手で保守しているファイルで、
        note: キーや行間のコメントが入りうる。yaml.safe_dump はキーと順序は
        保つが、コメント・空行・引用スタイルは破棄してしまうため、初回だけ
        元の内容を退避する。_DEFAULT_WRITE_PATH (shadow-clerk 自身が作る
        書き込み先) は対象外: そこは shadow-clerk 自身が作った状態であり、
        ユーザーが手で保守しているファイルではない
        """
        if target == _DEFAULT_WRITE_PATH or not os.path.isfile(target):
            return
        backup = f"{target}.bak"
        if os.path.exists(backup):
            return  # 最初の1回だけ残す
        try:
            shutil.copyfile(target, backup)
            logger.info("mtg 設定の初回書き換え前にバックアップを作成: %s", backup)
        except OSError as e:
            logger.warning("mtg 設定のバックアップ作成に失敗: %s", e)
