# 音声デバイス選択（第1段階）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ダッシュボードの設定パネルからマイクとスピーカー（モニター）のデバイスを名前で指定でき、指定デバイスが消えている間も自動デバイスで録音を続け、戻ったら自動復帰する。

**Architecture:** `config.yaml` に `mic_device` / `monitor_device` をデバイス名で保存する。既存の監視スレッド `_audio_capture_thread` の 2 秒ティックで「設定値が変わったか」を、10 秒ティックで「フォールバック中の指定デバイスが OS 側に現れたか」を独立に判定する。この 2 分離により、指定デバイスが無い間は静止して再接続ループに陥らない。張り替えは、目的のデバイスが PortAudio のキャッシュ上にある場合は該当ストリームのみ、無い場合のみ全ストリームを閉じて再列挙する。

**Tech Stack:** Python 3.11+ / sounddevice (PortAudio) / PipeWire (`wpctl`, `pw-record`) / PulseAudio (`pactl`, `parec`) / 標準ライブラリの `http.server` ダッシュボード

**設計文書:** `docs/superpowers/specs/2026-08-10-audio-device-selection-design.md`

## Global Constraints

- Python は必ず `uv run python` で実行する（`python3` / `python` を直接使わない）
- 全ファイル先頭に `from __future__ import annotations`。関数シグネチャの引数・戻り値に型注釈は必須
- 1 ファイル最大 700 行。超えるなら既存の分割パターン（`_daemon_dashboard_js_panels.py` など）に倣って分割する
- **音声デバイスの同一性は必ず名前（`AudioDevice.name`）で判定する。番号は起動ごとに変わり稼働中にも移動する**
- PortAudio のデバイス一覧は `Pa_Initialize` 時点のキャッシュ。`refresh_device_list()`（`sd._terminate()` + `sd._initialize()`）は開いている全ストリームを破棄するため、全ストリームを閉じた状態でのみ呼ぶ
- ユーザー向け文字列は全て `i18n.py` の `t()` 経由。`_i18n_ja.py` と `_i18n_en.py` の両方に追加する
- ログは logger 経由（`print` を使わない）。ソース内の日本語コメントは可
- **テストフレームワークは無い。** 各タスクの検証は単体で走るスクリプトを `$SCRATCH`（スクラッチディレクトリ）に置いて `uv run python` で実行する。スクリプト全文は各タスクに記載してある
- 構文チェック: `uv run python -m py_compile src/shadow_clerk/<file>.py`
- 重複コード検査: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`（10.00/10 を維持）
- コミットメッセージは英語

---

## ファイル構成

| ファイル | 責務 | 変更 |
|---|---|---|
| `src/shadow_clerk/_daemon_constants.py` | 設定既定値 | `mic_device` / `monitor_device` を追加 |
| `src/shadow_clerk/_daemon_audio.py` | デバイス列挙・バックエンド | `device_exists()` を追加、バックエンドに名前指定を通す |
| `src/shadow_clerk/_daemon_recorder_capture.py` | キャプチャと監視ループ | 解決の優先順位、張り替えトリガ 2 系統、張り替えの粒度、一覧スナップショット |
| `src/shadow_clerk/_daemon_dashboard_ops_config.py` | 設定系 HTTP ハンドラ | `/api/audio-devices` のハンドラ |
| `src/shadow_clerk/_daemon_dashboard_base.py` | ルーティング | `/api/audio-devices` を追加 |
| `src/shadow_clerk/_daemon_dashboard_html.py` | ダッシュボード HTML | 設定パネルのセレクト 2 つ |
| `src/shadow_clerk/_daemon_dashboard_js_panels.py` | 設定パネルの JS | セレクトの読み書き |
| `src/shadow_clerk/_i18n_ja.py` / `_i18n_en.py` | 文言 | 新規キー |
| `README.md` / `README.ja.md` / `SPEC.md` | ドキュメント | 設定キーと API の追記 |

---

### Task 1: 設定キーとデバイス名による解決

**Files:**
- Modify: `src/shadow_clerk/_daemon_constants.py`（`DEFAULT_CONFIG`）
- Modify: `src/shadow_clerk/_daemon_audio.py`（`device_exists` を追加）
- Modify: `src/shadow_clerk/_daemon_recorder_capture.py:294-312`（`_resolve` を書き換え）
- Test: `$SCRATCH/test_task1.py`

**Interfaces:**
- Consumes: 既存の `find_device_by_name(name: str, capture: bool) -> AudioDevice | None`、`resolve_mic_device(index: int | None) -> AudioDevice | None`、`resolve_monitor_device(index: int | None) -> AudioDevice | None`
- Produces:
  - `device_exists(name: str) -> bool | None`（`_daemon_audio.py`）— OS 側の一覧に名前が存在するか。取得できなければ `None`
  - `_RecorderCaptureMixin._requested_device(label: str) -> str | None` — config で指定されたデバイス名。CLI 番号指定時は `None`
  - `_RecorderCaptureMixin._resolve(label: str, index: int | None) -> AudioDevice | None` — 優先順位 CLI 番号 > config 名 > 自動

- [ ] **Step 1: 検証スクリプトを書く（失敗するはず）**

`$SCRATCH/test_task1.py`:

```python
"""Task 1: 設定キーと名前解決の検証"""
from __future__ import annotations
import argparse, queue, threading

from shadow_clerk._daemon_constants import DEFAULT_CONFIG
from shadow_clerk import _daemon_recorder_capture as cap
from shadow_clerk import _daemon_audio as audio
from shadow_clerk.domain import AudioDevice

results: list[bool] = []

def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)

class Host(cap._RecorderCaptureMixin):
    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        self.args = argparse.Namespace(mic=None, monitor=None)
        self.stop_event = threading.Event()
        self.mic_queue, self.monitor_queue = queue.Queue(), queue.Queue()
        self.backend_name, self.backend = "pipewire", None
        self.use_mic = self.use_monitor = False
        self._pinned_names = {}
        self._monitor_backend = None

check("1. DEFAULT_CONFIG に mic_device がある", "mic_device" in DEFAULT_CONFIG)
check("2. DEFAULT_CONFIG に monitor_device がある", "monitor_device" in DEFAULT_CONFIG)
check("3. 既定値は None",
      DEFAULT_CONFIG.get("mic_device") is None
      and DEFAULT_CONFIG.get("monitor_device") is None)

host = Host()
cap.load_config = lambda: {"mic_device": "  ", "monitor_device": None}
check("4. 空白だけの設定は未指定扱い", host._requested_device("mic") is None)

cap.load_config = lambda: {"mic_device": "TargetMic"}
check("5. config の名前を返す", host._requested_device("mic") == "TargetMic")

host.args.mic = 3
check("6. CLI 番号指定時は config を無視", host._requested_device("mic") is None)

# 指定名が存在する → それを開く
host2 = Host()
cap.load_config = lambda: {"mic_device": "TargetMic"}
cap.find_device_by_name = lambda name, capture: (
    AudioDevice(index=9, name="TargetMic") if name == "TargetMic" else None)
cap.resolve_mic_device = lambda i: AudioDevice(index=0, name="default")
got = host2._resolve("mic", None)
check("7. 指定名が存在すればそれを解決", got is not None and got.name == "TargetMic", f"{got}")

# 指定名が無い → 自動にフォールバック（設定値は書き換えない）
cap.find_device_by_name = lambda name, capture: None
got2 = host2._resolve("mic", None)
check("8. 指定名が無ければ自動にフォールバック",
      got2 is not None and got2.name == "default", f"{got2}")

# device_exists は実デバイス名で True、でたらめな名前で False
import sounddevice as sd
real = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
if real:
    check("9. device_exists: 実在する名前", audio.device_exists(real[0]) is True,
          f"{real[0]}")
check("10. device_exists: 存在しない名前",
      audio.device_exists("no_such_device_xyz") is False)

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run python $SCRATCH/test_task1.py`
Expected: FAIL（`mic_device` が無い、`_requested_device` が未定義、`device_exists` が未定義）

- [ ] **Step 3: 設定キーを追加する**

`_daemon_constants.py` の `DEFAULT_CONFIG` に追加（`voice_command_key` の直前あたり、既存の並びに合わせる）:

```python
    # 音声デバイス。null = OS のデフォルトに追従。値はデバイス名（番号は不安定）
    "mic_device": None,
    "monitor_device": None,
