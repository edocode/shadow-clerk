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
from dataclasses import dataclass, field

from shadow_clerk import DATA_DIR
from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_constants import DEFAULT_CONFIG
from shadow_clerk.domain.voiceprint import PersonName, VoiceSample

logger = logging.getLogger("shadow-clerk")

VOICEPRINTS_FILE = os.path.join(DATA_DIR, "voiceprints.json")
_MAX_SAMPLES_DEFAULT = DEFAULT_CONFIG["voiceprint_max_samples"]
_VERSION = 1
_lock = threading.Lock()


def atomic_write_json(path: str, body: dict, prefix: str) -> None:
    """同じディレクトリの一時ファイルに書いて os.replace する（mkstemp は 0600 で作る）"""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@dataclass(frozen=True)
class StoreChange:
    """update で実際に外した・足したサンプルのキー（人の名前 → {(source, recorded_at)}）"""

    removed: dict[str, set[tuple[str, str]]] = field(default_factory=dict)
    added: dict[str, set[tuple[str, str]]] = field(default_factory=dict)


class VoiceprintStoreError(Exception):
    """voiceprints.json を読めない。空とみなして上書きすると溜めた声紋が消えるので、書き込みを止める"""


class VoiceprintStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = path or VOICEPRINTS_FILE

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
        atomic_write_json(self.path, {"version": _VERSION, "people": {n: {"samples": s} for n, s in people.items()}},
                          ".voiceprints-")

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
        self.update(samples_by_person, {})

    def update(self, add: dict[PersonName, list[VoiceSample]],
               remove: dict[str, set[tuple[str, str]]]) -> StoreChange:
        """remove の (source, recorded_at) に当たるサンプルを外し、add を足す。1回の読み書きで行う。空になった人は消す。
        実際に外した・足したキーを返す（既にない・既にある・上限で捨てたものは含めない）"""
        cap = int(load_config().get("voiceprint_max_samples", _MAX_SAMPLES_DEFAULT))
        change = StoreChange()
        with _lock:
            people = self._load()
            for name, keys in remove.items():
                kept = []
                for d in people.get(name, []):
                    if isinstance(d, dict) and (key := (d.get("source"), d.get("recorded_at"))) in keys:
                        change.removed.setdefault(name, set()).add(key)
                    else:
                        kept.append(d)
                if kept:
                    people[name] = kept
                else:
                    people.pop(name, None)
            for name, samples in add.items():
                merged = people.get(name.value, [])
                seen = {(d.get("source"), d.get("recorded_at")) for d in merged if isinstance(d, dict)}
                new: set[tuple[str, str]] = set()
                for sample in samples:
                    if sample.key not in seen:
                        seen.add(sample.key)
                        new.add(sample.key)
                        merged.append(sample.to_dict())
                people[name.value] = merged = merged[-cap:] if cap > 0 else merged
                if stored := new & {(d.get("source"), d.get("recorded_at")) for d in merged if isinstance(d, dict)}:
                    change.added[name.value] = stored
            self._save(people)
        return change

    def relocate_source(self, old: str, new: str, ts_range: tuple[str, str] | None = None) -> int:
        """source が old（かつ ts_range 内の recorded_at）のサンプルの source を new に付け替え、件数を返す"""
        n = 0
        with _lock:
            people = self._load()
            for samples in people.values():
                for d in samples:
                    if (isinstance(d, dict) and d.get("source") == old
                            and (ts_range is None or ts_range[0] <= str(d.get("recorded_at", "")) <= ts_range[1])):
                        d["source"] = new
                        n += 1
            if n:
                self._save(people)
        return n

    def delete(self, name: str) -> bool:
        with _lock:
            people = self._load()
            if name not in people:
                return False
            del people[name]
            self._save(people)
            return True
