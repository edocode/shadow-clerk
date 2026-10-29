"""shadow-clerk domain: 他の人に渡す声紋の書き出しファイル"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shadow_clerk.domain.speaker_group import is_color
from shadow_clerk.domain.voiceprint import PersonName, decode_embedding, encode_embedding

FORMAT = "shadow-clerk-voiceprints"
_VERSION = 1


@dataclass(frozen=True, eq=False)
class ExportedPerson:
    """1人分。samples は (埋め込み, 録音時刻)。どの会議で取ったか（source）は会議名が漏れるので持たない"""

    name: PersonName
    samples: tuple[tuple[np.ndarray, str], ...]
    group: str = ""
    color: str = ""
    person: bool = True


@dataclass(frozen=True, eq=False)
class VoiceprintExport:
    model: str
    exported_at: str
    people: tuple[ExportedPerson, ...]

    def to_dict(self) -> dict[str, object]:
        return {"format": FORMAT, "version": _VERSION, "model": self.model, "exported_at": self.exported_at,
                "people": [{"name": p.name.value, "group": p.group, "color": p.color, "person": p.person,
                            "samples": [{"emb": encode_embedding(e), "recorded_at": ts} for e, ts in p.samples]}
                           for p in self.people]}

    @classmethod
    def parse(cls, raw: object) -> VoiceprintExport:
        """JSON を読んだ dict から。形が違えば ValueError"""
        if not isinstance(raw, dict) or raw.get("format") != FORMAT:
            raise ValueError("声紋の書き出しファイルではない")
        if raw.get("version") != _VERSION:
            raise ValueError(f"対応していない版: {raw.get('version')}")
        people = []
        try:
            for p in raw["people"]:
                color = str(p.get("color") or "")
                people.append(ExportedPerson(
                    PersonName(p["name"]),
                    tuple((decode_embedding(s["emb"]), str(s["recorded_at"])) for s in p["samples"]),
                    str(p.get("group") or ""), color if is_color(color) else "", p.get("person") is not False))
        except (KeyError, TypeError, AttributeError) as e:
            raise ValueError(f"形が不正: {e}") from e
        if len({p.name.value for p in people}) != len(people):
            raise ValueError("同じ名前が2回ある")
        return cls(str(raw.get("model", "")), str(raw.get("exported_at", "")), tuple(people))
