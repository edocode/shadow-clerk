"""Shadow-clerk daemon: 声紋ストア

人ごとの埋め込みを DATA_DIR/voiceprints.json に保存する。声紋は生体情報なので
ローカルにだけ置き、ファイルは本人だけが読める権限 (0600) で書く。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading

from shadow_clerk import DATA_DIR
from shadow_clerk._daemon_config import load_config
from shadow_clerk.domain.voiceprint import PersonName, VoiceSample

logger = logging.getLogger("shadow-clerk")

VOICEPRINTS_FILE = os.path.join(DATA_DIR, "voiceprints.json")
_MAX_SAMPLES_DEFAULT = 200
_VERSION = 1
_lock = threading.Lock()


class VoiceprintStoreError(Exception):
    """voiceprints.json を読めない。空とみなして上書きすると溜めた声紋が消えるので、書き込みを止める"""


class VoiceprintStore:
    def __init__(self, path: str = VOICEPRINTS_FILE) -> None:
        self.path = path

    def _load(self) -> dict[str, list[dict]]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            raise VoiceprintStoreError(f"{self.path}: {e}") from e
        people = data.get("people") if isinstance(data, dict) else None
        if not isinstance(people, dict):
            raise VoiceprintStoreError(f"{self.path}: people がない")
        result = {}
        for name, p in people.items():
            if not isinstance(p, dict):
                raise VoiceprintStoreError(f"{self.path}: person entry for {name} is not a dict")
            samples = p.get("samples")
            if samples is not None and not isinstance(samples, list):
                raise VoiceprintStoreError(f"{self.path}: samples for {name} is not a list")
            result[name] = list(samples or [])
        return result

    def _save(self, people: dict[str, list[dict]]) -> None:
        body = {"version": _VERSION, "people": {n: {"samples": s} for n, s in people.items()}}
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path) or ".", prefix=".voiceprints-",
                                   suffix=".tmp")  # mkstemp は 0600 で作る
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(body, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def people(self) -> dict[str, int]:
        with _lock:
            return {name: len(s) for name, s in sorted(self._load().items())}

    def samples(self, name: PersonName) -> list[VoiceSample]:
        with _lock:
            raw = self._load().get(name.value, [])
        out: list[VoiceSample] = []
        for d in raw:
            try:
                out.append(VoiceSample.from_dict(d))
            except (KeyError, TypeError, ValueError):
                logger.warning("声紋の壊れたサンプルを飛ばす: %s", name.value)
        return out

    def add(self, samples_by_person: dict[PersonName, list[VoiceSample]]) -> None:
        cap = int(load_config().get("voiceprint_max_samples", _MAX_SAMPLES_DEFAULT))
        with _lock:
            people = self._load()
            for name, samples in samples_by_person.items():
                merged = people.get(name.value, []) + [s.to_dict() for s in samples]
                people[name.value] = merged[-cap:] if cap > 0 else merged
            self._save(people)

    def delete(self, name: str) -> bool:
        with _lock:
            people = self._load()
            if name not in people:
                return False
            del people[name]
            self._save(people)
            return True