```

- [ ] **Step 4: `device_exists` を追加する**

`_daemon_audio.py` の `find_device_by_name` の直後に追加:

```python
def device_exists(name: str) -> bool | None:
    """OS 側の一覧にこの名前のノードがあるか。取得できなければ None。

    PortAudio の一覧はキャッシュで、再列挙には全ストリームの破棄が必要なため、
    「抜き差しされたデバイスが戻ったか」の判定には使えない。OS 側に直接聞く。
    PortAudio のデバイス名は PipeWire のノード名と一致する。
    """
    if shutil.which("wpctl"):
        try:
            result = subprocess.run(["wpctl", "status", "--name"],
                                    capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout:
                return name in result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    if shutil.which("pactl"):
        for kind in ("sources", "sinks"):
            try:
                result = subprocess.run(["pactl", "list", "short", kind],
                                        capture_output=True, text=True, timeout=5)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return None
            if name in result.stdout:
                return True
        return False
    return None
```

注意: `wpctl status --name` が使えない古い wpctl では `returncode != 0` になる。その場合は `pactl` へ、それも無ければ `None` を返して呼び出し側に判定を諦めさせる。実機で `wpctl status --name` が動くことを Step 6 で確かめる。

- [ ] **Step 5: `_resolve` を書き換える**

`_daemon_recorder_capture.py` の既存 `_resolve`（294-312 行）を次で置き換え、`_resolve_index` と `_requested_device` を追加する:

```python
    def _requested_device(self, label: str) -> str | None:
        """config で指定されたデバイス名。CLI で番号指定されている場合は None。

        CLI と config が同時に効くと張り替えが競合するため、CLI を優先して
        config を無効化する。
        """
        if getattr(self.args, label) is not None:
            return None
        value = load_config().get(f"{label}_device")
        return value.strip() if isinstance(value, str) and value.strip() else None

    def _resolve(self, label: str, index: int | None) -> AudioDevice | None:
        """デバイスを解決する。優先順位は CLI 番号 > config のデバイス名 > 自動。

        config の名前が見つからない場合は自動にフォールバックする。設定値は
        書き換えない（デバイスが戻ったら復帰させるため）。
        """
        if index is not None:
            return self._resolve_index(label, index)
        if requested := self._requested_device(label):
            if (found := find_device_by_name(requested, capture=True)) is not None:
                return found
            logger.info("%s: 指定デバイス %s が見つかりません。自動で代替します",
                        label, requested)
        resolve = resolve_mic_device if label == "mic" else resolve_monitor_device
        return resolve(None)

    def _resolve_index(self, label: str, index: int) -> AudioDevice | None:
        """番号指定を解決する。前回開いた名前と一致するものを優先する。

        refresh_device_list() の後は同じ番号が別のデバイスを指しうるため、番号だけを
        頼りにすると無言で別のマイクを掴む。
        """
        resolve = resolve_mic_device if label == "mic" else resolve_monitor_device
        device = resolve(index)
        pinned = self._pinned_names.get(label)
        if pinned and device is not None and device.name != pinned:
            if (found := find_device_by_name(pinned, capture=True)) is not None:
                logger.info("%s: 番号 %d は %s に変わったため名前で再解決: %s",
                            label, index, device.name, found)
                return found
            logger.warning("%s: 指定デバイス %s が見つかりません。番号 %d の %s を使います",
                           label, pinned, index, device.name)
        if device is not None:
            self._pinned_names[label] = device.name
        return device
```

`_daemon_recorder_capture.py` の import に `load_config` が既にあることを確認する（21 行目付近に `from shadow_clerk._daemon_config import load_config` がある）。

- [ ] **Step 6: 検証スクリプトを通す**

Run: `uv run python $SCRATCH/test_task1.py`
Expected: `=== 10/10 PASS ===`

失敗する場合、`device_exists` が実機で `None` を返しているなら `wpctl status --name` の出力を直接確認する:

Run: `wpctl status --name | head -20`

- [ ] **Step 7: 構文と重複をチェックする**

Run: `uv run python -m py_compile src/shadow_clerk/_daemon_constants.py src/shadow_clerk/_daemon_audio.py src/shadow_clerk/_daemon_recorder_capture.py`
Run: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`
Expected: 構文エラーなし、10.00/10

- [ ] **Step 8: コミット**

```bash
git add src/shadow_clerk/_daemon_constants.py src/shadow_clerk/_daemon_audio.py src/shadow_clerk/_daemon_recorder_capture.py
git commit -m "Add mic_device/monitor_device config keys and name-based resolution"
```

---

### Task 2: 張り替えトリガの分離

**Files:**
- Modify: `src/shadow_clerk/_daemon_recorder_capture.py`（`_CaptureStream.__init__`、`_open_capture`、`_watch_streams`、`_audio_capture_thread`）
- Test: `$SCRATCH/test_task2.py`

**Interfaces:**
- Consumes: Task 1 の `_requested_device`、`_resolve`、`device_exists`
- Produces:
  - `_Reconnect` データクラス — `reason: str`、`labels: frozenset[str] | None`（`None` = 全ストリーム）、`refresh: bool`
  - `_CaptureStream.requested: str | None` — 開いた時点で要求されていた設定値
  - `_watch_streams(streams, degraded_wait) -> _Reconnect | None`（戻り値が `str | None` から変わる）

- [ ] **Step 1: 検証スクリプトを書く**

`$SCRATCH/test_task2.py`:

```python
"""Task 2: 張り替えトリガ 2 系統の検証"""
from __future__ import annotations
import argparse, queue, threading, time

from shadow_clerk import _daemon_recorder_capture as cap
from shadow_clerk.domain import AudioDevice

results: list[bool] = []

def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)

class Host(cap._RecorderCaptureMixin):
    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        self.args = argparse.Namespace(mic=None, monitor=None)
        self.stop_event = threading.Event()
        self.mic_queue, self.monitor_queue = queue.Queue(), queue.Queue()
        self.backend_name, self.backend = "pipewire", None
        self.use_mic = self.use_monitor = False
        self._pinned_names = {}
        self._monitor_backend = None

def make_stream(label: str, name: str, requested: str | None) -> cap._CaptureStream:
    """open() せずに監視対象として使えるダミーストリーム"""
    s = cap._CaptureStream(label, AudioDevice(index=1, name=name), queue.Queue())
    s.requested = requested
    s.last_frame = time.monotonic()   # 途絶していない状態にする
    return s

# チェック間隔を詰めて短時間で判定させる
cap.STREAM_CHECK_INTERVAL = 0.05
cap.STREAM_RESOLVE_INTERVAL = 0.1
cap.get_default_sink_name = lambda: "sinkA"

# --- 1. フォールバック中は静止する（初版の欠陥の回帰テスト） ---
# 指定デバイスが無い状態で 1 秒監視し、張り替え要求が出ないことを確かめる。
# stop_event で抜けたときだけ None が返るので、None == 静止していた、となる。
host = Host()
cap.load_config = lambda: {"mic_device": "GoneDevice"}
cap.device_exists = lambda name: False          # まだ戻っていない
st = make_stream("mic", "default", requested="GoneDevice")
holder: dict[str, object] = {}
t = threading.Thread(target=lambda: holder.update(
    result=host._watch_streams([st], None)), daemon=True)
t.start()
time.sleep(1.0)
host.stop_event.set()
t.join(timeout=3)
check("1. フォールバック中は張り替えない（1秒静止）",
      "result" in holder and holder["result"] is None,
      f"結果={holder.get('result', 'スレッド未終了')!r}")

# --- 2. 設定値が変わったら張り替える ---
host2 = Host()
cap.load_config = lambda: {"mic_device": "NewMic"}
cap.device_exists = lambda name: False
cap.find_device_by_name = lambda name, capture: AudioDevice(index=2, name="NewMic")
st2 = make_stream("mic", "default", requested=None)   # いまは自動で開いている
req = host2._watch_streams([st2], None)
check("2. 設定変更を検知", req is not None and req.labels == frozenset({"mic"}),
      f"{req}")
check("2b. キャッシュにあるので再列挙不要", req is not None and req.refresh is False,
      f"refresh={req.refresh if req else None}")

# --- 3. 設定値が変わり、キャッシュに無ければ再列挙が要る ---
host3 = Host()
cap.load_config = lambda: {"mic_device": "NotCached"}
cap.find_device_by_name = lambda name, capture: None
st3 = make_stream("mic", "default", requested=None)
req3 = host3._watch_streams([st3], None)
check("3. キャッシュに無ければ再列挙を要求",
      req3 is not None and req3.refresh is True, f"{req3}")

# --- 4. フォールバック中に指定デバイスが戻ったら張り替える ---
host4 = Host()
cap.load_config = lambda: {"mic_device": "BackDevice"}
cap.device_exists = lambda name: name == "BackDevice"
st4 = make_stream("mic", "default", requested="BackDevice")
req4 = host4._watch_streams([st4], None)
check("4. デバイス復帰を検知", req4 is not None and req4.labels == frozenset({"mic"}),
      f"{req4}")
check("4b. 復帰は再列挙が要る", req4 is not None and req4.refresh is True)

# --- 5. device_exists が None（OS 一覧を取れない）なら復帰判定しない ---
host5 = Host()
cap.load_config = lambda: {"mic_device": "Unknown"}
cap.device_exists = lambda name: None
st5 = make_stream("mic", "default", requested="Unknown")
host5.stop_event.set()   # 監視ループに入らず即 None を返させる
check("5. OS 一覧が無いなら復帰判定しない",
      host5._watch_streams([st5], None) is None)

# --- 6. モニターが config 固定なら follow_sink を切る ---
host6 = Host()
cap.load_config = lambda: {"monitor_device": "PinnedMon"}
check("6. config 固定なら follow_sink=False",
      host6._should_follow_sink() is False)
cap.load_config = lambda: {"monitor_device": None}
check("6b. 自動なら follow_sink=True", host6._should_follow_sink() is True)

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run python $SCRATCH/test_task2.py`
Expected: FAIL（`_Reconnect` が無い、`requested` 属性が無い、`_should_follow_sink` が未定義）

- [ ] **Step 3: `_Reconnect` と `requested` を追加する**

`_daemon_recorder_capture.py` の import に `from dataclasses import dataclass` を追加し、`logger = ...` の直後に置く:

```python
@dataclass(frozen=True)
class _Reconnect:
    """張り替え要求。

    labels=None は全ストリームが対象。refresh=True はデバイス一覧の再列挙が
    必要な場合で、再列挙は開いている全ストリームを破棄する。
    """

    reason: str
    labels: frozenset[str] | None = None
    refresh: bool = True
```

`_CaptureStream.__init__` のシグネチャと本体に `requested` を足す:

```python
    def __init__(self, label: str, device: AudioDevice, audio_queue: queue.Queue,
                 follow_sink: bool = False, requested: str | None = None) -> None:
        self.label = label
        self.device = device
        self.requested = requested   # 開いた時点で config が要求していたデバイス名
        self.follow_sink = follow_sink
```

（`self.follow_sink` 以降の既存行はそのまま）

`_open_capture` にも通す:

```python
    def _open_capture(self, label: str, device: AudioDevice | None, audio_queue: queue.Queue,
                      follow_sink: bool = False,
                      requested: str | None = None) -> _CaptureStream | None:
        """キャプチャストリームを開く。一時的な失敗に備えて 1 度だけリトライする。"""
        if device is None:
            return None
        for attempt in range(2):
            stream = _CaptureStream(label, device, audio_queue, follow_sink, requested)
            if stream.open():
                return stream
            if attempt == 0 and self.stop_event.wait(1.0):
                break
        return None
```

- [ ] **Step 4: `_should_follow_sink` を追加する**

`_requested_device` の直後に追加:

```python
    def _should_follow_sink(self) -> bool:
        """デフォルト Sink の変更でモニターを張り替えてよいか。

        CLI でも config でもモニターを固定していない場合だけ追従する。固定して
        いるのに追従すると、出力先を変えるたび同じデバイスを開き直すだけになる。
        """
        return self.args.monitor is None and self._requested_device("monitor") is None
```

- [ ] **Step 5: `_watch_streams` にトリガ 2 系統を実装する**

既存の `_watch_streams` を次で置き換える:

```python
    def _watch_streams(self, streams: list[_CaptureStream],
                       degraded_wait: float | None = None) -> _Reconnect | None:
        """ストリームを監視し、張り替え要求を返す。停止要求なら None。

        degraded_wait は一部のデバイスを開けていない場合の再試行間隔。
        """
        if not streams:
            # 1 本も開けていない。即座に返すと再列挙のビジーループになるので待つ
            if self.stop_event.wait(degraded_wait or STREAM_DEGRADED_RETRY_SEC):
                return None
            return _Reconnect("キャプチャデバイスを取得できません")
        retry_at = time.monotonic() + degraded_wait if degraded_wait else None
        next_resolve = time.monotonic() + STREAM_RESOLVE_INTERVAL
        while not self.stop_event.wait(STREAM_CHECK_INTERVAL):
            if retry_at is not None and time.monotonic() >= retry_at:
                return _Reconnect("開けていないデバイスの再試行")
            for stream in streams:
                if (idle := stream.idle_sec()) > STREAM_STALL_SEC:
                    return _Reconnect(
                        f"{stream.label} のフレームが {idle:.0f} 秒途絶 "
                        f"({stream.device.name})")
            if (req := self._config_changed(streams)) is not None:
                return req
            if time.monotonic() < next_resolve:
                continue
            next_resolve = time.monotonic() + STREAM_RESOLVE_INTERVAL
            for stream in streams:
                if (new_sink := stream.changed_sink()) is not None:
                    return _Reconnect(f"デフォルト出力先が変更 {stream.sink} → {new_sink}")
            if (req := self._requested_returned(streams)) is not None:
                return req
        return None

    def _config_changed(self, streams: list[_CaptureStream]) -> _Reconnect | None:
        """設定値が開いた時点から変わっていれば張り替えを要求する（2 秒ごと）"""
        for stream in streams:
            requested = self._requested_device(stream.label)
            if requested == stream.requested:
                continue
            # 目的のデバイスがキャッシュ上にあるなら再列挙は要らず、
            # この系統だけ開き直せばもう一方の音声は途切れない
            cached = (requested is None
                      or find_device_by_name(requested, capture=True) is not None)
            return _Reconnect(
                f"{stream.label} の指定デバイスが変更 {stream.requested} → {requested}",
                labels=frozenset({stream.label}), refresh=not cached)
        return None

    def _requested_returned(self, streams: list[_CaptureStream]) -> _Reconnect | None:
        """フォールバック中の指定デバイスが戻っていれば張り替えを要求する（10 秒ごと）

        戻ったばかりのデバイスは PortAudio のキャッシュに無いので再列挙が要る。
        """
        for stream in streams:
            if not stream.requested or stream.device.name == stream.requested:
                continue
            if device_exists(stream.requested) is True:
                return _Reconnect(
                    f"{stream.label} の指定デバイスが復帰 {stream.requested}",
                    labels=frozenset({stream.label}), refresh=True)
        return None
```

`_daemon_audio` からの import に `device_exists` を追加する。

- [ ] **Step 6: 呼び出し側を新しい戻り値に合わせる**

`_audio_capture_thread` 内の `reason` を使っている箇所を修正する（Task 3 で本格的に書き換えるので、ここでは最小限の追従にとどめる）:

```python
                req = self._watch_streams(live, degraded_wait if degraded else None)
                for stream in live:
                    stream.close()
                if req is None:
                    return
                degraded_wait = (min(degraded_wait * 2, STREAM_DEGRADED_RETRY_MAX_SEC)
                                 if degraded else STREAM_DEGRADED_RETRY_SEC)
                logger.warning("音声ストリーム再接続: %s", req.reason)
```

同じく `_open_capture` の monitor 呼び出しに `requested` と新しい `follow_sink` を渡す:

```python
                    monitor = self._open_capture(
                        "monitor", self._resolve("monitor", self.args.monitor),
                        self.monitor_queue, follow_sink=self._should_follow_sink(),
                        requested=self._requested_device("monitor"),
                    )
```

mic 側も同様に:

```python
                mic = self._open_capture("mic", self._resolve("mic", self.args.mic),
                                         self.mic_queue,
                                         requested=self._requested_device("mic"))
```

- [ ] **Step 7: 開けなかった場合のフォールバックを実装する**

設計の解決規則 2 は「一覧にない**または開こうとして失敗した**」場合にフォールバックすると定めている。ここまでの実装は「一覧にない」しか扱っていないため、他アプリが排他的に掴んでいて開けないケースで指定デバイスに固執してしまう。

`_open_capture` の直後にフォールバックを挟むヘルパーを追加する（`_open_capture` の直後に置く）:

```python
    def _open_requested(self, label: str, index: int | None,
                        audio_queue: queue.Queue,
                        follow_sink: bool = False) -> _CaptureStream | None:
        """指定デバイスで開き、失敗したら自動デバイスで開き直す。

        列挙はできても他アプリが排他的に掴んでいて開けないことがある。設定値は
        書き換えず、戻ってきたら復帰判定で拾い直す。
        """
        requested = self._requested_device(label)
        stream = self._open_capture(label, self._resolve(label, index), audio_queue,
                                    follow_sink, requested)
        if stream is not None or not requested:
            return stream
        logger.info("%s: 指定デバイス %s を開けません。自動で代替します", label, requested)
        resolve = resolve_mic_device if label == "mic" else resolve_monitor_device
        return self._open_capture(label, resolve(None), audio_queue, follow_sink, requested)
```

`_audio_capture_thread` の 2 箇所の `self._open_capture(...)` 呼び出しを `self._open_requested(...)` に置き換える:

```python
                mic = self._open_requested("mic", self.args.mic, self.mic_queue)
```

```python
                    monitor = self._open_requested(
                        "monitor", self.args.monitor, self.monitor_queue,
                        follow_sink=self._should_follow_sink())
```

`requested` を維持したまま自動デバイスで開くので、`_requested_returned` がフォールバック中と判定して復帰を監視し続ける。

- [ ] **Step 8: フォールバックの検証を追加して通す**

`$SCRATCH/test_task2.py` の末尾（`print(f"\n=== ...")` の直前）に追加:

```python
# --- 7. 開けないデバイスを指定したら自動にフォールバックする ---
host7 = Host()
cap.load_config = lambda: {"mic_device": "UnopenableMic"}
cap.find_device_by_name = lambda name, capture: (
    AudioDevice(index=4, name="UnopenableMic") if name == "UnopenableMic" else None)
cap.resolve_mic_device = lambda i: AudioDevice(index=0, name="default")

attempts: list[str] = []
class _FailingStream(cap._CaptureStream):
    def open(self):
        attempts.append(self.device.name)
        return self.device.name != "UnopenableMic"   # 指定デバイスだけ失敗させる

_real_stream = cap._CaptureStream
cap._CaptureStream = _FailingStream
try:
    got7 = host7._open_requested("mic", None, queue.Queue())
finally:
    cap._CaptureStream = _real_stream

check("7. 指定デバイスを開けなければ自動にフォールバック",
      got7 is not None and got7.device.name == "default",
      f"試行={attempts} 結果={got7.device.name if got7 else None}")
check("7b. フォールバック中も requested を保持する",
      got7 is not None and got7.requested == "UnopenableMic",
      f"requested={got7.requested if got7 else None}")
```

Run: `uv run python $SCRATCH/test_task2.py`
Expected: `=== 11/11 PASS ===`

- [ ] **Step 9: 既存のウォッチドッグ検証で退行がないことを確認する**

Task 2 は監視ループの中核を触るため、既存の実機検証も回す。`$SCRATCH/test_watchdog.py` が無ければ次で作る（本計画の末尾「付録: 既存のウォッチドッグ検証スクリプト」に全文がある）。

Run: `uv run python $SCRATCH/test_watchdog.py`
Expected: `=== 7/7 PASS ===`

- [ ] **Step 10: 構文・重複チェックとコミット**

Run: `uv run python -m py_compile src/shadow_clerk/_daemon_recorder_capture.py`
Run: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`

```bash
git add src/shadow_clerk/_daemon_recorder_capture.py
git commit -m "Split reconnect trigger into config change and device return"
```

---

### Task 3: デバイス一覧スナップショットと `/api/audio-devices`

**Files:**
- Modify: `src/shadow_clerk/_daemon_audio.py`（`snapshot_devices` を追加）
- Modify: `src/shadow_clerk/_daemon_recorder_capture.py`（`__init__` に `_device_snapshot`）
- Modify: `src/shadow_clerk/_daemon_dashboard_ops_config.py`（ハンドラを追加）
- Modify: `src/shadow_clerk/_daemon_dashboard_base.py`（ルーティングを追加、38 行目付近の `elif path == "/api/status":` の並びに追加）
- Test: `$SCRATCH/test_task3.py`

**Interfaces:**
- Consumes: なし（既存の `sd.query_devices()` のみ）
- Produces:
  - `snapshot_devices() -> dict[str, Any]` — `{"mic": [{"name", "label"}], "monitor": [...], "updated_at": float}`
  - `_RecorderCaptureMixin._device_snapshot: dict[str, Any]` — `__init__` で初期化する。Task 4 の監視ループがストリームを開くたびに更新する
  - `GET /api/audio-devices` — `_device_snapshot` に `cli_pinned` を添えて返す

- [ ] **Step 1: 検証スクリプトを書く**

`$SCRATCH/test_task3.py`:

```python
"""Task 4: デバイス一覧スナップショットと API の検証"""
from __future__ import annotations
import json, urllib.request

from shadow_clerk._daemon_audio import snapshot_devices

results: list[bool] = []
def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)

