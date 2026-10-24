"""発音フィードバックの自由発話モード（会話の練習）の検証

実行: uv run python tests/test_pronounce_free.py
モデル（torch）は不要。音素認識は偽物に差し替える（test_pronounce_api.py の部品を使う）。
"""
from __future__ import annotations
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_pronounce_api import _FakeRecogniser, _settle, check, results  # noqa: E402
from shadow_clerk._daemon_pronounce import PronounceDriver  # noqa: E402
from shadow_clerk._daemon_pronounce_ipa import G2PError  # noqa: E402
from shadow_clerk.domain import PronunciationTask  # noqa: E402

_IPA = {"thick": ("θ", "@", "k"), "soup": ("s", "u", "p"), "is": ("@", "z")}


def _expected_of(word: str, lang: object) -> tuple[str, ...]:
    if word.lower() not in _IPA:
        raise G2PError(f"no ipa for {word}")
    return _IPA[word.lower()]


def _driver(now: list[float]) -> PronounceDriver:
    rec = _FakeRecogniser()
    drv = PronounceDriver(recogniser_factory=lambda: rec, clock=lambda: now[0])
    drv._recogniser = rec                            # type: ignore[assignment]
    drv._expected_of = _expected_of                  # type: ignore[assignment]
    drv._unavailable = lambda: None                  # type: ignore[assignment]
    return drv


def _free() -> PronunciationTask:
    return PronunciationTask.parse({"free": True, "lang": "en"})


def test_parse() -> None:
    task = _free()
    check("free は課題文なしで受け付ける", task.free and task.text == "" and task.focus == ())
    for body, label in (({"free": True, "lang": "en", "text": "soup"}, "text"),
                        ({"free": True, "lang": "en", "focus": [{"word": "a", "phoneme": "a"}]}, "focus"),
                        ({"free": "yes", "lang": "en"}, "bool 以外"),
                        ({"free": True}, "lang なし")):
        try:
            PronunciationTask.parse(body)
            check(f"free に {label} は拒否", False)
        except ValueError:
            check(f"free に {label} は拒否", True)
    check("to_json に free が載る", task.to_json()["free"] is True)


def test_analyses_against_asr_text() -> None:
    now = [1000.0]
    drv = _driver(now)
    out = drv.arm(_free())
    check("free でアームできる", out["state"] == "armed" and out["expected"] == [], repr(out))
    drv.offer(("s", "u", "p", "@", "z", "s", "@", "k"), "2026-10-24 15:00:00", "Soup is thick.")
    _settle(drv)
    attempts = drv.snapshot()["attempts"]
    check("文字起こしを期待文にして解析する", len(attempts) == 1, repr(attempts))
    thick = attempts[0]["words"][2]
    check("語ごとの差分が出る (θ→s)",
          thick["word"] == "thick" and thick["ops"][0]["kind"] == "sub"
          and thick["ops"][0]["actual"] == "s", repr(thick))
    check("focus は付かない", not any(op["focus"] for w in attempts[0]["words"] for op in w["ops"]))


def test_trimmed_reaches_attempt() -> None:
    now = [1000.0]
    drv = _driver(now)
    drv.arm(_free())
    drv.offer(("s", "u", "p"), "2026-10-24 15:00:00", "soup", trimmed=True)
    drv.offer(("s", "u", "p"), "2026-10-24 15:00:05", "soup")
    _settle(drv)
    got = [a["trimmed"] for a in drv.snapshot()["attempts"]]
    check("切り落としたセグメントは attempt に trimmed が付く", got == [False, True], repr(got))


def test_skips_unreadable() -> None:
    now = [1000.0]
    drv = _driver(now)
    drv.arm(_free())
    drv.offer(("s",), "2026-10-24 15:00:01", "I have 3 soups.")
    drv.offer(("s",), "2026-10-24 15:00:02", "Unknownword soup.")
    drv.offer(("s",), "2026-10-24 15:00:03", "...")
    _settle(drv)
    check("数字・G2P 不可・語なしは解析しない", drv.snapshot()["attempts"] == [],
          repr(drv.snapshot()["attempts"]))
    check("失敗扱いにもしない", drv.snapshot()["state"] == "armed")


def test_ttl_extends_on_speech() -> None:
    now = [1000.0]
    drv = _driver(now)
    drv.arm(_free())
    now[0] += 200
    drv.offer(("s", "u", "p"), "2026-10-24 15:03:20", "soup")
    _settle(drv)
    now[0] += 200
    check("発話があれば期限が延びる", drv.snapshot()["state"] == "armed", repr(drv.snapshot()))
    now[0] += 101
    check("最後の発話から TTL で切れる", drv.snapshot()["state"] == "idle")


if __name__ == "__main__":
    test_parse()
    test_analyses_against_asr_text()
    test_trimmed_reaches_attempt()
    test_skips_unreadable()
    test_ttl_extends_on_speech()
    print(f"\n=== {sum(results)}/{len(results)} PASS ===")
    sys.exit(0 if all(results) else 1)
