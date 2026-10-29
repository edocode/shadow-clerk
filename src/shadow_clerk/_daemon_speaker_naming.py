"""Shadow-clerk daemon: 話者の名前付け（会議内ラベル → 人名）の純粋な処理"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from shadow_clerk._daemon_speaker_diarization import label_index
from shadow_clerk.domain.speaker import Speaker
from shadow_clerk.domain.speaker_group import GroupName, SpeakerEntry
from shadow_clerk.domain.transcript_line import TranscriptLine
from shadow_clerk.domain.voiceprint import PersonName, tentative_name


_UNASSIGNED = frozenset({"相手?", Speaker.OTHER.value})


@dataclass(frozen=True)
class LabelSummary:
    label: str
    count: int
    example: str  # 誰だったか思い出せるよう、最長の発話を見せる
    named: bool = False  # 名前付け済み（相手A 等ではなく人名）。「alice?」も含む

    @property
    def suggested(self) -> str | None:
        """会議中の識別で「alice?」と出たラベルなら、確認用に事前入力する名前 alice"""
        return tentative_name(self.label)

    @property
    def tentative(self) -> bool:
        return self.suggested is not None


def summarize_labels(lines: list[str]) -> list[LabelSummary]:
    """名前付けの対象ラベルを返す。相手A 等を番号順、続けて付け済みの人名を名前順（相手? と 相手 は除く）"""
    counts: dict[str, int] = {}
    longest: dict[str, str] = {}
    for line in lines:
        tl = TranscriptLine.parse(line)
        if (tl is None or tl.speaker != Speaker.OTHER or not tl.speaker_label
                or tl.speaker_label in _UNASSIGNED):
            continue
        label = tl.speaker_label
        counts[label] = counts.get(label, 0) + 1
        if len(tl.text) > len(longest.get(label, "")):
            longest[label] = tl.text
    order = sorted(counts, key=lambda lb: (label_index(lb) is None, label_index(lb) or 0, lb))
    return [LabelSummary(lb, counts[lb], longest[lb], label_index(lb) is None) for lb in order]


def relabel_lines_where(lines: list[str], pick: Callable[[TranscriptLine], str | None]) -> tuple[list[str], int]:
    """pick が新しいラベルを返した行だけ書き換え、行と書き換えた行数を返す。行数は変えない"""
    out: list[str] = []
    renamed = 0
    for line in lines:
        tl = TranscriptLine.parse(line)
        new = pick(tl) if tl is not None else None
        if tl is not None and new is not None and new != tl.speaker_label:
            line = TranscriptLine(tl.timestamp, tl.speaker, tl.text, new).format()
            renamed += 1
        out.append(line)
    return out, renamed


def line_key(tl: TranscriptLine) -> tuple[str, str] | None:
    """付け替えられる行の (時刻, 今のラベル)。相手側（分離なしの行は「相手」）と自分の行。Claude の行は None"""
    if tl.speaker == Speaker.OTHER:
        return tl.timestamp, tl.speaker_label or Speaker.OTHER.value
    return (tl.timestamp, Speaker.SELF.value) if tl.speaker == Speaker.SELF else None


def relabelable_keys(lines: list[str]) -> set[tuple[str, str]]:
    return {k for ln in lines if (tl := TranscriptLine.parse(ln)) and (k := line_key(tl))}


def line_target_picker(targets: set[tuple[str, str]], new_label: str) -> Callable[[TranscriptLine], str | None]:
    """(時刻, 今のラベル) が targets にある行だけ new_label にする"""
    return lambda tl: new_label if line_key(tl) in targets else None


def range_targets(lines: list[str], ends: set[tuple[str, str]]) -> set[tuple[str, str]] | None:
    """2 行 ends（時刻, ラベル）の時刻の間（両端を含む）にある相手側の行を、話者を問わず targets の形で返す。
    自分の行は、端のどちらかが自分の行のときだけ含める（相手の行だけ付け替えたいときに自分の行を巻き込まない）。
    ends が 2 行でないか、どちらかが付け替えられる行として無ければ None"""
    keys = relabelable_keys(lines)
    if len(ends) != 2 or not ends <= keys:
        return None
    lo, hi = min(ts for ts, _ in ends), max(ts for ts, _ in ends)
    with_self = any(label == Speaker.SELF.value for _, label in ends)
    return {k for k in keys if lo <= k[0] <= hi and (with_self or k[1] != Speaker.SELF.value)}


@dataclass(frozen=True)
class Assignment:
    """ダッシュボードから来た1件の割り当て。group None は台帳の値を保つ、"" はグループなし。
    confirm: 会議中の識別で付いた行（サイドカーの auto）を、人が確認したとして声紋に足す"""
    name: PersonName
    group: str | None = None
    person: bool | None = None
    confirm: bool = False


def parse_assignment(raw: object) -> Assignment:
    if isinstance(raw, str):
        return Assignment(PersonName(raw))
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
        raise ValueError("割り当ての形式が不正")
    group, person, confirm = raw.get("group"), raw.get("person"), raw.get("confirm", False)
    if ((group is not None and not isinstance(group, str)) or (person is not None and not isinstance(person, bool))
            or not isinstance(confirm, bool)):
        raise ValueError("割り当ての型が不正")
    if group is not None:
        group = GroupName(group).value if group.strip() else ""
    return Assignment(PersonName(raw["name"]), group, person, confirm)


@dataclass(frozen=True)
class Decision:
    """台帳と照らして決まった割り当て"""
    name: PersonName
    group: str
    person: bool

    def entry(self) -> SpeakerEntry:
        return SpeakerEntry(self.group, self.person)

    def changes(self, label: str, entries: dict[str, SpeakerEntry]) -> bool:
        return self.name.value != label or entries.get(self.name.value) != self.entry()


def decide_assignment(a: Assignment, entries: dict[str, SpeakerEntry], groups: dict[str, str]) -> Decision:
    current = entries.get(a.name.value)
    group = a.group if a.group is not None else (current.group if current else "")
    if a.person is not None:
        person = a.person
    elif current is not None:
        person = current.person
    else:
        person = a.name.value not in groups  # グループ名そのままなら会社名のラベルとみなす
    return Decision(a.name, group, person)


def remap_offset(old_lines: list[str], new_lines: list[str], old_offset: int) -> int:
    """書き換え前の translate_offset（バイト）を、書き換え後の同じ位置へ移す。

    名前とラベルはバイト長が違うので、現サイズへのリセットでは未翻訳の末尾を
    翻訳済みとみなし、0 への巻き戻しでは全文を翻訳し直してしまう
    """
    old_pos = new_pos = 0
    for old, new in zip(old_lines, new_lines):
        ob, nb = len(old.encode("utf-8")), len(new.encode("utf-8"))
        if old_pos + ob > old_offset:
            return new_pos + min(old_offset - old_pos, nb)
        old_pos += ob
        new_pos += nb
    return new_pos + max(0, old_offset - old_pos)
