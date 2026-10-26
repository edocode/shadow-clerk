"""会議ごとの起動ディレクトリ設定（会議ごとの起動ディレクトリ）"""
from __future__ import annotations
import logging
import os
import re
import shutil
from dataclasses import dataclass

import yaml

from shadow_clerk import DATA_DIR

logger = logging.getLogger("shadow-clerk")

# 設定は DATA_DIR に一本化する。~/.config/ は POSIX の作法で、Windows では
# C:\Users\<user>\.config\ という据わりの悪い場所になる。DATA_DIR は OS 差を
# 既に吸収している
_SEARCH_PATHS = (
    lambda: os.environ.get("MEETING_CONFIG") or "",
    lambda: os.path.join(DATA_DIR, "meeting.yaml"),
)

# 設定が無いときの書き込み先。探索順の最後と揃える
_DEFAULT_WRITE_PATH = os.path.join(DATA_DIR, "meeting.yaml")

# 改名前のバージョンが読んでいた場所。起動時に1度だけ新パスへ複製する
_LEGACY_PATHS = (
    lambda: os.environ.get("MTG_CONFIG") or "",
    lambda: os.path.join(
        os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
        "mtg", "config.yaml"),
    lambda: os.path.expanduser("~/.config/mtg/config.yaml"),
    lambda: os.path.join(DATA_DIR, "mtg.yaml"),
)


def migrate_legacy(legacy_paths: list[str] | None = None,
                   target: str | None = None) -> bool:
    """旧パスの設定を新パスへ複製する。旧ファイルは消さない。

    消さないのは、古いバージョンに戻したくなったときに設定ごと失わせないため。
    新パスが既にあれば何もしない——利用者が新しい方を育てている
    """
    target = target or _DEFAULT_WRITE_PATH
    if os.path.exists(target):
        return False
    candidates = legacy_paths if legacy_paths is not None else [get() for get in _LEGACY_PATHS]
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        shutil.copy2(path, target)
        logger.info("会議設定を移行しました: %s -> %s", path, target)
        return True
    return False


PUBLISH_TARGETS = ("artifact", "notion")


def literal_name(pattern: str) -> str:
    """会議名をそのまま書いたパターン（^…$ とエスケープを除いたもの）。メタ文字が残れば空"""
    body = pattern.removeprefix("^").removesuffix("$")
    if re.search(r"[.^$*+?{}\[\]|()]", re.sub(r"\\.", "", body)):
        return ""
    return re.sub(r"\\(.)", r"\1", body)


@dataclass(frozen=True)
class MeetingSettings:
    """会議ごとの設定のうち、ダッシュボードから変える値。None は変えない"""

    publish: bool | None = None
    workdir: str | None = None
    publish_to: str | None = None
    notion_url: str | None = None
    publish_advice: bool | None = None
    analyze: bool | None = None

    @classmethod
    def parse(cls, data: object) -> "MeetingSettings":
        """POST の set を検証する。不正なら ValueError"""
        if not isinstance(data, dict):
            raise ValueError("set must be an object")
        publish, workdir = data.get("publish"), data.get("workdir")
        publish_to, notion_url = data.get("publish_to"), data.get("notion_url")
        publish_advice, analyze = data.get("publish_advice"), data.get("analyze")
        for key, value in (("publish", publish), ("publish_advice", publish_advice), ("analyze", analyze)):
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
        if workdir is not None and not isinstance(workdir, str):
            raise ValueError("workdir must be a string")
        if publish_to is not None and publish_to not in PUBLISH_TARGETS:
            raise ValueError(f"publish_to must be one of {', '.join(PUBLISH_TARGETS)}")
        if notion_url is not None and not (isinstance(notion_url, str) and (
                not notion_url.strip() or notion_url.strip().startswith("https://"))):
            raise ValueError("notion_url must be an https URL")
        return cls(publish, workdir.strip() if workdir is not None else None, publish_to,
                   notion_url.strip() if notion_url is not None else None, publish_advice, analyze)

    def fields(self) -> dict:
        return {k: v for k, v in vars(self).items() if v is not None}


@dataclass(frozen=True)
class MeetingRule:
    """会議名パターンと、その会議での起動ディレクトリ"""

    pattern: str
    workdir: str


