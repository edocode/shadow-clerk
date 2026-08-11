"""level SSE イベントの検証

実行: uv run python tests/test_level_event.py
実デバイス不要。FileWatcher に偽 recorder を渡して配信内容を検査する。
"""
from __future__ import annotations
import json
import threading
from unittest.mock import patch

import numpy as np

from shadow_clerk._daemon_audio_backends import PipeWireBackend
from shadow_clerk._daemon_audio_level import CaptureLevel
from shadow_clerk._daemon_log_buffer import FileWatcher, LogBuffer
from shadow_clerk._daemon_recorder_monitor import _RecorderMonitorBackendMixin

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
        self.backend_source: dict = {}
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
check("3. monitor は開いていない (backend_source も無い) ので null",
      payload.get("monitor") is None, f"{payload.get('monitor')}")

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

# requested が未指定 (None) の場合 — CLI/config どちらでも指定していない通常のケース
rec3 = FakeRecorder()
rec3.levels["mic"].add(np.full(480, 500, dtype=np.int16))
rec3.open_streams["mic"] = FakeStream("alsa_input.auto", requested=None)
fw3 = FileWatcher(rec3, LogBuffer())
sent3: list[tuple[str, str]] = []
fw3._broadcast = lambda event, data: sent3.append((event, data))  # type: ignore[method-assign]
fw3._poll_levels()
mic3 = json.loads(sent3[0][1])["mic"]
check("9. requested 未指定なら requested=None", mic3.get("requested") is None,
      f"{mic3.get('requested')}")
check("10. requested 未指定なら fallback=false", mic3.get("fallback") is False,
      f"{mic3.get('fallback')}")

# バックエンド経路 (pw-record/parec) 中のモニターは open_streams に載らないが、
# backend_source にソース (PipeWire は object.serial の文字列) が入っている。
# ここで null にすると、pw-record が正常に録れているのに毎秒 1 秒分の実測値を
# 捨ててメーターが常時空表示になる (Finding 1)
rec4 = FakeRecorder()
rec4.levels["monitor"].add(np.full(480, 2000, dtype=np.int16))
rec4.backend_source["monitor"] = "80"
fw4 = FileWatcher(rec4, LogBuffer())
sent4: list[tuple[str, str]] = []
fw4._broadcast = lambda event, data: sent4.append((event, data))  # type: ignore[method-assign]
fw4._poll_levels()
monitor4 = json.loads(sent4[0][1]).get("monitor")
check("11. バックエンド経路でも monitor が null にならない",
      isinstance(monitor4, dict), f"{monitor4}")
mon4 = monitor4 or {}
check("12. バックエンドのレベル値が入っている",
      all(k in mon4 for k in ("rms", "peak", "crest")), f"{list(mon4)}")
check("13. device がバックエンドのソース", mon4.get("device") == "80", f"{mon4.get('device')}")
check("14. requested は None (PipeWire は名前ではなく object.serial しか持たない)",
      mon4.get("requested") is None, f"{mon4.get('requested')}")
check("15. fallback は false (判定不能なので偽の答えは出さない)",
      mon4.get("fallback") is False, f"{mon4.get('fallback')}")

# open_streams にも backend_source にも無ければ、どちらの経路も未確立なので null
rec5 = FakeRecorder()
rec5.levels["monitor"].add(np.full(480, 2000, dtype=np.int16))
fw5 = FileWatcher(rec5, LogBuffer())
sent5: list[tuple[str, str]] = []
fw5._broadcast = lambda event, data: sent5.append((event, data))  # type: ignore[method-assign]
fw5._poll_levels()
monitor5 = json.loads(sent5[0][1]).get("monitor")
check("16. ストリームもバックエンドソースも無ければ null", monitor5 is None, f"{monitor5}")

# _poll_levels() を直接呼ぶテストだけでは、run() からの呼び出しを消しても
# 8/8 のまま通ってしまう (Finding 3)。配線自体を _poll_iteration() 経由で検証する。
# _poll_levels() は以前 _poll() の最後の文だったが、_poll() 中の無関係な例外が
# レベル配信そのものを止めてしまう問題 (Finding B) を切るため、run() が両者を
# 別々に guard する _poll_iteration() に分離した
rec6 = FakeRecorder()
rec6.levels["mic"].add(np.full(480, 3000, dtype=np.int16))
rec6.open_streams["mic"] = FakeStream("alsa_input.wired", requested=None)
fw6 = FileWatcher(rec6, LogBuffer())
sent6: list[tuple[str, str]] = []
fw6._broadcast = lambda event, data: sent6.append((event, data))  # type: ignore[method-assign]
fw6._poll_iteration()
check("17. _poll_iteration() 経由でも level イベントが配信される",
      any(e == "level" for e, _ in sent6), f"{[e for e, _ in sent6]}")

# _poll() が無関係な例外を投げても、_poll_levels() は独立して動く (Finding B)
rec6b = FakeRecorder()
rec6b.levels["mic"].add(np.full(480, 3000, dtype=np.int16))
rec6b.open_streams["mic"] = FakeStream("alsa_input.wired", requested=None)
fw6b = FileWatcher(rec6b, LogBuffer())
sent6b: list[tuple[str, str]] = []
fw6b._broadcast = lambda event, data: sent6b.append((event, data))  # type: ignore[method-assign]
fw6b._poll = lambda: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]
fw6b._poll_iteration()
check("17b. _poll() が例外を投げても level イベントは配信される",
      any(e == "level" for e, _ in sent6b), f"{[e for e, _ in sent6b]}")

