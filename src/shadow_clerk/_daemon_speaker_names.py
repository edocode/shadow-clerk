"""Shadow-clerk daemon: 話者の名前帳

名前付けで付けたラベル（人名、または会社名・役割名）と、そのグループ・色を
DATA_DIR/speaker_names.json に覚える。声紋は含まない（生体情報ではない）。
どの会議でも候補に出し、文字起こしの色分けと議事録のグループ別整理に使う。
"""
from __future__ import annotations

import json
import logging
import os
import threading

from shadow_clerk import DATA_DIR
from shadow_clerk._atomic_file import atomic_write_json
from shadow_clerk.domain.speaker_group import GroupName, SpeakerEntry, is_color, next_group_color
from shadow_clerk.domain.voiceprint import PersonName

logger = logging.getLogger("shadow-clerk")

SPEAKER_NAMES_FILE = os.path.join(DATA_DIR, "speaker_names.json")
_VERSION = 2
_lock = threading.Lock()


class SpeakerNameBookError(Exception):
    """speaker_names.json を読めない。空とみなして上書きすると溜めた名前が消えるので、書き込みを止める"""


class SpeakerNameBook:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or SPEAKER_NAMES_FILE

    def _load(self) -> tuple[dict[str, SpeakerEntry], dict[str, str]]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}, {}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            raise SpeakerNameBookError(f"{self.path}: {e}") from e
        raw = data.get("names") if isinstance(data, dict) else None
        if isinstance(raw, list):  # v1: 名前の配列だけ
            if not all(isinstance(n, str) for n in raw):
                raise SpeakerNameBookError(f"{self.path}: names が文字列の配列ではない")
            return {n: SpeakerEntry() for n in raw}, {}
        if not isinstance(raw, dict):
            raise SpeakerNameBookError(f"{self.path}: names がない")
        try:
            names = {str(n): SpeakerEntry.from_dict(e) for n, e in raw.items()}
        except ValueError as e:
            raise SpeakerNameBookError(f"{self.path}: {e}") from e
        groups = data.get("groups", {})
        if not isinstance(groups, dict) or not all(isinstance(g, str) and is_color(c) for g, c in groups.items()):
            raise SpeakerNameBookError(f"{self.path}: groups が不正")
        return names, dict(groups)

    def _save(self, names: dict[str, SpeakerEntry], groups: dict[str, str]) -> None:
        atomic_write_json(self.path, {"version": _VERSION,
                                      "names": {n: e.to_dict() for n, e in sorted(names.items())},
                                      "groups": dict(sorted(groups.items()))}, ".speaker-names-")

    @staticmethod
    def _color_for(group: str, groups: dict[str, str]) -> bool:
        """group に色が無ければ割り当てる。割り当てたら True"""
        if not group or group in groups:
            return False
        groups[group] = next_group_color(groups.values())
        return True

    def entries(self) -> dict[str, SpeakerEntry]:
        with _lock:
            return self._load()[0]

    def groups(self) -> dict[str, str]:
        with _lock:
            return self._load()[1]

    def set_entry(self, name: PersonName, group: GroupName | None, person: bool) -> None:
        with _lock:
            current, groups = self._load()
            entry = SpeakerEntry(group.value if group else "", person)
            changed = current.get(name.value) != entry
            current[name.value] = entry
            if self._color_for(entry.group, groups) or changed:
                self._save(current, groups)

    def set_group(self, name: str, group: GroupName | None) -> bool:
        with _lock:
            current, groups = self._load()
            if name not in current:
                return False
            entry = SpeakerEntry(group.value if group else "", current[name].person)
            changed = current[name] != entry
            current[name] = entry
            if self._color_for(entry.group, groups) or changed:
                self._save(current, groups)
            return True

    def ensure_group(self, group: GroupName) -> str:
        with _lock:
            current, groups = self._load()
            if self._color_for(group.value, groups):
                self._save(current, groups)
            return groups[group.value]

    def remove(self, name: str) -> bool:
        with _lock:
            current, groups = self._load()
            if name not in current:
                return False
            del current[name]
            self._save(current, groups)
            return True