snap = snapshot_devices()
check("1. mic と monitor のキーがある", "mic" in snap and "monitor" in snap)
check("2. updated_at が入る", isinstance(snap.get("updated_at"), float))
check("3. mic に入力デバイスが 1 つ以上ある", len(snap["mic"]) > 0,
      f"{len(snap['mic'])} 件")
check("4. 各要素が name と label を持つ",
      all("name" in d and "label" in d for d in snap["mic"] + snap["monitor"]))
check("5. monitor は .monitor / Monitor of だけ",
      all(d["name"].endswith(".monitor") or d["name"].lower().startswith("monitor of ")
          for d in snap["monitor"]),
      f"{[d['name'] for d in snap['monitor']][:3]}")
check("6. mic に monitor デバイスを含めない",
      not any(d["name"].endswith(".monitor") for d in snap["mic"]))

# 生 ALSA デバイスは選択肢に出さない（device_exists で検証できず、掴むと
# サウンドカードを排他確保して他アプリの音を壊すため）
import sounddevice as sd
node_inputs = [str(d["name"]) for d in sd.query_devices()
               if d["max_input_channels"] > 0
               and (str(d["name"]).startswith("alsa_input.")
                    or str(d["name"]).startswith("alsa_output."))]
if node_inputs:
    check("7. 生 ALSA デバイスを含めない",
          all(d["name"].startswith(("alsa_input.", "alsa_output."))
              for d in snap["mic"] + snap["monitor"]),
          f"{[d['name'] for d in snap['mic'] + snap['monitor']][:4]}")