# Step 0a: backend_source に書き込む表示名が PipeWire の object.serial
# （意味のない数字文字列。例 "80"）そのままにならないこと。pw-record に渡す
# 値 (serial) 自体は変えてはいけないので、そちらは維持されているかも確認する


class _MonitorHost(_RecorderMonitorBackendMixin):
    def _requested_device(self, label: str) -> str | None:
        return None


host = _MonitorHost()

# 自動検出経路 (requested なし): detect_monitor_source は serial の生数字を
# 返すが、表示名には get_default_sink_name() の結果を使う
with patch("shadow_clerk._daemon_recorder_monitor.get_default_sink_name",
           return_value="alsa_output.pci-0000_c4_00.6.HiFi__hw_Interface__sink"), \
     patch.object(PipeWireBackend, "detect_monitor_source", return_value="80"):
    auto_target = host._monitor_target(PipeWireBackend(), None)
check("18. 自動検出経路: 表示名が serial 単体の数字文字列にならない",
      auto_target is not None and not auto_target[1].isdigit(), f"{auto_target}")
check("19. 自動検出経路: pw-record に渡す値は serial のまま",
      auto_target is not None and auto_target[0] == "80", f"{auto_target}")

# 指定デバイス経路: sink_serial で解決できれば表示名は Sink 名 (".monitor" 抜き)
with patch("shadow_clerk._daemon_recorder_monitor.sink_serial", return_value="64"):
    req_target = host._monitor_target(
        PipeWireBackend(), "alsa_output.usb-Shokz.monitor")
check("20. 指定デバイス経路: 表示名が serial 単体の数字文字列にならない",
      req_target is not None and not req_target[1].isdigit(), f"{req_target}")
check("21. 指定デバイス経路: pw-record に渡す値は serial のまま",
      req_target is not None and req_target[0] == "64", f"{req_target}")

# Step A: device=None でマイクを開くと PortAudio は "default" のような
# エイリアスしか返さない。ツールチップにそのまま出すと、OS のデフォルト入力が
# 死んだデバイスにすり替わっていても気づけない (今回の障害そのもの)。
# _poll_levels は FileWatcher._resolve_device_name でこれを OS 側の実名に
# 解決する

# 22. エイリアス名は OS 報告の実名に解決される
rec7 = FakeRecorder()
rec7.levels["mic"].add(np.full(480, 1500, dtype=np.int16))
rec7.open_streams["mic"] = FakeStream("default", requested=None)
fw7 = FileWatcher(rec7, LogBuffer())
sent7: list[tuple[str, str]] = []
fw7._broadcast = lambda event, data: sent7.append((event, data))  # type: ignore[method-assign]
with patch("shadow_clerk._daemon_log_buffer.get_default_source_name",
           return_value="Shokz Loop110 モノ") as mock_resolve7:
    fw7._poll_levels()
mic7 = json.loads(sent7[0][1])["mic"]
check("22. エイリアス device 名が OS 報告の実名に解決される",
      mic7.get("device") == "Shokz Loop110 モノ", f"{mic7.get('device')}")

# 23. 実デバイス名はそのまま素通しし、解決を試みない (無駄な subprocess を呼ばない)
rec8 = FakeRecorder()
rec8.levels["mic"].add(np.full(480, 1500, dtype=np.int16))
rec8.open_streams["mic"] = FakeStream("alsa_input.real", requested=None)
fw8 = FileWatcher(rec8, LogBuffer())
sent8: list[tuple[str, str]] = []
fw8._broadcast = lambda event, data: sent8.append((event, data))  # type: ignore[method-assign]
with patch("shadow_clerk._daemon_log_buffer.get_default_source_name") as mock_resolve8:
    fw8._poll_levels()
mic8 = json.loads(sent8[0][1])["mic"]
check("23. 実デバイス名は素通し（解決は呼ばれない）",
      mic8.get("device") == "alsa_input.real" and mock_resolve8.call_count == 0,
      f"device={mic8.get('device')} calls={mock_resolve8.call_count}")

# 24. 解決に失敗した (None) 場合はエイリアス名のままフォールバックする
rec9 = FakeRecorder()
rec9.levels["mic"].add(np.full(480, 1500, dtype=np.int16))
rec9.open_streams["mic"] = FakeStream("default", requested=None)
fw9 = FileWatcher(rec9, LogBuffer())
sent9: list[tuple[str, str]] = []
fw9._broadcast = lambda event, data: sent9.append((event, data))  # type: ignore[method-assign]
with patch("shadow_clerk._daemon_log_buffer.get_default_source_name", return_value=None):
    fw9._poll_levels()
mic9 = json.loads(sent9[0][1])["mic"]
check("24. 解決失敗時はエイリアス名 'default' にフォールバックする",
      mic9.get("device") == "default", f"{mic9.get('device')}")

# 25. 解決は毎回行わない (TTL キャッシュ) — 短時間の連続呼び出しでは1回だけ呼ぶ
rec10 = FakeRecorder()
rec10.levels["mic"].add(np.full(480, 1500, dtype=np.int16))
rec10.open_streams["mic"] = FakeStream("default", requested=None)
fw10 = FileWatcher(rec10, LogBuffer())
fw10._broadcast = lambda event, data: None  # type: ignore[method-assign]
with patch("shadow_clerk._daemon_log_buffer.get_default_source_name",
           return_value="Shokz Loop110 モノ") as mock_resolve10:
    for _ in range(5):
        rec10.levels["mic"].add(np.full(480, 1500, dtype=np.int16))
        fw10._poll_levels()
check("25. TTL 内の連続呼び出しでは解決を1回しか呼ばない",
      mock_resolve10.call_count == 1, f"calls={mock_resolve10.call_count}")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
