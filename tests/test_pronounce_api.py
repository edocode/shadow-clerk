"""発音フィードバックのアーム状態・ワーカー・API ハンドラの検証

実行: uv run python tests/test_pronounce_api.py
モデル（torch）は不要。音素認識は偽物に差し替える。
"""
from __future__ import annotations
import io
import json
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SHADOW_CLERK_DATA_DIR",
                      os.path.join(tempfile.gettempdir(), "shadow-clerk-pronounce-api-test"))
os.makedirs(os.environ["SHADOW_CLERK_DATA_DIR"], exist_ok=True)

from shadow_clerk._daemon_pronounce import ArmError, PronounceDriver  # noqa: E402
from shadow_clerk.domain import Language, PronunciationTask  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _FakeRecogniser:
    """音素認識の偽物。pcm に渡した tuple をそのまま実測IPAとして返す"""

    def __init__(self) -> None:
        self.loaded = True
        self.loads = 0

    def load(self) -> None:
        self.loads += 1
        self.loaded = True

    def unload(self) -> None:
        self.loaded = False

    def actual_ipa(self, pcm) -> tuple[str, ...]:
        return tuple(pcm)


def _driver() -> PronounceDriver:
    """読み込み済みのドライバ。最初の POST が loading を返す経路は別のテストで見る"""
    rec = _FakeRecogniser()
    drv = PronounceDriver(recogniser_factory=lambda: rec)
    drv._recogniser = rec                            # type: ignore[assignment]
    # G2P を呼ばずに済むよう、語ごとの期待IPAを直接差し替える
    drv._expected_of = lambda word, lang: {          # type: ignore[assignment]
        "light": ("l", "aɪ", "t"), "right": ("ɹ", "aɪ", "t")}[word.lower()]
    # extra も設定も見ない（CI でも開発機でも同じ結果にする）
    drv._unavailable = lambda: None                  # type: ignore[assignment]
    return drv


def _task(text: str = "right light", focus=((("light"), "l"),)) -> PronunciationTask:
    return PronunciationTask.parse(
        {"text": text, "lang": "en", "focus": [{"word": w, "phoneme": p} for w, p in focus]})


def _settle(drv: PronounceDriver, timeout: float = 5.0) -> None:
    """ワーカーが処理し終えるまで待つ。pending が 0 になったら attempt は必ず見えている"""
    deadline = time.monotonic() + timeout
    while drv.snapshot()["pending"] > 0 and time.monotonic() < deadline:
        time.sleep(0.01)


def test_arm_and_clear() -> None:
    drv = _driver()
    check("最初は idle", drv.snapshot()["state"] == "idle", repr(drv.snapshot()))
    out = drv.arm(_task())
    check("アームできる", out["state"] == "armed" and out["id"], repr(out))
    check("正規化後の期待IPAを返す",
          out["expected"] == [{"word": "right", "ipa": ["ɹ", "aɪ", "t"]},
                              {"word": "light", "ipa": ["l", "aɪ", "t"]}], repr(out["expected"]))
    check("期限を返す", bool(out["expires_at"]))
    snap = drv.snapshot()
    check("snapshot も armed", snap["state"] == "armed" and snap["pending"] == 0)
    check("課題を返す", snap["task"]["text"] == "right light", repr(snap["task"]))
    drv.clear()
    check("解除できる", drv.snapshot()["state"] == "idle" and drv.snapshot()["task"] is None)


def test_first_post_reports_loading() -> None:
    # モデルは 1.2GB ある。最初の POST で取得を始め、その間 loading を返す（設計書 §9）
    started = threading.Event()
    release = threading.Event()

    class _SlowRecogniser(_FakeRecogniser):
        def __init__(self) -> None:
            super().__init__()
            self.loaded = False

        def load(self) -> None:
            started.set()
            release.wait(5.0)
            self.loaded = True

    drv = PronounceDriver(recogniser_factory=_SlowRecogniser)
    drv._expected_of = lambda word, lang: ("l", "aɪ", "t")   # type: ignore[assignment]
    drv._unavailable = lambda: None                          # type: ignore[assignment]
    out = drv.arm(_task("light", focus=()))
    started.wait(5.0)
    check("取得中は loading を返す", drv.snapshot()["state"] == "loading", repr(drv.snapshot()))
    check("それでも id と期待IPAは返る", bool(out["id"]) and bool(out["expected"]), repr(out))
    release.set()
    deadline = time.monotonic() + 5.0
    while drv.snapshot()["state"] == "loading" and time.monotonic() < deadline:
        time.sleep(0.01)
    check("読み込みが終われば armed", drv.snapshot()["state"] == "armed", repr(drv.snapshot()))