else:
    print("[SKIP] 7. 生 ALSA 除外（ノード名デバイスが無い環境）")

# デーモンが動いていれば API も確認する
try:
    with urllib.request.urlopen("http://localhost:8765/api/audio-devices", timeout=3) as r:
        api = json.loads(r.read())
    check("8. API が mic/monitor/updated_at を返す",
          all(k in api for k in ("mic", "monitor", "updated_at")), f"{list(api)}")
    check("9. API が cli_pinned を返す",
          isinstance(api.get("cli_pinned"), dict)
          and set(api["cli_pinned"]) == {"mic", "monitor"}, f"{api.get('cli_pinned')}")
except Exception as e:
    print(f"[SKIP] 8-9. API 確認（デーモン未起動）: {e}")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run python $SCRATCH/test_task3.py`
Expected: FAIL（`ImportError: cannot import name 'snapshot_devices'`）

- [ ] **Step 3: `snapshot_devices` を実装する**

`_daemon_audio.py` の `find_monitor_device_sd` の直前に追加する:

```python
def snapshot_devices() -> dict[str, Any]:
    """UI に出すデバイス一覧のスナップショットを取る。

    PortAudio のキャッシュを読むだけなので、ストリームを開くたびに呼んでも
    コストは無視できる。ブラウザからの要求ごとに再列挙はできない
    （refresh_device_list が全ストリームを破棄するため）ので、監視スレッドが
    このスナップショットを更新し、API はそれを返す。
    """
    import sounddevice as sd
    import time as _time
    mic: list[dict[str, str]] = []
    monitor: list[dict[str, str]] = []
    try:
        devices = sd.query_devices()
    except Exception as e:
        logger.warning("デバイス一覧を取得できません: %s", e)
        return {"mic": [], "monitor": [], "updated_at": None}
    inputs = [str(d["name"]) for d in devices if d["max_input_channels"] > 0]
    # 選択肢は PipeWire/PulseAudio のノードに限る。PortAudio は生 ALSA デバイス
    # ("HD-Audio Generic: ALC257 Analog (hw:1,0)") も列挙するが、これらは
    # device_exists で存在を確認できず復帰判定が働かない上、掴むとサウンド
    # カードを排他確保して他アプリの音を壊す。ノードが 1 つも無い環境
    # (PipeWire/PulseAudio 不在) でのみ全件にフォールバックする
    nodes = [n for n in inputs
             if n.startswith("alsa_input.") or n.startswith("alsa_output.")]
    for name in (nodes or inputs):
        entry = {"name": name, "label": _device_label(name)}
        if name.endswith(".monitor") or name.lower().startswith("monitor of "):
            monitor.append(entry)
        else:
            mic.append(entry)
    return {"mic": mic, "monitor": monitor, "updated_at": _time.time()}


