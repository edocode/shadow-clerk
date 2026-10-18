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
    # focus が空なのは正当な入力。拒否しない
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


def test_pending_covers_the_append() -> None:
    # pending は解析の開始から attempt が積まれ終わるまで 1 以上であること。
    # ここが崩れると、スキルが「解析は来ない」と判断して、正しく言えた文を言い直させる
    entered, release = threading.Event(), threading.Event()

    class _Blocking(_FakeRecogniser):
        def actual_ipa(self, pcm) -> tuple[str, ...]:
            entered.set()
            release.wait(5.0)
            return tuple(pcm)

    rec = _Blocking()
    drv = PronounceDriver(recogniser_factory=lambda: rec)
    drv._recogniser = rec                                    # type: ignore[assignment]
    drv._expected_of = lambda word, lang: {                  # type: ignore[assignment]
        "light": ("l", "aɪ", "t"), "right": ("ɹ", "aɪ", "t")}[word.lower()]
    drv._unavailable = lambda: None                          # type: ignore[assignment]
    drv.arm(_task())
    drv.offer(("ɹ", "aɪ", "t", "l", "aɪ", "t"), "2026-10-18 10:12:00", "right light")
    check("推論に入った", entered.wait(5.0))
    snap = drv.snapshot()
    check("解析中は pending が 1 以上で attempt はまだ無い",
          snap["pending"] >= 1 and not snap["attempts"], repr(snap))
    release.set()
    _settle(drv)
    snap = drv.snapshot()
    check("終われば pending 0 で attempt が読める",
          snap["pending"] == 0 and len(snap["attempts"]) == 1, repr(snap))


def test_pending_zero_never_precedes_the_attempt() -> None:
    # 競合が起きうるのは「attempts が空の状態からの1件目」だけなので、毎回 arm し直す。
    # pending が 0 に見えた最初の瞬間に attempt が読めていること
    drv = _driver()
    empty = 0
    observed = 0
    for i in range(50):
        drv.arm(_task())                 # attempts が空に戻る
        drv.offer(("ɹ", "aɪ", "t", "l", "aɪ", "t"), f"2026-10-18 10:13:{i:02d}", "right light")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            snap = drv.snapshot()        # offer が返った時点で pending は 1 以上
            if snap["pending"] == 0:
                observed += 1
                if not snap["attempts"]:
                    empty += 1
                break
    check("50 回とも pending==0 を観測した", observed == 50, f"observed={observed}")
    check("pending==0 を最初に見た瞬間に attempt が読める", empty == 0, f"{empty}/50 回で空だった")


def test_stale_arm_discarded() -> None:
    drv = _driver()
    drv.arm(_task())
    drv.offer(("ɹ", "aɪ", "t"), "2026-10-18 10:03:00", "right")
    drv.clear()
    drv.arm(_task())
    _settle(drv)
    check("解除前の解析結果は捨てる", drv.snapshot()["attempts"] == [],
          repr(drv.snapshot()["attempts"]))


