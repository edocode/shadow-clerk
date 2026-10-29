"""Shadow-clerk daemon: 声紋の書き出し・取り込み

よく使っている人の声紋を、あまり使っていない人に渡す。書き出しは照合に使っているサンプル
（外れ値を除く）と名前帳のグループ・色だけで、どの会議で取ったか（会議名）は含めない。
取り込んだサンプルは origin=import / source=import で、元からある声紋と区別できる。
"""
from __future__ import annotations

import datetime
import logging

from shadow_clerk._daemon_speaker_diarization import EMBEDDING_MODEL
from shadow_clerk._daemon_speaker_names import SpeakerNameBook
from shadow_clerk._daemon_voiceprint_clusters import majority_shape
from shadow_clerk._daemon_voiceprint_store import VoiceprintStore
from shadow_clerk.domain.speaker_group import GroupName
from shadow_clerk.domain.voiceprint import IMPORT_SOURCE, PersonName, SampleOrigin, SampleStatus, VoiceSample
from shadow_clerk.domain.voiceprint_export import ExportedPerson, VoiceprintExport

logger = logging.getLogger("shadow-clerk")


class ModelMismatchError(Exception):
    """書き出したモデルが違う。埋め込みを比べられない"""


def build_export(names: list[str], store: VoiceprintStore | None = None,
                 book: SpeakerNameBook | None = None) -> VoiceprintExport:
    """names の人の声紋を書き出す。声紋の無い人は入れない"""
    store, book = store or VoiceprintStore(), book or SpeakerNameBook()
    entries, groups = book.entries(), book.groups()
    people = []
    for name in sorted(set(names)):
        samples = [s for s in store.samples(PersonName(name)) if s.status is not SampleStatus.OUTLIER]
        samples = [samples[i] for i in majority_shape([s.embedding for s in samples])]
        if not samples:
            continue
        entry = entries.get(name)
        group = entry.group if entry else ""
        people.append(ExportedPerson(PersonName(name), tuple((s.embedding, s.recorded_at) for s in samples),
                                     group, groups.get(group, ""), entry.person if entry else True))
    return VoiceprintExport(EMBEDDING_MODEL, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), tuple(people))


def import_export(exp: VoiceprintExport, mapping: dict[str, str], store: VoiceprintStore | None = None,
                  book: SpeakerNameBook | None = None) -> dict[str, int]:
    """mapping（ファイル上の名前 → 取り込み先の名前）にある人だけ取り込み、取り込み先 → 足した件数を返す。
    名前帳に無い取り込み先は、ファイルのグループ・色で名前帳にも足す（ある人のグループは変えない）。
    モデルが違えば ModelMismatchError、取り込み先の名前が不正なら ValueError（何も書かない）"""
    if exp.model != EMBEDDING_MODEL:
        raise ModelMismatchError(exp.model)
    store, book = store or VoiceprintStore(), book or SpeakerNameBook()
    picked = [(p, PersonName(mapping[p.name.value])) for p in exp.people if p.name.value in mapping]
    adds: dict[PersonName, list[VoiceSample]] = {}
    for p, target in picked:
        adds.setdefault(target, []).extend(
            VoiceSample(e, ts, IMPORT_SOURCE, origin=SampleOrigin.IMPORTED) for e, ts in p.samples)
    change = store.update(adds, {})
    known = set(book.entries())
    for p, target in picked:
        if target.value in known:
            continue
        known.add(target.value)
        try:
            group = GroupName(p.group) if p.group else None
        except ValueError:
            group = None
        if group:
            book.ensure_group(group, p.color)
        book.set_entry(target, group, p.person)
    added = {n.value: len(change.added.get(n.value, ())) for n in adds}
    logger.info("声紋を取り込み: %s", added)
    return added