class MeetingConfig:
    """会議設定。shadow-clerk は workdir だけを読み書きする"""

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
    def load(cls, path: str | None = None) -> "MeetingConfig":
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
            logger.warning("会議設定の読み込みに失敗: %s (%s)", e, target)
        return cls(target, raw)

    # --- 読み ---

    def _meetings(self) -> list[dict]:
        entries = self.raw.get("meetings")
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []

    def rules(self) -> list[MeetingRule]:
        return [MeetingRule(str(e.get("pattern") or ""), str(e.get("workdir") or ""))
                for e in self._meetings() if e.get("pattern")]

    #: 設定が無くても動くための組み込み既定。get-config.sh と同じ値。
    #: `research`(調べものの当て先)が空なのは、このマシンの外へ問い合わせるものを
    #: 明示的に許可されたものだけにするため。どの当て先が社内かは環境ごとに違う
    DEFAULTS = {"analyze": True, "verbosity": "normal", "interval": 25,
                "publish": True, "publish_to": "artifact", "notion_url": "", "publish_advice": False,
                "workdir": "", "history": 3, "research": []}

    def _first_match(self, meeting_name: str) -> tuple[int, dict | None]:
        """meetings[] を上から照合し、最初に一致したルールと raw 上の位置を返す"""
        entries = self.raw.get("meetings")
        for i, entry in enumerate(entries if isinstance(entries, list) else []):
            if not isinstance(entry, dict) or not (pattern := entry.get("pattern")):
                continue
            try:
                if re.search(str(pattern), meeting_name, re.IGNORECASE):
                    return i, entry
            except re.error as e:
                # 人が手で書く設定なので壊れたパターンは起こりうる。
                # 全体を落とさず、そのルールだけ飛ばして次を見る
                logger.warning("会議設定の pattern が不正です %r: %s", pattern, e)
        return -1, None

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
        if (entry := self._first_match(meeting_name)[1]) is not None:
            matched, note = str(entry["pattern"]), str(entry.get("note") or "")
            resolved.update({k: v for k, v in entry.items() if k in self.DEFAULTS})
        resolved["workdir"] = (os.path.expanduser(str(resolved["workdir"]))
                               if resolved["workdir"] else "")
        resolved["research"] = self._research(resolved.get("research"))
        glossary = self.raw.get("glossary")
        return {**resolved, "matched": matched, "note": note,
                "config_path": self.path,
                "glossary": os.path.expanduser(str(glossary)) if glossary else ""}

    @classmethod
    def _research(cls, value: object) -> list[dict]:
        """調べものの当て先を正規化する。

        `allow_private` の既定は **False**（社外向けとして扱う）。社内の当て先だと
        書き忘れたときに、社内の固有名詞をそのまま外へ出してしまう向きに倒れない
        ようにする。
        """
        out: list[dict] = []
        for item in value if isinstance(value, list) else []:
            if isinstance(item, str):
                item = {"name": item}
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            out.append({"name": name,
                        "allow_private": bool(item.get("allow_private", False)),
                        "note": str(item.get("note") or "")})
        return out

    def resolve_workdir(self, meeting_name: str) -> str:
        """会議名に一致する最初のルールの workdir を返す。無ければ defaults、それも無ければ空"""
        if (entry := self._first_match(meeting_name)[1]) is not None:
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

    def apply(self, meeting_name: str, settings: MeetingSettings) -> None:
        """会議名ひとつに設定を書く。

        一致したルールがその会議名だけのもの（`週次定例` や `^週次定例$`）なら、それを更新する。
        別の名前向けの広いルールに一致していたら、そのルールの値を写した `^会議名$` のルールを
        その直前に足して変える。最初に一致したルールだけが効くので、後ろに足すと効かず、
        広いルールを書き換えるとほかの会議まで変わる
        """
        entries = self.raw.get("meetings")
        if not isinstance(entries, list):
            entries = self.raw["meetings"] = []
        index, entry = self._first_match(meeting_name)
        if entry is not None and literal_name(str(entry["pattern"])) == meeting_name:
            entry.update(settings.fields())
            return
        copied = {k: v for k, v in (entry or {}).items() if k in self.DEFAULTS}
        new = {"pattern": f"^{re.escape(meeting_name)}$", **copied, **settings.fields()}
        entries.insert(index if entry is not None else len(entries), new)

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
            logger.info("会議設定の初回書き換え前にバックアップを作成: %s", backup)
        except OSError as e:
            logger.warning("会議設定のバックアップ作成に失敗: %s", e)
