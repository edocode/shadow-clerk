"""Shadow-clerk daemon: 声紋ストア

人ごとの埋め込みを DATA_DIR/voiceprints.json に保存する。声紋は生体情報なので
ローカルにだけ置き、ファイルは本人だけが読める権限 (0600) で書く。
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field, replace

import numpy as np

from shadow_clerk import DATA_DIR
from shadow_clerk._atomic_file import atomic_write_json
from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_voiceprint_clusters import ClusterKind, cluster_samples, majority_shape, voiceprint_number
from shadow_clerk.domain.voiceprint import PersonName, SampleStatus, VoiceSample

logger = logging.getLogger("shadow-clerk")

VOICEPRINTS_FILE = os.path.join(DATA_DIR, "voiceprints.json")
_VERSION = 1
_lock = threading.Lock()


def _restatus(raw: list[dict]) -> None:
    """塊分けして外れ値の塊のサンプルを OUTLIER に、それ以外を NORMAL にする（KEPT と読めないものは触らない）"""
    items: list[tuple[dict, VoiceSample]] = []
    for d in raw:
        try:
            items.append((d, VoiceSample.from_dict(d)))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    items = [items[i] for i in majority_shape([s.embedding for _, s in items])]  # 次元違いは触らない
    outliers = {i for c in cluster_samples([s.embedding for _, s in items]) if c.kind is ClusterKind.OUTLIER
                for i in c.members}
    for i, (d, s) in enumerate(items):
        if s.status is SampleStatus.KEPT:
            continue
        if i in outliers:
            d["status"] = SampleStatus.OUTLIER.value
        else:
            d.pop("status", None)


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
        self._pools_cache: tuple[tuple[int, int, int], dict[str, np.ndarray]] | None = None

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

    def candidate_pools(self) -> dict[str, np.ndarray]:
        """人 → (n, D) の埋め込み行列。外れ値を除き多数派の次元だけ、0 件の人は入れない。mtime・サイズ・inode が変わるまで前回の結果を返す"""
        try:
            st = os.stat(self.path)
            sig = (st.st_mtime_ns, st.st_size, st.st_ino)
        except FileNotFoundError:
            sig = (0, 0, 0)
        except OSError as e:
            raise VoiceprintStoreError(f"{self.path}: {e}") from e
        if self._pools_cache and self._pools_cache[0] == sig:
            return self._pools_cache[1]
        with _lock:
            raw = self._load()
        pools: dict[str, np.ndarray] = {}
        for name, items in raw.items():
            embs = []
            broken = 0
            for d in items:
                try:
                    s = VoiceSample.from_dict(d)
                except (KeyError, TypeError, ValueError, AttributeError):
                    broken += 1
                    continue
                if s.status is not SampleStatus.OUTLIER:
                    embs.append(s.embedding)
            kept = [embs[i] for i in majority_shape(embs)]
            if dropped := broken + len(embs) - len(kept):  # 読み直したときだけ（キャッシュ中は黙る）
                logger.warning("声紋の照合に使えないサンプルを除いた: %s %d 件", name, dropped)
            if kept:
                pools[name] = np.stack(kept).astype(np.float32)
                pools[name].setflags(write=False)  # キャッシュを共有するので呼び出し側に書き換えさせない
        self._pools_cache = (sig, pools)
        return pools

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
        実際に外した・足したキーを返す（既にない・既にある・上限で捨てたものは含めない）。
        同じ人から外して足し直すキーは外さずに残す（status と上限の順番を保つ）。触った人は除外を判定し直す"""
        cap = int(voiceprint_number(load_config(), "voiceprint_max_samples"))
        change = StoreChange()
        readd = {n.value: {s.key for s in samples} for n, samples in add.items()}
        with _lock:
            people = self._load()
            for name, keys in remove.items():
                keys = keys - readd.get(name, set())
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
            for name in {n.value for n in add} | set(change.removed):
                if name in people:
                    _restatus(people[name])
            self._save(people)
        return change

    def remove_samples(self, name: str, keys: set[tuple[str, str]]) -> int:
        """name のサンプルのうち keys に当たるものを外し、外した件数を返す"""
        return len(self.update({}, {name: keys}).removed.get(name, ()))

    def move_samples(self, src: str, dst: PersonName, keys: set[tuple[str, str]]) -> int:
        """src のサンプルのうち keys に当たるものを status を NORMAL に戻して dst へ移し、src から外した件数を返す"""
        if src == dst.value:
            return 0
        picked = [replace(s, status=SampleStatus.NORMAL) for s in self.samples(PersonName(src)) if s.key in keys]
        if not picked:
            return 0
        return len(self.update({dst: picked}, {src: {s.key for s in picked}}).removed.get(src, ()))

    def set_status(self, name: str, keys: set[tuple[str, str]], status: SampleStatus) -> int:
        """name のサンプルのうち keys に当たるものの status を変え、変えた件数を返す"""
        n = 0
        with _lock:
            people = self._load()
            for d in people.get(name, []):
                if isinstance(d, dict) and (d.get("source"), d.get("recorded_at")) in keys:
                    if status is SampleStatus.NORMAL:
                        n += d.pop("status", None) is not None
                    else:
                        n += d.get("status") != status.value
                        d["status"] = status.value
            if n:
                self._save(people)
        return n

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
