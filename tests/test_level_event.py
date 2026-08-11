"""level SSE イベントの検証

実行: uv run python tests/test_level_event.py
実デバイス不要。FileWatcher に偽 recorder を渡して配信内容を検査する。
"""
from __future__ import annotations
import json
import threading

import numpy as np

from shadow_clerk._daemon_audio_level import CaptureLevel
from shadow_clerk._daemon_log_buffer import FileWatcher, LogBuffer

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class FakeStream:
    def __init__(self, name: str, requested: str | None) -> None:
        self.device = type("D", (), {"name": name})()
        self.requested = requested


class FakeRecorder:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.levels = {"mic": CaptureLevel(), "monitor": CaptureLevel()}
        self.open_streams: dict = {}
        self.output_path = "/dev/null"
        self._command_mode = False


rec = FakeRecorder()
rec.levels["mic"].add(np.full(480, 4000, dtype=np.int16))
rec.open_streams["mic"] = FakeStream("alsa_input.real", requested="alsa_input.wanted")

fw = FileWatcher(rec, LogBuffer())
sent: list[tuple[str, str]] = []
fw._broadcast = lambda event, data: sent.append((event, data))  # type: ignore[method-assign]

fw._poll_levels()
levels = [json.loads(d) for e, d in sent if e == "level"]
check("1. level イベントが1件送られる", len(levels) == 1, f"{len(levels)}件")

payload = levels[0] if levels else {}
check("2. mic が値を持つ", isinstance(payload.get("mic"), dict), f"{payload.get('mic')}")
check("3. monitor は開いていないので null", payload.get("monitor") is None,
      f"{payload.get('monitor')}")

mic = payload.get("mic") or {}
check("4. rms/peak/crest がある", all(k in mic for k in ("rms", "peak", "crest")), f"{list(mic)}")
check("5. device が実デバイス名", mic.get("device") == "alsa_input.real", f"{mic.get('device')}")
check("6. requested が設定値", mic.get("requested") == "alsa_input.wanted")
check("7. 別デバイスなので fallback=true", mic.get("fallback") is True, f"{mic.get('fallback')}")

# 指定と実デバイスが一致していれば fallback=false
rec2 = FakeRecorder()
rec2.levels["mic"].add(np.full(480, 1000, dtype=np.int16))
rec2.open_streams["mic"] = FakeStream("alsa_input.same", requested="alsa_input.same")
fw2 = FileWatcher(rec2, LogBuffer())
sent2: list[tuple[str, str]] = []
fw2._broadcast = lambda event, data: sent2.append((event, data))  # type: ignore[method-assign]
fw2._poll_levels()
mic2 = json.loads(sent2[0][1])["mic"]
check("8. 一致していれば fallback=false", mic2.get("fallback") is False, f"{mic2.get('fallback')}")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