def _device_label(name: str) -> str:
    """PipeWire のノード名を人間が読める形に整える。

    例: alsa_input.usb-Shokz_Shokz_Loop110_96D3...-02.mono-fallback
        → Shokz Shokz Loop110 (usb)
    整形できない名前はそのまま返す。
    """
    body = name
    for prefix, kind in (("alsa_input.", ""), ("alsa_output.", "")):
        if body.startswith(prefix):
            body = body[len(prefix):]
            break
    body = body.removesuffix(".monitor")
    parts = body.split("-")
    if len(parts) >= 2 and parts[0] in ("usb", "pci", "platform", "bluez"):
        # usb-Shokz_Shokz_Loop110_96D3...-02.mono-fallback → Shokz Shokz Loop110
        middle = "-".join(parts[1:])
        middle = middle.split(".")[0]
        words = [w for w in middle.split("_") if w and not w.isdigit()]
        # 末尾のシリアルらしき長い英数字は落とす
        if words and len(words[-1]) > 12 and any(c.isdigit() for c in words[-1]):
            words = words[:-1]
        if words:
            return f"{' '.join(words)} ({parts[0]})"
    return name
```

`_daemon_audio.py` の先頭 import に `from typing import Any` があることを確認する（既にある）。

- [ ] **Step 4: `_device_snapshot` を初期化する**

`_RecorderCaptureMixin.__init__`（`_daemon_recorder_capture.py`）の `self._monitor_backend = None` の直後に追加する:

```python
        # /api/audio-devices が返すデバイス一覧。Task 4 で監視スレッドが
        # ストリームを開くたびに更新する。起動直後のごく短い間だけ空になる
        self._device_snapshot: dict[str, Any] = {
            "mic": [], "monitor": [], "updated_at": None}
```

`_daemon_recorder_capture.py` の import に `from typing import Any` があることを確認する（既にある）。

- [ ] **Step 5: API ハンドラを追加する**

`_daemon_dashboard_ops_config.py` の `_serve_config` の直後に追加:

```python
    def _serve_audio_devices(self) -> None:
        """GET /api/audio-devices — 監視スレッドが更新したスナップショットを返す"""
        rec = self.recorder
        self._send_json({
            **rec._device_snapshot,
            # CLI で番号固定されている系統は config を無視するため、UI を操作不能にする
            "cli_pinned": {"mic": rec.args.mic is not None,
                           "monitor": rec.args.monitor is not None},
        })
```

`_daemon_dashboard_base.py` のルーティングに追加（`elif path == "/api/config":` の直後）:

```python
        elif path == "/api/audio-devices":
            self._serve_audio_devices()
```

- [ ] **Step 6: 検証スクリプトを通す**

Run: `uv run python $SCRATCH/test_task3.py`
Expected: `=== 7/7 PASS ===`（デーモン未起動なら 8-9 は SKIP）

- [ ] **Step 7: 構文・重複チェックとコミット**

Run: `uv run python -m py_compile src/shadow_clerk/_daemon_audio.py src/shadow_clerk/_daemon_recorder_capture.py src/shadow_clerk/_daemon_dashboard_ops_config.py src/shadow_clerk/_daemon_dashboard_base.py`
Run: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`

```bash
git add src/shadow_clerk/_daemon_audio.py src/shadow_clerk/_daemon_recorder_capture.py src/shadow_clerk/_daemon_dashboard_ops_config.py src/shadow_clerk/_daemon_dashboard_base.py
git commit -m "Add device list snapshot and GET /api/audio-devices"
```

---

### Task 4: 張り替えの粒度

**Files:**
- Modify: `src/shadow_clerk/_daemon_recorder_capture.py`（`_audio_capture_thread` を書き換え。行番号は Task 1-3 の変更でずれているため、関数名で探すこと）
- Test: `$SCRATCH/test_task4.py`

**Interfaces:**
- Consumes: Task 2 の `_Reconnect`、Task 3 の `snapshot_devices()` と `_device_snapshot`
- Produces: `_audio_capture_thread` がストリームを `dict[str, _CaptureStream]` で保持し、`_Reconnect.refresh` が偽なら該当ラベルだけを閉じて開き直す

- [ ] **Step 1: 検証スクリプトを書く**

`$SCRATCH/test_task4.py`:

```python
"""Task 3: 張り替えの粒度の検証 — マイクの切替でモニターが途切れないこと"""
from __future__ import annotations
import argparse, logging, queue, threading, time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

from shadow_clerk import _daemon_recorder_capture as cap
from shadow_clerk._daemon_audio import detect_backend, find_monitor_device_sd

opened: list[cap._CaptureStream] = []
_orig_open = cap._CaptureStream.open

def _tracking_open(self):
    ok = _orig_open(self)
    if ok:
        opened.append(self)
    return ok

cap._CaptureStream.open = _tracking_open

class Host(cap._RecorderCaptureMixin):
    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        self.args = argparse.Namespace(mic=None, monitor=None)
        self.stop_event = threading.Event()
        self.mic_queue, self.monitor_queue = queue.Queue(), queue.Queue()
        self.backend_name, self.backend = detect_backend("auto")
        self.use_mic = self.use_monitor = False
        self._pinned_names = {}
        self._monitor_backend = None

results: list[bool] = []
def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)

# 実在するモニターデバイスの名前を取り、それを config で指定する形にする
mon = find_monitor_device_sd()
assert mon is not None, "モニターデバイスが見つからないため検証できません"

config = {"mic_device": None, "monitor_device": None}
cap.load_config = lambda: dict(config)

host = Host()
th = threading.Thread(target=host._audio_capture_thread, daemon=True)
th.start()
try:
    time.sleep(4)
    check("1. 両系統が開いた", host.use_mic and host.use_monitor,
          f"use_mic={host.use_mic} use_monitor={host.use_monitor}")
    mon_stream = next(s for s in opened if s.label == "monitor")
    before_opens = len(opened)

    # モニターのフレームを数えながらマイクの設定を変える
    while not host.monitor_queue.empty():
        host.monitor_queue.get_nowait()
    import sounddevice as sd
    mic_name = str(sd.query_devices(None, kind="input")["name"])
    config["mic_device"] = mic_name          # 実在する名前 → 再列挙不要のはず
    time.sleep(5)

    new_opens = [s for s in opened[before_opens:]]
    check("2. マイクだけが開き直された",
          len(new_opens) == 1 and new_opens[0].label == "mic",
          f"{[s.label for s in new_opens]}")
    check("3. モニターのストリームは同一オブジェクトのまま",
          any(s is mon_stream for s in opened), "閉じられず再利用されている")
    check("4. モニターのフレームが流れ続けている",
          host.monitor_queue.qsize() > 50, f"{host.monitor_queue.qsize()} フレーム")
finally:
    host.stop_event.set()
    th.join(timeout=10)

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run python $SCRATCH/test_task4.py`
Expected: FAIL（現状はマイクの設定変更でもモニターごと開き直すため「2. マイクだけが開き直された」が落ちる）