def test_stale_arm_discarded_mid_inference() -> None:
    # 推論の最中に課題が差し替わったら、その結果は捨てる（設計書 §8.3）。
    # 偽の認識器を推論中に止めて、その間に clear + arm する
    entered, release = threading.Event(), threading.Event()

    class _Blocking(_FakeRecogniser):
        def actual_ipa(self, pcm) -> tuple[str, ...]:
            entered.set()
            release.wait(5.0)
            return tuple(pcm)

    rec = _Blocking()
    drv = PronounceDriver(recogniser_factory=lambda: rec)
    drv._recogniser = rec                                    # type: ignore[assignment]
    drv._expected_of = lambda word, lang: {                  # type: ignore[assignment]
        "light": ("l", "aɪ", "t"), "right": ("ɹ", "aɪ", "t")}[word.lower()]
    drv._unavailable = lambda: None                          # type: ignore[assignment]
    drv.arm(_task())
    drv.offer(("ɹ", "aɪ", "t", "l", "aɪ", "t"), "2026-10-18 10:09:00", "right light")
    check("推論に入った", entered.wait(5.0))
    drv.clear()
    drv.arm(_task())          # 差し替え。推論は古い課題に対して走っている
    release.set()
    _settle(drv)
    check("推論中に差し替えられた結果は捨てる", drv.snapshot()["attempts"] == [],
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
    # キューが詰まっても offer は例外を出さない（文字起こしを止めない）
    drv = _driver()
    drv.arm(_task())
    import queue as _q
    class _TinyQueue:
        def put_nowait(self, item) -> None:
            raise _q.Full

    drv._queue = _TinyQueue()            # type: ignore[assignment]
    drv.offer(("l",), "2026-10-18 10:06:00", "light")
    check("満杯なら黙って捨てる", drv.snapshot()["pending"] == 0, repr(drv.snapshot()))


def test_same_segment_at_twice() -> None:
    # VAD が同じ秒に2セグメントを閉じることがある。
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
    drv.arm(_task())
    drv.offer(("l", "aɪ", "t"), "2026-10-18 10:08:00", "light")
    _settle(drv)
    # 解放に追い抜かれないよう、差し替えは解析が終わってから行う
    drv._configured_idle_unload_sec = lambda: 0.5            # type: ignore[assignment]
    # ワーカーは既に長いタイムアウトでキュー待ちに入っている。もう1件流して待ち直させる
    drv.offer(("l", "aɪ", "t"), "2026-10-18 10:08:01", "light")
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


def test_worker_survives_config_error() -> None:
    # 設定の読み取りで例外が出てもワーカーは死なない。
    # 死ぬと pending が永久に減らず、スキルは解析を待ち続ける
    drv = _driver()
    calls = {"n": 0}

    def _boom() -> float:
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("could not convert string to float: 'abc'")
        return 0.05

    drv.arm(_task())
    drv.offer(("ɹ", "aɪ", "t", "l", "aɪ", "t"), "2026-10-18 10:14:00", "right light")
    _settle(drv)                          # 1件目を処理させ、ワーカーを待機に戻す
    check("1件目は入る", len(drv.snapshot()["attempts"]) == 1)
    drv._idle_unload_sec = _boom          # type: ignore[assignment]
    drv.offer(("ɹ", "aɪ", "t", "l", "aɪ", "t"), "2026-10-18 10:14:01", "right light")
    _settle(drv)                          # 2件目を処理 → 次の周回で _boom が例外を出す
    deadline = time.monotonic() + 10.0
    while calls["n"] < 2 and time.monotonic() < deadline:
        time.sleep(0.05)                  # 例外 → 1秒の小休止 → 再度 _idle_unload_sec
    check("例外のあともワーカーが設定を読み直しに来る", calls["n"] >= 2, repr(calls))
    drv.offer(("ɹ", "aɪ", "t", "l", "aɪ", "t"), "2026-10-18 10:14:02", "right light")
    _settle(drv, timeout=10.0)
    check("例外のあとも解析を続ける", len(drv.snapshot()["attempts"]) == 3,
          repr(len(drv.snapshot()["attempts"])))


def test_load_failure_is_visible() -> None:
    # ロードに失敗したら unavailable と reason を返す（設計書 §10）。黙って armed のままにしない
    class _Broken(_FakeRecogniser):
        def __init__(self) -> None:
            super().__init__()
            self.loaded = False

        def load(self) -> None:
            raise RuntimeError("network is unreachable")

    drv = PronounceDriver(recogniser_factory=_Broken)
    drv._expected_of = lambda word, lang: ("l", "aɪ", "t")   # type: ignore[assignment]
    drv._unavailable = lambda: None                          # type: ignore[assignment]
    drv.arm(_task("light", focus=()))
    deadline = time.monotonic() + 5.0
    while drv.snapshot()["state"] == "loading" and time.monotonic() < deadline:
        time.sleep(0.01)
    snap = drv.snapshot()
    check("ロード失敗は unavailable になる", snap["state"] == "unavailable", repr(snap))
    check("理由を返す", snap.get("reason") == "load_failed", repr(snap))


from shadow_clerk._daemon_dashboard_ops_talk import _DashboardHandlerTalkOps as Ops  # noqa: E402


class _FakeDriver:
    def __init__(self, armed: bool = False) -> None:
        self.calls: list[tuple] = []
        self.armed = armed
        self.fail: ArmError | None = None

    def arm(self, task) -> dict:
        if self.fail is not None:
            raise self.fail
        self.calls.append(("arm", task.text, task.language.value,
                           tuple((f.word, f.phoneme) for f in task.focus)))
        return {"status": "ok", "id": "abc", "state": "armed", "expires_at": "2026-10-18 10:05:00",
                "expected": [{"word": "light", "ipa": ["l", "aɪ", "t"]}]}

    def clear(self) -> None:
        self.calls.append(("clear",))

    def snapshot(self) -> dict:
        return {"state": "armed" if self.armed else "idle", "pending": 0,
                "expires_at": "", "task": None, "attempts": []}


class _PronounceHandler(Ops):
    def __init__(self, body: object = None, client: str = "127.0.0.1", talk_active: bool = True,
                 headers: dict | None = None) -> None:
        raw = json.dumps(body if body is not None else {}).encode("utf-8")
        self.client_address = (client, 12345)
        self.headers = {"Content-Length": str(len(raw)), **(headers or {})}
        self.rfile = io.BytesIO(raw)
        self.sent: dict = {}
        self.pronounce = _FakeDriver()
        self.recorder = type("_Rec", (), {
            "pronounce": self.pronounce,
            "talk": type("_T", (), {"active": talk_active})()})()

    def _send_json(self, data: dict) -> None:
        self.sent = data


def test_post_pronounce() -> None:
    h = _PronounceHandler({"text": "Turn right at the light.", "lang": "en",
                           "focus": [{"word": "light", "phoneme": "l"}]})
    h._set_pronounce()
    check("アームを渡す",
          h.pronounce.calls == [("arm", "Turn right at the light.", "en", (("light", "l"),))],
          repr(h.pronounce.calls))
    check("id と期待IPAを返す",
          h.sent.get("status") == "ok" and h.sent.get("id") == "abc" and h.sent.get("expected"),
          repr(h.sent))
    h = _PronounceHandler({"clear": True})
    h._set_pronounce()
    check("clear で解除する", h.pronounce.calls == [("clear",)] and h.sent.get("status") == "ok")


def test_post_requires_talk_mode() -> None:
    h = _PronounceHandler({"text": "Say right again.", "lang": "en", "focus": []}, talk_active=False)
    h._set_pronounce()
    check("talk mode が止まっていたら拒否する",
          h.sent.get("status") == "error" and h.pronounce.calls == [], repr(h.sent))
    check("理由を返す", "talk mode" in h.sent.get("message", ""), repr(h.sent))


def test_post_rejects_with_200() -> None:
    h = _PronounceHandler({"text": "Say right again.", "lang": "en", "focus": []})
    h.pronounce.fail = ArmError("focus phoneme 'r' is not in the expected IPA of 'right'",
                                [{"word": "right", "ipa": ["ɹ", "aɪ", "t"]}])
    h._set_pronounce()
    check("拒否も status: error で返す", h.sent.get("status") == "error", repr(h.sent))
    check("拒否に期待IPAを添える",
          h.sent.get("expected") == [{"word": "right", "ipa": ["ɹ", "aɪ", "t"]}], repr(h.sent))
    h = _PronounceHandler({"text": "Say right 3 times.", "lang": "en", "focus": []})
    h.pronounce.fail = ArmError("text must not contain digits; spell numbers out")
    h._set_pronounce()
    check("数字を含む課題文を拒否する", h.sent.get("status") == "error")
    # 長すぎる課題文は parse の段階で落ちる
    h = _PronounceHandler({"text": "a " * 400, "lang": "en", "focus": []})
    h._set_pronounce()
    check("長すぎる課題文を拒否する",
          h.sent.get("status") == "error" and h.pronounce.calls == [], repr(h.sent)[:120])
    h = _PronounceHandler({"text": "Hi.", "lang": "en", "focus": [{"word": "hi"}]})
    h._set_pronounce()
    check("不正な focus を拒否する", h.sent.get("status") == "error")


def test_post_rejects_cross_origin() -> None:
    # 新しい書き込みエンドポイントなので、既存の書き込み API と同じ CSRF 防御が効くこと
    # （tests/test_console_ops.py の C2 と同じ形）
    body = {"text": "Say right again.", "lang": "en", "focus": []}
    h = _PronounceHandler(body, headers={"Host": "localhost:8765", "Origin": "http://evil.example"})
    h._set_pronounce()
    check("クロスオリジンの POST を拒否する",
          h.sent.get("status") == "error" and h.pronounce.calls == [], repr(h.sent))
    h = _PronounceHandler(body, headers={"Host": "localhost:8765", "Origin": "http://localhost:8765"})
    h._set_pronounce()
    check("同一オリジンの POST は通す", h.sent.get("status") == "ok", repr(h.sent))
    h = _PronounceHandler({"clear": True}, client="10.0.0.5")
    h._set_pronounce()
    check("localhost 以外の POST を拒否する",
          h.sent.get("status") == "error" and h.pronounce.calls == [], repr(h.sent))


def test_get_pronounce() -> None:
    h = _PronounceHandler()
    h._serve_pronounce()
    check("状態を返す", h.sent.get("state") == "idle" and h.sent.get("pending") == 0, repr(h.sent))
    check("判定・スコアを返さない",
          not ({"distance", "score", "ok", "passed"} & set(h.sent)), repr(sorted(h.sent)))
    h = _PronounceHandler(client="10.0.0.5")
    h._serve_pronounce()
    check("localhost 以外は拒否する", h.sent.get("status") == "error", repr(h.sent))


def test_routes_are_wired() -> None:
    from shadow_clerk import _daemon_dashboard_base as base
    src = open(base.__file__, encoding="utf-8").read()
    check("GET のルートがある", '"/api/pronounce"' in src and "_serve_pronounce()" in src)
    check("POST のルートがある", "_set_pronounce()" in src)


if __name__ == "__main__":
    test_arm_and_clear()
    test_first_post_reports_loading()
    test_unavailable_reports_reason()
    test_focus_validation()
    test_attempts_accumulate()
    test_pending_covers_the_append()
    test_pending_zero_never_precedes_the_attempt()
    test_stale_arm_discarded()
    test_stale_arm_discarded_mid_inference()
    test_not_armed_is_ignored()
    test_queue_full_is_dropped()
    test_same_segment_at_twice()
    test_idle_unload()
    test_ttl()
    test_worker_error_is_contained()
    test_worker_survives_config_error()
    test_load_failure_is_visible()
    test_post_pronounce()
    test_post_requires_talk_mode()
    test_post_rejects_with_200()
    test_post_rejects_cross_origin()
    test_get_pronounce()
    test_routes_are_wired()
    sys.exit(0 if all(results) else 1)
