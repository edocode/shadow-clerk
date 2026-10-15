"""Shadow-clerk daemon: 話者一覧（transcript の話者 × 名前帳のグループ）

議事録の LLM プロンプトと、AI アシスタント（スキル）向け API の両方に渡す。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from shadow_clerk.i18n import nt
from shadow_clerk._daemon_speaker_names import SpeakerNameBook, SpeakerNameBookError
from shadow_clerk.domain.speaker import Speaker
from shadow_clerk.domain.speaker_group import SpeakerEntry
from shadow_clerk.domain.transcript_line import TranscriptLine

logger = logging.getLogger("shadow-clerk")

_UNLABELED = frozenset({"相手?", Speaker.OTHER.value})


@dataclass(frozen=True)
class RosterEntry:
    label: str
    group: str
    is_self: bool
    person: bool  # 台帳で個人と記録されているか（会社名・役割名のラベルや未登録は False）

    def to_dict(self) -> dict[str, object]:
        return {"label": self.label, "group": self.group, "self": self.is_self, "person": self.person}


def build_roster(lines: list[str], entries: dict[str, SpeakerEntry], self_group: str) -> list[RosterEntry]:
    """transcript に出てくる話者を出現順に返す"""
    out: dict[str, RosterEntry] = {}
    for line in lines:
        tl = TranscriptLine.parse(line)
        if tl is None:
            continue
        if tl.speaker == Speaker.SELF:
            out.setdefault(Speaker.SELF.value, RosterEntry(Speaker.SELF.value, self_group, True, True))
        elif tl.speaker == Speaker.OTHER and tl.speaker_label and tl.speaker_label not in _UNLABELED:
            e = entries.get(tl.speaker_label)
            out.setdefault(tl.speaker_label,
                           RosterEntry(tl.speaker_label, e.group if e else "", False, e.person if e else False))
    return list(out.values())


def roster_prompt_block(roster: list[RosterEntry], self_group: str) -> str:
    """議事録プロンプトに足す話者とグループの説明。グループが1つも無ければ何も足さない"""
    groups = {e.group for e in roster if e.group} | ({self_group} if self_group else set())
    if not groups:
        return ""
    unknown = nt("llm.summary_speakers_unknown_group")
    speakers = "\n".join(f"- {e.label}: {e.group or unknown}"
                         + (nt("llm.summary_speakers_self_mark") if e.is_self else "") for e in roster)
    block = nt("llm.summary_speakers_block", speakers=speakers, self_group=self_group or unknown)
    if len(groups) >= 2:
        block += nt("llm.summary_groups_instruction")
    return block


def load_roster(lines: list[str], self_group: str) -> list[RosterEntry]:
    try:
        entries = SpeakerNameBook().entries()
    except SpeakerNameBookError as e:
        logger.warning("名前帳を読めないので話者のグループなしで扱う: %s", e)
        entries = {}
    return build_roster(lines, entries, self_group)