def test_unavailable_reports_reason() -> None:
    # extra が無い・設定が off のときは理由を添える（設計書 §10）
    drv = _driver()
    drv._unavailable = lambda: "not_installed"       # type: ignore[assignment]
    snap = drv.snapshot()
    check("使えないときは unavailable", snap["state"] == "unavailable", repr(snap))
    check("理由を返す", snap.get("reason") == "not_installed", repr(snap))
    try:
        drv.arm(_task())
        check("使えないときはアームを拒否する", False)
    except ArmError as e:
        check("使えないときはアームを拒否する", e.message == "not_installed", e.message)


def test_focus_validation() -> None:
    drv = _driver()
    try:
        drv.arm(_task(focus=(("light", "r"),)))
        check("期待IPAに無い音素を拒否する", False)
    except ArmError as e:
        check("期待IPAに無い音素を拒否する", True)
        check("拒否のときに期待IPAを返す",
              e.expected == [{"word": "light", "ipa": ["l", "aɪ", "t"]}], repr(e.expected))
    try:
        drv.arm(_task(focus=(("bright", "ɹ"),)))
        check("課題文に無い語を拒否する", False)
    except ArmError:
        check("課題文に無い語を拒否する", True)
    # Review Focus 3: focus が空なのは正当な入力。拒否しない
    check("focus が空でもアームできる", drv.arm(_task(focus=())).get("state") == "armed")


def test_attempts_accumulate() -> None:
    drv = _driver()
    drv.arm(_task())
    for i, take in enumerate((("ɹ", "aɪ", "t", "r", "aɪ", "t"),
                              ("ɹ", "aɪ", "t", "l", "aɪ", "t"))):
        drv.offer(take, f"2026-10-18 10:00:0{i}", "right light")
    _settle(drv)
    snap = drv.snapshot()
    check("アームは続く（done を持たない）", snap["state"] == "armed", repr(snap["state"]))
    check("attempts が積まれる", len(snap["attempts"]) == 2, repr(len(snap["attempts"])))
    check("新しい順", snap["attempts"][0]["segment_at"] == "2026-10-18 10:00:01",
          repr([a["segment_at"] for a in snap["attempts"]]))
    check("asr_text が同梱される", snap["attempts"][0]["asr_text"] == "right light")
    light = [w for w in snap["attempts"][0]["words"] if w["word"] == "light"][0]
    check("focus の op に印が付く", [op["focus"] for op in light["ops"]] == [True, False, False],
          repr(light["ops"]))
    check("判定・スコアを返さない",
          not ({"distance", "score", "ok"} & set(snap["attempts"][0])), repr(sorted(snap["attempts"][0])))
    for i in range(3):
        drv.offer(("l", "aɪ", "t"), f"2026-10-18 10:01:0{i}", "light")
    _settle(drv)
    check("attempts は最大3件", len(drv.snapshot()["attempts"]) == 3,
          repr(len(drv.snapshot()["attempts"])))


def test_pending_then_attempt_visible() -> None:
    # pending が 0 になった時点で attempt は必ず見えていること（設計書 §7.2・§7.4 の前提）
    drv = _driver()
    drv.arm(_task())
    drv.offer(("ɹ", "aɪ", "t", "l", "aɪ", "t"), "2026-10-18 10:02:00", "right light")
    _settle(drv)
    snap = drv.snapshot()
    check("pending が 0 で attempt が見える",
          snap["pending"] == 0 and len(snap["attempts"]) == 1, repr(snap))


def test_stale_arm_discarded() -> None:
    drv = _driver()
    drv.arm(_task())
    drv.offer(("ɹ", "aɪ", "t"), "2026-10-18 10:03:00", "right")
    drv.clear()
    drv.arm(_task())
    _settle(drv)
    check("解除前の解析結果は捨てる", drv.snapshot()["attempts"] == [],
          repr(drv.snapshot()["attempts"]))