- [ ] **Step 3: `_audio_capture_thread` を書き換える**

既存の `_audio_capture_thread` 全体を次で置き換える:

```python
    def _audio_capture_thread(self) -> None:
        """マイク/モニターをキャプチャし、途絶・出力先変更・設定変更で再接続する。

        マイクとモニターを 1 スレッドでまとめて管理するのは、デバイス一覧の再列挙
        (refresh_device_list) が開いている PortAudio ストリームを全て破棄するため。
        逆に再列挙が要らない張り替え（設定で選び直した先がキャッシュ上にある）では
        該当する系統だけを開き直し、もう一方の音声を途切れさせない。
        """
        streams: dict[str, _CaptureStream] = {}
        backend_started = False
        need_refresh = False
        degraded_wait = STREAM_DEGRADED_RETRY_SEC
        try:
            while not self.stop_event.is_set():
                try:
                    if need_refresh:
                        # サスペンド復帰・抜き差し後はキャッシュが陳腐化している。
                        # 全ストリームが閉じている状態でのみ呼べる
                        try:
                            refresh_device_list()
                        except Exception as e:
                            logger.warning("デバイス一覧の再列挙に失敗: %s", e)
                        need_refresh = False

                    if "mic" not in streams:
                        if (s := self._open_capture(
                                "mic", self._resolve("mic", self.args.mic), self.mic_queue,
                                requested=self._requested_device("mic"))) is not None:
                            streams["mic"] = s
                    self.use_mic = "mic" in streams

                    if "monitor" not in streams and not backend_started:
                        s = self._open_capture(
                            "monitor", self._resolve("monitor", self.args.monitor),
                            self.monitor_queue, follow_sink=self._should_follow_sink(),
                            requested=self._requested_device("monitor"))
                        if s is not None:
                            streams["monitor"] = s
                        else:
                            logger.info("sounddevice でモニターを開けません、"
                                        "%s バックエンドにフォールバック", self.backend_name)
                            self._monitor_backend = threading.Thread(
                                target=self._monitor_backend_thread,
                                name="monitor-backend", daemon=True)
                            self._monitor_backend.start()
                            backend_started = True
                        self.use_monitor = "monitor" in streams

                    self._device_snapshot = snapshot_devices()

                    degraded = "mic" not in streams or (
                        "monitor" not in streams and not backend_started)
                    req = self._watch_streams(list(streams.values()),
                                              degraded_wait if degraded else None)
                    if req is None:
                        return
                    logger.warning("音声ストリーム再接続: %s", req.reason)
                    degraded_wait = (min(degraded_wait * 2, STREAM_DEGRADED_RETRY_MAX_SEC)
                                     if degraded else STREAM_DEGRADED_RETRY_SEC)
                    had_live = bool(streams)
                    if req.refresh:
                        # 再列挙は全ストリームを破棄するので、全部閉じてから
                        for stream in streams.values():
                            stream.close()
                        streams.clear()
                        need_refresh = True
                    else:
                        for label in (req.labels or frozenset(streams)):
                            if (stream := streams.pop(label, None)) is not None:
                                stream.close()
                    # 待機は「開き直しても失敗する」状態でのビジーループ防止。
                    # 直前に生きたストリームがあったなら待たずに張り替える
                    if not had_live and self.stop_event.wait(STREAM_RETRY_SEC):
                        return
                except Exception:
                    # 1 スレッドで両系統を持つため、ここで落とすと録音が全て止まる
                    logger.exception("音声キャプチャで予期しないエラー、再試行します")
                    for stream in streams.values():
                        stream.close()
                    streams.clear()
                    need_refresh = True
                    if self.stop_event.wait(STREAM_RETRY_SEC):
                        return
        finally:
            for stream in streams.values():
                stream.close()
```

`snapshot_devices()` と `self._device_snapshot` は Task 3 で追加済みである。`_daemon_recorder_capture.py` の import に `snapshot_devices` を足すこと:

```python
from shadow_clerk._daemon_audio import (
    AudioBackend, PulseAudioBackend, detect_backend, device_exists, find_device_by_name,
    get_default_sink_name, refresh_device_list, resolve_mic_device, resolve_monitor_device,
    snapshot_devices,
)
```

この行で `_device_snapshot` が毎オープンごとに更新されるため、設定パネルのセレクトは起動直後から埋まる。

- [ ] **Step 4: 検証スクリプトを通す**

Run: `uv run python $SCRATCH/test_task4.py`
Expected: `=== 4/4 PASS ===`

- [ ] **Step 5: 既存のウォッチドッグ検証で退行がないことを確認する**

Run: `uv run python $SCRATCH/test_watchdog.py`
Expected: `=== 7/7 PASS ===`

- [ ] **Step 6: 構文・重複チェックとコミット**

Run: `uv run python -m py_compile src/shadow_clerk/_daemon_recorder_capture.py`
Run: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`

```bash
git add src/shadow_clerk/_daemon_recorder_capture.py
git commit -m "Reconnect only the affected stream when no re-enumeration is needed"
```

---

### Task 5: バックエンド経路への名前指定

**Files:**
- Modify: `src/shadow_clerk/_daemon_recorder_capture.py`（`_capture_monitor_backend_once`）
- Test: `$SCRATCH/test_task5.py`

**Interfaces:**
- Consumes: Task 1 の `_requested_device`
- Produces: `_capture_monitor_backend_once` が `monitor_device` 設定時に `detect_monitor_source()` の代わりにその名前を使う

`pw-record --target` は「serial or name」を受け付け、`parec --device=` も名前指定である（`pw-record --help` および実機で確認済み）。

- [ ] **Step 1: 検証スクリプトを書く**

`$SCRATCH/test_task5.py`:

```python
"""Task 5: バックエンド経路が monitor_device を尊重することの検証"""
from __future__ import annotations
import argparse, queue, threading

from shadow_clerk import _daemon_recorder_capture as cap

results: list[bool] = []
def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)

class Recorder(cap._RecorderCaptureMixin):
    def __init__(self, backends) -> None:  # pylint: disable=super-init-not-called
        self.args = argparse.Namespace(mic=None, monitor=None)
        self.stop_event = threading.Event()
        self.mic_queue, self.monitor_queue = queue.Queue(), queue.Queue()
        self.backend_name, self.backend = "pipewire", None
        self.use_mic = self.use_monitor = False
        self._pinned_names = {}
        self._monitor_backend = None
        self._backends = backends

    def _monitor_backends(self):
        return iter(self._backends)

class FakeBackend:
    def __init__(self, auto_source="AUTO"):
        self.auto_source = auto_source
        self.detect_calls = 0
        self.used_source = None

    def detect_monitor_source(self):
        self.detect_calls += 1
        return self.auto_source

    def start_monitor_capture(self, source, q, stop_event):
        self.used_source = source

