"""TalkVoice の検証

実行: uv run python tests/test_talk_voice.py
"""
from __future__ import annotations
import sys

from shadow_clerk.domain import TalkVoice

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_parse() -> None:
    v = TalkVoice.parse({"speaker_id": 8, "speed": 1.3, "pitch": -0.05, "intonation": 1, "volume": 0.8})
    check("値をそのまま持つ", v == TalkVoice(8, 1.3, -0.05, 1.0, 0.8), repr(v))
    check("省略した項目は既定値", TalkVoice.parse({}) == TalkVoice(), repr(TalkVoice.parse({})))
    for raw, label in [({"speed": 3.0}, "範囲外の話速"), ({"pitch": "0.1"}, "文字列の音高"),
                       ({"speaker_id": -1}, "負の話者 ID"), ({"speaker_id": True}, "bool の話者 ID"),
                       ({"volume": True}, "bool の音量")]:
        try:
            TalkVoice.parse(raw)
            check(f"{label}は ValueError", False)
        except ValueError:
            check(f"{label}は ValueError", True)


def test_from_config() -> None:
    cfg = {"talk_speaker_id": 2, "talk_speed": 1.2, "talk_pitch": 0.0, "talk_intonation": 1.0, "talk_volume": 1.0}
    check("config から作る", TalkVoice.from_config(cfg) == TalkVoice(2, 1.2, 0.0, 1.0, 1.0))
    check("不正な config は既定値", TalkVoice.from_config({**cfg, "talk_speed": "fast"}) == TalkVoice())
    check("キーが無ければ既定値", TalkVoice.from_config({}) == TalkVoice())


def test_query_overrides() -> None:
    q = TalkVoice(3, 1.5, 0.1, 0.5, 1.2).query_overrides()
    check("audio_query に上書きする値", q == {"speedScale": 1.5, "pitchScale": 0.1,
                                            "intonationScale": 0.5, "volumeScale": 1.2}, repr(q))


if __name__ == "__main__":
    test_parse()
    test_from_config()
    test_query_overrides()
    sys.exit(0 if all(results) else 1)
