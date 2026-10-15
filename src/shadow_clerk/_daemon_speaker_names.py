"""Shadow-clerk daemon: 話者名の名簿

名前付けで付けた名前を DATA_DIR/speaker_names.json に覚えておく。名前だけで声紋は含まない
（生体情報ではない）。どの会議でも候補に出すために使う。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Iterable

from shadow_clerk import DATA_DIR
from shadow_clerk._daemon_voiceprint_store import atomic_write_json
from shadow_clerk.domain.voiceprint import PersonName

logger = logging.getLogger("shadow-clerk")

SPEAKER_NAMES_FILE = os.path.join(DATA_DIR, "speaker_names.json")
_VERSION = 1
_lock = threading.Lock()


class SpeakerNameBookError(Exception):
    """speaker_names.json を読めない。空とみなして上書きすると溜めた名前が消えるので、書き込みを止める"""


class SpeakerNameBook:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or SPEAKER_NAMES_FILE

    def _load(self) -> set[str]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return set()
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            raise SpeakerNameBookError(f"{self.path}: {e}") from e
        names = data.get("names") if isinstance(data, dict) else None
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise SpeakerNameBookError(f"{self.path}: names がない、または文字列の配列ではない")
        return set(names)

    def _save(self, names: set[str]) -> None:
        atomic_write_json(self.path, {"version": _VERSION, "names": sorted(names)}, ".speaker-names-")

    def names(self) -> list[str]:
        with _lock:
            return sorted(self._load())

    def add(self, names: Iterable[PersonName]) -> None:
        with _lock:
            current = self._load()
            merged = current | {n.value for n in names}
            if merged != current:
                self._save(merged)

    def remove(self, name: str) -> bool:
        with _lock:
            current = self._load()
            if name not in current:
                return False
            self._save(current - {name})
            return True