# 1. config 指定があればその名前を使い、自動検出を呼ばない
be = FakeBackend()
rec = Recorder([(be, "pipewire")])
cap.load_config = lambda: {"monitor_device": "PinnedMonitorName"}
rec._capture_monitor_backend_once()
check("1. 指定名がバックエンドに渡る", be.used_source == "PinnedMonitorName",
      f"渡された値={be.used_source!r}")
check("2. 自動検出を呼ばない", be.detect_calls == 0, f"{be.detect_calls} 回")

# 3. config が null なら従来どおり自動検出
be2 = FakeBackend()
rec2 = Recorder([(be2, "pipewire")])
cap.load_config = lambda: {"monitor_device": None}
rec2._capture_monitor_backend_once()
check("3. 未指定なら自動検出の結果を使う", be2.used_source == "AUTO",
      f"渡された値={be2.used_source!r}")
check("4. 自動検出を呼ぶ", be2.detect_calls == 1)

# 5. CLI で番号指定されている場合は config を無視して自動検出
be3 = FakeBackend()
rec3 = Recorder([(be3, "pipewire")])
rec3.args.monitor = 5
cap.load_config = lambda: {"monitor_device": "IgnoredName"}
rec3._capture_monitor_backend_once()
check("5. CLI 指定時は config を無視", be3.used_source == "AUTO",
      f"渡された値={be3.used_source!r}")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run python $SCRATCH/test_task5.py`
Expected: FAIL（現状は常に `detect_monitor_source()` の結果を使う）

- [ ] **Step 3: `_capture_monitor_backend_once` を修正する**

`for backend, name in self._monitor_backends():` の直後の `source = backend.detect_monitor_source()` を次で置き換える:

```python
        requested = self._requested_device("monitor")
        for backend, name in self._monitor_backends():
            # config で固定されていればその名前を直接渡す。pw-record --target は
            # serial または name を、parec --device= は name を受け付ける
            source = requested or backend.detect_monitor_source()
            if not source:
                continue
```

（`requested` はループの外で 1 回だけ読む）

- [ ] **Step 4: 検証スクリプトを通す**

Run: `uv run python $SCRATCH/test_task5.py`
Expected: `=== 5/5 PASS ===`

- [ ] **Step 5: 構文・重複チェックとコミット**

Run: `uv run python -m py_compile src/shadow_clerk/_daemon_recorder_capture.py`
Run: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`

```bash
git add src/shadow_clerk/_daemon_recorder_capture.py
git commit -m "Honour monitor_device on the pw-record/parec fallback path"
```

---

### Task 6: 設定パネルの UI

**Files:**
- Modify: `src/shadow_clerk/_daemon_dashboard_html.py`（設定パネルにセレクト 2 つ）
- Modify: `src/shadow_clerk/_daemon_dashboard_js_panels.py`（読み書き）
- Modify: `src/shadow_clerk/_i18n_ja.py` / `src/shadow_clerk/_i18n_en.py`
- Test: 実機のブラウザで確認

**Interfaces:**
- Consumes: Task 4 の `GET /api/audio-devices`、既存の `GET /api/config` と `POST /api/config`
- Produces: `#micDevice` / `#monitorDevice` の `<select>`。値は空文字が「自動」を意味し、保存時に `null` に変換する

- [ ] **Step 0: 既存の設定パネルの構造を読む**

このタスクだけは既存マークアップに合わせる必要があるため、先に実物を読む。想像で class 名を書かないこと。

Run: `grep -n "whisper_beam_size\|whisper_compute_type" src/shadow_clerk/_daemon_dashboard_html.py`
Run: `grep -n "whisper_beam_size\|loadConfig\|saveConfig\|function.*[Cc]onfig" src/shadow_clerk/_daemon_dashboard_js_panels.py | head -20`

確認すること:
- 設定行 1 つ分の HTML 構造（ラベルと入力の包み方、class 名）
- 設定を読み込んでフォームに反映する関数名
- 設定を集めて `POST /api/config` する関数名と、値を集めている箇所

以降のステップの `cfg-row` などは**例**であり、ここで確認した実際の構造に置き換えて実装する。

- [ ] **Step 1: i18n キーを追加する**

`_i18n_ja.py` の `dash.` 系の並びに追加:

```python
    "dash.mic_device": "マイク",
    "dash.monitor_device": "スピーカー（モニター）",
    "dash.device_auto": "自動（OS のデフォルト）",
    "dash.device_cli_pinned": "CLI で固定中（--mic / --monitor）",
    "dash.device_refresh": "一覧を更新",
    "dash.device_refresh_title": "デバイスを再検出します。音が一瞬途切れます",
```

`_i18n_en.py` の同じ位置に追加:

```python
    "dash.mic_device": "Microphone",
    "dash.monitor_device": "Speaker (monitor)",
    "dash.device_auto": "Auto (OS default)",
    "dash.device_cli_pinned": "Pinned by CLI (--mic / --monitor)",
    "dash.device_refresh": "Refresh list",
    "dash.device_refresh_title": "Re-detect devices. Audio drops briefly.",
```

- [ ] **Step 2: HTML を追加する**

`_daemon_dashboard_html.py` の設定パネル内、既存の設定項目の並びに追加する（`whisper_beam_size` などの行を探し、同じ構造に合わせる）:

```html
<div class="cfg-row">
  <label for="micDevice">{{i18n:dash.mic_device}}</label>
  <select id="micDevice"></select>
</div>
<div class="cfg-row">
  <label for="monitorDevice">{{i18n:dash.monitor_device}}</label>
  <select id="monitorDevice"></select>
</div>
```

既存行の class 名やマークアップ構造は必ず周囲に合わせること。`cfg-row` は例であり、実際のファイルで使われている class を使う。

- [ ] **Step 3: JS を追加する**

`_daemon_dashboard_js_panels.py` の設定読み込み関数に追加する。既存の `loadConfig` 相当の関数を探し、そこからデバイス一覧の取得と反映を呼ぶ:

```javascript
async function loadAudioDevices(cfg){
  let d;
  try{ d = await (await fetch('/api/audio-devices')).json(); }
  catch(e){ return; }
  const pinned = d.cli_pinned||{};
  fillDeviceSelect('micDevice', d.mic||[], cfg.mic_device, pinned.mic);
  fillDeviceSelect('monitorDevice', d.monitor||[], cfg.monitor_device, pinned.monitor);
}
function fillDeviceSelect(id, items, current, cliPinned){
  const sel = document.getElementById(id);
  if(!sel) return;
  if(cliPinned){
    // CLI 番号指定が config に優先するため、UI から変えても効かない
    sel.innerHTML = '';
    const o = document.createElement('option');
    o.textContent = I18N['dash.device_cli_pinned'];
    sel.appendChild(o);
    sel.disabled = true;
    return;
  }
  sel.disabled = false;
  sel.innerHTML = '';
  const auto = document.createElement('option');
  auto.value = ''; auto.textContent = I18N['dash.device_auto'];
  sel.appendChild(auto);
  let matched = false;
  for(const it of items){
    const o = document.createElement('option');
    o.value = it.name; o.textContent = it.label; o.title = it.name;
    if(it.name === current){ o.selected = true; matched = true; }
    sel.appendChild(o);
  }
  // 設定済みだが一覧に無い（抜かれている）場合も選択肢として残す
  if(current && !matched){
    const o = document.createElement('option');
    o.value = current; o.textContent = current; o.selected = true;
    sel.appendChild(o);
  }
}
```

保存側は、既存の設定保存関数が集めている値に次を加える。CLI 固定中は `disabled` なので、その場合は送らない（送ると `null` で上書きしてしまう）:

```javascript
  ...(document.getElementById('micDevice').disabled ? {} :
      {mic_device: document.getElementById('micDevice').value || null}),
  ...(document.getElementById('monitorDevice').disabled ? {} :
      {monitor_device: document.getElementById('monitorDevice').value || null}),
```

- [ ] **Step 4: 実機で確認する**

デーモンを起動する（既に稼働中なら多重起動ガードで失敗するので、先に `uv run clerk-util stop` する）:

Run: `uv run clerk-daemon`