def test_not_armed_is_ignored() -> None:
    drv = _driver()
    drv.offer(("l", "aɪ", "t"), "2026-10-18 10:04:00", "light")
    _settle(drv)
    check("アーム前の発話は無視する", drv.snapshot()["attempts"] == [])


def test_ttl() -> None:
    now = [1000.0]
    drv = PronounceDriver(recogniser_factory=_FakeRecogniser, clock=lambda: now[0])
    drv._expected_of = lambda word, lang: ("l", "aɪ", "t")   # type: ignore[assignment]
    drv._unavailable = lambda: None                          # type: ignore[assignment]
    drv.arm(_task("light", focus=()))
    check("期限内は armed", drv.snapshot()["state"] == "armed")
    now[0] += 301
    check("TTL を過ぎたら idle", drv.snapshot()["state"] == "idle", repr(drv.snapshot()))


def test_queue_full_is_dropped() -> None:
    # Review Focus 2: キューが詰まっても offer は例外を出さない（文字起こしを止めない）
    drv = _driver()
    drv.arm(_task())
    import queue as _q
    drv._queue = _q.Queue(maxsize=0)     # 何も入らないキューに差し替える

    class _TinyQueue:
        def put_nowait(self, item) -> None:
            raise _q.Full

    drv._queue = _TinyQueue()            # type: ignore[assignment]
    drv.offer(("l",), "2026-10-18 10:06:00", "light")
    check("満杯なら黙って捨てる", drv.snapshot()["pending"] == 0, repr(drv.snapshot()))


def test_same_segment_at_twice() -> None:
    # Review Focus 5: VAD が同じ秒に2セグメントを閉じることがある。
    # どちらも正当な試行なので daemon は消さない。スキルは最初に一致したものを使う
    drv = _driver()
    drv.arm(_task())
    for take in (("ɹ", "aɪ", "t"), ("l", "aɪ", "t")):
        drv.offer(take, "2026-10-18 10:07:00", "right light")
    _settle(drv)
    same = [a for a in drv.snapshot()["attempts"] if a["segment_at"] == "2026-10-18 10:07:00"]
    check("同じ segment_at の attempt を両方残す", len(same) == 2, repr(len(same)))


def test_idle_unload() -> None:
    # 設計書 §9: 一定時間使われなければモデルを解放する（import torch のメモリは残る）
    drv = _driver()
    drv._idle_unload_sec = lambda: 0.05                      # type: ignore[assignment]
    drv.arm(_task())
    drv.offer(("l", "aɪ", "t"), "2026-10-18 10:08:00", "light")
    _settle(drv)
    check("解析のあとは読み込み済み", drv._recogniser.loaded)
    deadline = time.monotonic() + 5.0
    while drv._recogniser.loaded and time.monotonic() < deadline:
        time.sleep(0.02)
    check("アイドルで解放する", not drv._recogniser.loaded)


def test_worker_error_is_contained() -> None:
    class _Boom(_FakeRecogniser):
        def actual_ipa(self, pcm):
            raise RuntimeError("boom")

    drv = PronounceDriver(recogniser_factory=_Boom)
    drv._expected_of = lambda word, lang: ("l", "aɪ", "t")   # type: ignore[assignment]
    drv._unavailable = lambda: None                          # type: ignore[assignment]
    drv.arm(_task("light", focus=()))
    drv.offer(("l",), "2026-10-18 10:05:00", "light")
    _settle(drv)
    snap = drv.snapshot()
    check("解析の例外を外に出さない", snap["attempts"] == [] and snap["pending"] == 0, repr(snap))
    check("アームは生きたまま", snap["state"] == "armed")


if __name__ == "__main__":
    test_arm_and_clear()
    test_first_post_reports_loading()
    test_unavailable_reports_reason()
    test_focus_validation()
    test_attempts_accumulate()
    test_pending_then_attempt_visible()
    test_stale_arm_discarded()
    test_not_armed_is_ignored()
    test_queue_full_is_dropped()
    test_same_segment_at_twice()
    test_idle_unload()
    test_ttl()
    test_worker_error_is_contained()
    sys.exit(0 if all(results) else 1)