ブラウザで `http://localhost:8765` を開き、設定パネルで次を確認する:

1. マイク／スピーカーのセレクトにデバイスが並ぶ（「自動（OS のデフォルト）」が先頭）
2. マイクを別のデバイスに変えて保存すると、ログに「mic の指定デバイスが変更」が出て 2 秒程度で張り替わる
3. その間、相手側（モニター）の文字起こしが途切れない
4. 「自動」に戻すと元に戻る

- [ ] **Step 5: 構文チェックとコミット**

Run: `uv run python -m py_compile src/shadow_clerk/_daemon_dashboard_html.py src/shadow_clerk/_daemon_dashboard_js_panels.py src/shadow_clerk/_i18n_ja.py src/shadow_clerk/_i18n_en.py`

```bash
git add src/shadow_clerk/_daemon_dashboard_html.py src/shadow_clerk/_daemon_dashboard_js_panels.py src/shadow_clerk/_i18n_ja.py src/shadow_clerk/_i18n_en.py
git commit -m "Add mic/speaker device selectors to the dashboard settings panel"
```

---

### Task 7: ドキュメント更新

**Files:**
- Modify: `README.md`（`config.yaml` サンプル、438 行目付近）
- Modify: `README.ja.md`（同じ箇所）
- Modify: `SPEC.md`（`/api/*` 一覧 100 行目付近、`config.yaml` サンプル 605 行目付近）

**Interfaces:**
- Consumes: Task 1 の設定キー、Task 4 の API
- Produces: なし（ドキュメントのみ）

- [ ] **Step 1: 該当箇所を特定する**

Run: `grep -n "whisper_beam_size\|api_endpoint" README.md README.ja.md SPEC.md | head -20`
Run: `grep -n "/api/config\|/api/status" SPEC.md | head`

- [ ] **Step 2: README の config サンプルに追記する**

`README.md` の `config.yaml` サンプルに追加:

```yaml
# Audio devices. null follows the OS default. Values are device NAMES,
# not indices — indices change between runs and can move while running.
# Selectable from the dashboard settings panel.
mic_device: null
monitor_device: null
```

`README.ja.md` の同じ箇所に追加:

```yaml
# 音声デバイス。null は OS のデフォルトに追従する。値はデバイス「名」であり
# 番号ではない（番号は起動ごとに変わり、稼働中にも移動するため）。
# ダッシュボードの設定パネルから選択できる。
mic_device: null
monitor_device: null
```

- [ ] **Step 3: SPEC.md の API 一覧に追記する**

`/api/*` ルート一覧の表または箇条書きに追加:

```
| `GET /api/audio-devices` | 選択可能な音声デバイス一覧（監視スレッドが保持するスナップショット） |
```

`config.yaml` サンプルにも `mic_device` / `monitor_device` を追加する（README.ja.md と同じコメント）。

- [ ] **Step 4: 記述の食い違いがないか確認する**

Run: `grep -n "mic_device\|monitor_device\|audio-devices" README.md README.ja.md SPEC.md`
Expected: 3 ファイルすべてに現れ、既定値が `null` で一致している

- [ ] **Step 5: コミット**

```bash
git add README.md README.ja.md SPEC.md
git commit -m "Document mic_device/monitor_device and /api/audio-devices"
```

---

## 完了条件

1. Task 1〜7 の全ステップにチェックが入っている
2. `$SCRATCH/test_watchdog.py` が 7/7 PASS（既存機能の退行なし）
3. `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/` が 10.00/10
4. `uv run --with mypy python -m mypy src/shadow_clerk/` のエラー数が着手前と同数（新規エラーなし。着手前に数えておくこと）
5. 実機のダッシュボードでマイクを切り替えられ、その間モニターの文字起こしが途切れない
6. 各ファイルが 700 行以内

## 第2段階（本計画の範囲外）

レベル表示（`AudioLevel` / `CaptureLevel`、両経路からの更新、バックエンド経路の生存監視、`level` SSE イベント、ヘッダーのレベルバーと定常ノイズ警告）は本計画に含まない。第 1 段階がマージされた後、別計画として作成する。設計は `docs/superpowers/specs/2026-08-10-audio-device-selection-design.md` の「レベル計測」「配信経路」「UI」節に記述済み。

## 付録: 既存のウォッチドッグ検証スクリプト

Task 2 と Task 4 の退行確認に使う。`$SCRATCH/test_watchdog.py` として保存する。

```python
"""音声ストリーム・ウォッチドッグの検証（退行確認用）"""
from __future__ import annotations
import argparse
import logging
import queue
import threading
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

from shadow_clerk import _daemon_recorder_capture as cap
from shadow_clerk._daemon_audio import detect_backend

opened: list[cap._CaptureStream] = []
_orig_open = cap._CaptureStream.open


def _tracking_open(self: cap._CaptureStream) -> bool:
    ok = _orig_open(self)
    if ok:
        opened.append(self)
    return ok


cap._CaptureStream.open = _tracking_open


class Host(cap._RecorderCaptureMixin):
    """キャプチャ機能だけを持つ最小ホスト (Transcriber の読み込みを避ける)"""

    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        self.args = argparse.Namespace(mic=None, monitor=None)
        self.stop_event = threading.Event()
        self.mic_queue = queue.Queue()
        self.monitor_queue = queue.Queue()
        self.backend_name, self.backend = detect_backend("auto")
        self.use_mic = self.use_monitor = False
        self._pinned_names = {}
        self._monitor_backend = None
        self._device_snapshot = {"mic": [], "monitor": [], "updated_at": None}


def drain(host: Host) -> tuple[int, int]:
    n = (host.mic_queue.qsize(), host.monitor_queue.qsize())
    for q in (host.mic_queue, host.monitor_queue):
        while not q.empty():
            q.get_nowait()
    return n


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    return ok


host = Host()
thread = threading.Thread(target=host._audio_capture_thread, daemon=True)
thread.start()
results = []
try:
    time.sleep(4)
    mic, mon = drain(host)
    results.append(check("1. 初期キャプチャ", mic > 0 and mon > 0, f"mic={mic} monitor={mon}"))
    results.append(check("1b. use_mic/use_monitor", host.use_mic and host.use_monitor,
                         f"use_mic={host.use_mic} use_monitor={host.use_monitor}"))

    print("\n--- モニターのストリームを停止 (サスペンドで死んだ状態を模擬) ---")
    # 実際にコールバックを止める。last_frame を書き換えるだけでは生きた
    # コールバックが即座に上書きしてしまい、途絶を再現できない。
    target = next(s for s in opened if s.label == "monitor")
    target._stream.stop()
    before = len(opened)

    deadline = time.monotonic() + cap.STREAM_STALL_SEC + cap.STREAM_CHECK_INTERVAL + 20
    while time.monotonic() < deadline and len(opened) <= before:
        time.sleep(0.5)
    results.append(check("2. 途絶を検知して再接続した", len(opened) > before,
                         f"ストリーム生成回数 {before} → {len(opened)}"))

    drain(host)
    time.sleep(3)
    mic, mon = drain(host)
    results.append(check("3. 再接続後にフレーム再開", mic > 0 and mon > 0,
                         f"mic={mic} monitor={mon}"))
    results.append(check("3b. use_monitor 復帰", host.use_monitor, f"use_monitor={host.use_monitor}"))

    print("\n--- デフォルト Sink 変更検知 (get_default_sink_name をスタブ) ---")
    mon_stream = next(s for s in reversed(opened) if s.label == "monitor")
    results.append(check("4. sink を記録している", mon_stream.sink is not None, f"sink={mon_stream.sink}"))
    cap.get_default_sink_name = lambda: "alsa_output.dummy_other_sink"
    deadline = time.monotonic() + 20
    before = len(opened)
    while time.monotonic() < deadline and len(opened) <= before:
        time.sleep(0.5)
    results.append(check("5. Sink 変更を検知して再接続", len(opened) > before,
                         f"ストリーム生成回数 {before} → {len(opened)}"))
finally:
    host.stop_event.set()
    thread.join(timeout=10)
    print(f"\nスレッド終了: {not thread.is_alive()}")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
```
