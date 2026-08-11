# 音声レベル表示（第2段階）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ダッシュボードのヘッダに入力レベルを常時表示し、「デバイスは開けているのにノイズしか来ていない」「指定デバイスが見つからず代替中」に設定パネルを開かずに気付けるようにする。

**Architecture:** ラベル（`mic` / `monitor`）ごとの `CaptureLevel` アキュムレータを recorder が保持し、sounddevice のコールバックと pw-record/parec の PCM 読み出しの**両方**が同じオブジェクトを更新する。FileWatcher の既存 1 秒ループが `level` SSE イベントとして配信する。同じ最終更新時刻を使って、これまで生存監視の無かった pw-record/parec 経路の停滞も検知できるようになる。

**Tech Stack:** Python 3.11+ / numpy / sounddevice (PortAudio) / PipeWire (`pw-record`) / 標準ライブラリの `http.server` + SSE / 素の JavaScript

**設計文書:** `docs/superpowers/specs/2026-08-10-audio-device-selection-design.md` の「レベル計測」「配信経路」「UI」節

**第1段階（マージ済み、PR #18）で入っているもの:** `mic_device`/`monitor_device` 設定、名前によるデバイス解決、張り替えトリガ 2 系統、ストリーム単位の張り替え、`GET /api/audio-devices`、`POST /api/audio-devices/refresh`、設定パネルのセレクト。

## Global Constraints

- Python は必ず `uv run python` で実行する（`python3` / `python` を直接使わない）
- 全ファイル先頭に `from __future__ import annotations`。関数シグネチャの引数・戻り値に型注釈は必須
- **1 ファイル最大 700 行。** `_daemon_dashboard_js_panels.py` は現在 696 行で余裕がない。Task 1 で分割してから UI に着手する。`_daemon_audio.py` も 666 行あり、Task 3（`level` 引数）と Task 4（読み出しループの書き換え）で 700 行に達する見込みである。超えたら `_capture_pcm_stream` とバックエンド 3 クラスを `_daemon_audio_backends.py` へ切り出すこと（デバイス列挙を `_daemon_audio_devices.py` に切り出した第1段階と同じ考え方）。分割したタスクの報告に、分割前後の行数を必ず書くこと
- ユーザー向け文字列は `t()` 経由。新規キーは `_i18n_ja.py` と `_i18n_en.py` の**両方**に追加する
- ログは logger 経由（`print` を使わない）。日本語コメントは可、周囲のスタイルに合わせる
- 値オブジェクトは `src/shadow_clerk/domain/` に `@dataclass(frozen=True)` で置く（DDD 規約）
- **`refresh_device_list()` は開いている全 PortAudio ストリームを破棄する。** capture スレッドから、全ストリームを閉じた状態でのみ呼ぶ。この不変条件を壊さないこと
- 音声コールバックは毎秒約33回走る。そこに置く処理は 480 サンプルの numpy 演算程度に留め、ロックやサブプロセスを持ち込まない
- テストフレームワークは無い。検証は `tests/` 配下に単体で走るスクリプトを置くか、既存の `tests/test_audio_capture_watchdog.py` を使う
- 重複コード検査: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/` を 10.00/10 に保つ
- mypy のエラー数を 101 から増やさない（着手前に `uv run --with mypy python -m mypy src/shadow_clerk/` で確認しておくこと）
- **回帰ゲート**: `uv run python tests/test_audio_capture_watchdog.py` が 8/8 PASS であること。実機の PortAudio を開くため約90秒かかる
- コミットメッセージは英語

## 稼働中デーモンについて

このリポジトリは **editable install** されており、`~/.local/share/uv/tools/shadow-clerk/.../__editable__.shadow_clerk-0.2.0.pth` が `src/` を直接指している。つまり**このツリーの変更は、ユーザーのデーモンを再起動した瞬間に本番へ載る**。

- 実際に会議を録音している本番デーモンがポート 8765 で動いていることがある。**止めない**こと
- 検証用のデーモンは必ず隔離して起動する:
  ```
  export SHADOW_CLERK_DATA_DIR=<スクラッチ配下のディレクトリ>
  uv run clerk-daemon --dashboard-port 8799
  ```
  PID を記録し、PID で kill する。`pkill` のパターンマッチは自分のシェルにマッチしうるので使わない

---

## ファイル構成

| ファイル | 責務 | 変更 |
|---|---|---|
| `src/shadow_clerk/domain/audio_level.py` | `AudioLevel` 値オブジェクト | 新規 |
| `src/shadow_clerk/_daemon_audio_level.py` | `CaptureLevel` アキュムレータ | 新規 |
| `src/shadow_clerk/_daemon_recorder_capture.py` | コールバックからのレベル更新、`self.levels` 保持 | 変更 |
| `src/shadow_clerk/_daemon_audio.py` | `_capture_pcm_stream` のレベル更新と停滞検知 | 変更 |
| `src/shadow_clerk/_daemon_recorder_monitor.py` | バックエンド経路へのレベル受け渡し | 変更 |
| `src/shadow_clerk/_daemon_log_buffer.py` | `level` SSE イベント | 変更 |
| `src/shadow_clerk/_daemon_dashboard_js_devices.py` | デバイス選択 UI（Task 1 で分割） | 新規 |
| `src/shadow_clerk/_daemon_dashboard_js_core.py` | `level` イベント受信、レベルバー描画 | 変更 |
| `src/shadow_clerk/_daemon_dashboard_html.py` | ヘッダのレベルバー要素 | 変更 |
| `src/shadow_clerk/_daemon_dashboard_css.py` | レベルバーのスタイル | 変更 |
| `src/shadow_clerk/_i18n_ja.py` / `_i18n_en.py` | 新規文言 | 変更 |
| `SPEC.md` | SSE イベント一覧 | 変更 |

---

### Task 1: `_daemon_dashboard_js_panels.py` の分割

**Files:**
- Create: `src/shadow_clerk/_daemon_dashboard_js_devices.py`
- Modify: `src/shadow_clerk/_daemon_dashboard_js_panels.py`
- Modify: `src/shadow_clerk/_daemon_dashboard_js.py`（結合順の確認・必要なら追加）

**Interfaces:**
- Consumes: なし
- Produces: デバイス選択 UI の JS を別モジュールに切り出し、`_daemon_dashboard_js_panels.py` に余裕を作る

**これは純粋な移動である。** 挙動を一切変えないこと。第1段階で実機検証済みの UI なので、ここで壊すと後続タスクの検証が信用できなくなる。

- [ ] **Step 1: 現状を記録する**

Run: `wc -l src/shadow_clerk/_daemon_dashboard_js*.py`
Run: `grep -n "loadAudioDevices\|fillDeviceSelect\|refreshAudioDevices\|device_select" src/shadow_clerk/_daemon_dashboard_js_panels.py`

移動対象を確定する。`CFG_FIELDS` の `device_select` 分岐は設定パネル本体と絡むので、**関数だけを移して分岐は残す**か、まとめて移すかを判断し、報告に理由を書くこと。

- [ ] **Step 2: 移動前の JS を保存する**

Run: `uv run clerk-daemon --dashboard-port 8799` を隔離環境で起動し（Global Constraints の手順）、`curl -s localhost:8799/ > $SCRATCH/dashboard_before.html`
デーモンは PID で kill する。

- [ ] **Step 3: 新モジュールへ移す**

`_daemon_dashboard_js_devices.py` を作り、対象の関数を移す。既存モジュールと同じ形（Python 文字列に JS を入れ、結合される）に従うこと。`_daemon_dashboard_js.py` を読んで、どう結合されているかを確認してから決めること。

- [ ] **Step 4: 出力が完全に一致することを確認する**

Run: 同じ手順で `curl -s localhost:8799/ > $SCRATCH/dashboard_after.html`
Run: `diff <(grep -o "function [a-zA-Z]*" $SCRATCH/dashboard_before.html | sort) <(grep -o "function [a-zA-Z]*" $SCRATCH/dashboard_after.html | sort)`
Expected: 差分なし（同じ関数が同じだけ存在する）

Run: `node --check <(...)` で JS が構文エラーなくパースできること。node が無ければその旨を報告する。

- [ ] **Step 5: 行数とチェック**

Run: `wc -l src/shadow_clerk/_daemon_dashboard_js*.py`
Expected: `_daemon_dashboard_js_panels.py` が 700 行を十分下回る

Run: `uv run python -m py_compile src/shadow_clerk/_daemon_dashboard_js_panels.py src/shadow_clerk/_daemon_dashboard_js_devices.py src/shadow_clerk/_daemon_dashboard_js.py`
Run: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`

- [ ] **Step 6: コミット**

```bash
git add src/shadow_clerk/_daemon_dashboard_js_devices.py src/shadow_clerk/_daemon_dashboard_js_panels.py src/shadow_clerk/_daemon_dashboard_js.py
git commit -m "Split device selection JS out of the panels module"
```

---

### Task 2: `AudioLevel` と `CaptureLevel`

**Files:**
- Create: `src/shadow_clerk/domain/audio_level.py`
- Create: `src/shadow_clerk/_daemon_audio_level.py`
- Modify: `src/shadow_clerk/domain/__init__.py`
- Test: `tests/test_audio_level.py`

**Interfaces:**
- Consumes: なし
- Produces:
  - `AudioLevel(rms: float, peak: float, crest: float)` — frozen dataclass、`domain/audio_level.py`
  - `CaptureLevel` — `add(samples: np.ndarray) -> None` / `snapshot() -> AudioLevel` / `idle_sec() -> float`

**クレストファクタを出す理由:** 2026-08-10 の障害切り分けで決め手になった指標。音声なら 3〜10 以上、定常ノイズなら 1〜2 になり、「デバイスは開けているがノイズしか来ていない」を数値ひとつで判別できる。実測値は内蔵マイク 1.3 / Shokz 49.4 だった。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_audio_level.py`:

```python
"""AudioLevel / CaptureLevel の検証

実行: uv run python tests/test_audio_level.py
音声デバイスを必要としない（合成波形のみ）。
"""
from __future__ import annotations
import math
import time

import numpy as np

from shadow_clerk._daemon_audio_level import CaptureLevel
from shadow_clerk.domain import AudioLevel

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def measure(samples: np.ndarray) -> AudioLevel:
    lv = CaptureLevel()
    lv.add(samples)
    return lv.snapshot()


n = 16000
t = np.arange(n) / 16000.0

# 無音: rms も peak も 0、crest は 0 除算を避けて 0
silence = measure(np.zeros(n, dtype=np.int16))
check("1. 無音の rms=0", silence.rms == 0.0, f"{silence.rms}")
check("2. 無音の crest=0 (0除算しない)", silence.crest == 0.0, f"{silence.crest}")

# 正弦波: crest = peak/rms = √2 ≒ 1.41
sine = measure((10000 * np.sin(2 * math.pi * 440 * t)).astype(np.int16))
check("3. 正弦波の crest ≒ 1.41", 1.30 < sine.crest < 1.55, f"{sine.crest:.2f}")

# 定常ノイズ: crest は 1〜2 の低い値に収まる（今回の障害の内蔵マイク相当）
rng = np.random.default_rng(12345)
noise = measure(rng.normal(0, 2000, n).astype(np.int16))
check("4. 定常ノイズの crest < 5", noise.crest < 5.0, f"{noise.crest:.2f}")

# バースト（音声相当）: 大半が無音で一部だけ大きい → crest が高い
burst = np.zeros(n, dtype=np.int16)
burst[:800] = 15000
check("5. バーストの crest > 3", measure(burst).crest > 3.0, f"{measure(burst).crest:.2f}")

# snapshot は窓をリセットする
lv = CaptureLevel()
lv.add(np.full(1000, 5000, dtype=np.int16))
first = lv.snapshot()
second = lv.snapshot()
check("6. snapshot で窓がリセットされる", first.rms > 0 and second.rms == 0.0,
      f"1回目={first.rms:.0f} 2回目={second.rms:.0f}")

# idle_sec は add からの経過を返す
lv2 = CaptureLevel()
lv2.add(np.zeros(10, dtype=np.int16))
time.sleep(0.2)
check("7. idle_sec が経過を返す", 0.15 < lv2.idle_sec() < 1.0, f"{lv2.idle_sec():.2f}")

# AudioLevel は不変
try:
    AudioLevel(rms=1.0, peak=2.0, crest=2.0).rms = 9.0  # type: ignore[misc]
    check("8. AudioLevel は不変", False, "代入できてしまった")
except Exception:
    check("8. AudioLevel は不変", True)

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run python tests/test_audio_level.py`
Expected: FAIL（`ModuleNotFoundError: shadow_clerk._daemon_audio_level`）

- [ ] **Step 3: `AudioLevel` を作る**

`src/shadow_clerk/domain/audio_level.py`:

```python
"""shadow-clerk: 音声レベル（バリューオブジェクト）"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioLevel:
    """直近 1 秒の入力レベル。

    crest（クレストファクタ = peak / rms）は「デバイスは開けているがノイズしか
    来ていない」状態の判別に使う。音声なら 3〜10 以上、定常ノイズなら 1〜2。
    rms が微小なときは 0 とする（無音で発散させないため）。
    """

    rms: float
    peak: float
    crest: float
```

`domain/__init__.py` の import と `__all__` に `AudioLevel` を追加する（既存の `AudioDevice` の並びに合わせる）。

- [ ] **Step 4: `CaptureLevel` を作る**

`src/shadow_clerk/_daemon_audio_level.py`:

```python
"""shadow-clerk daemon: 入力レベルの集計"""
from __future__ import annotations

import time

import numpy as np

from shadow_clerk.domain import AudioLevel

# rms がこの値未満なら実質無音とみなし、crest を 0 にする（0 除算回避）
_SILENCE_RMS = 1.0


class CaptureLevel:
    """1 秒窓の入力レベルを集計する。

    音声コールバック（毎秒約33回）から `add()` され、配信スレッドから
    `snapshot()` される。GIL 下の単純な数値更新のみで、ロックは持たない
    ——取りこぼしても次の窓で回復するため、厳密さより軽さを優先する。
    """

    def __init__(self) -> None:
        self._sum_sq = 0.0
        self._count = 0
        self._peak = 0.0
        self._last_add = time.monotonic()

    def add(self, samples: np.ndarray) -> None:
        """フレームを取り込む。音声コールバック内から呼ばれる。"""
        data = samples.astype(np.float32)
        self._sum_sq += float(np.dot(data, data))
        self._count += len(data)
        self._peak = max(self._peak, float(np.abs(data).max(initial=0.0)))
        self._last_add = time.monotonic()

    def idle_sec(self) -> float:
        """最後に add されてからの経過秒数。

        CLOCK_MONOTONIC はサスペンド中進まないため、レジューム直後に
        サスペンド時間で誤検知することはない。
        """
        return time.monotonic() - self._last_add

    def snapshot(self) -> AudioLevel:
        """直近の窓を返して窓をリセットする。"""
        count, sum_sq, peak = self._count, self._sum_sq, self._peak
        self._count, self._sum_sq, self._peak = 0, 0.0, 0.0
        if not count:
            return AudioLevel(rms=0.0, peak=0.0, crest=0.0)
        rms = (sum_sq / count) ** 0.5
        crest = peak / rms if rms >= _SILENCE_RMS else 0.0
        return AudioLevel(rms=rms, peak=peak, crest=crest)
```

- [ ] **Step 5: テストを通す**

Run: `uv run python tests/test_audio_level.py`
Expected: `=== 8/8 PASS ===`

- [ ] **Step 6: チェックとコミット**

Run: `uv run python -m py_compile src/shadow_clerk/_daemon_audio_level.py src/shadow_clerk/domain/audio_level.py`
Run: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`

```bash
git add src/shadow_clerk/domain/audio_level.py src/shadow_clerk/domain/__init__.py src/shadow_clerk/_daemon_audio_level.py tests/test_audio_level.py
git commit -m "Add AudioLevel value object and CaptureLevel accumulator"
```

---

### Task 3: 両経路からのレベル更新

**Files:**
- Modify: `src/shadow_clerk/_daemon_recorder_capture.py`（`__init__` に `self.levels`、`_CaptureStream` に受け渡し）
- Modify: `src/shadow_clerk/_daemon_audio.py`（`_capture_pcm_stream` にレベル引数）
- Modify: `src/shadow_clerk/_daemon_recorder_monitor.py`（バックエンドへ受け渡し）
- Test: `tests/test_audio_level.py` に追記

**Interfaces:**
- Consumes: Task 2 の `CaptureLevel`
- Produces: `_RecorderCaptureMixin.levels: dict[str, CaptureLevel]` — `"mic"` と `"monitor"` のキーを持つ。**両方の経路**が同じオブジェクトを更新する

**なぜ recorder が持つか:** `_CaptureStream` は監視スレッドのローカル変数で、配信する `FileWatcher` から到達できない。初版の設計はここを見落として実装不能だった。

- [ ] **Step 1: 失敗するテストを追記する**

`tests/test_audio_level.py` の `print(f"\n=== ...")` の直前に追加:

```python
# --- recorder が両ラベルの CaptureLevel を持つ ---
import argparse
import queue as _queue
import threading as _threading

from shadow_clerk import _daemon_recorder_capture as cap


class _Host(cap._RecorderCaptureMixin):
    def __init__(self) -> None:  # pylint: disable=super-init-not-called
        self.levels = {"mic": CaptureLevel(), "monitor": CaptureLevel()}


check("9. levels に mic と monitor がある",
      set(_Host().levels) == {"mic", "monitor"})

# --- _CaptureStream のコールバックが level を更新する ---
dev = __import__("shadow_clerk.domain", fromlist=["AudioDevice"]).AudioDevice(index=0, name="x")
lv = CaptureLevel()
st = cap._CaptureStream("mic", dev, _queue.Queue(), level=lv)
st._callback(np.full((480, 1), 3000, dtype=np.int16), 480, None, None)
snap = lv.snapshot()
check("10. コールバックが level を更新する", snap.rms > 0, f"rms={snap.rms:.0f}")
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run python tests/test_audio_level.py`
Expected: FAIL（`_CaptureStream` が `level` 引数を受け取らない）

- [ ] **Step 3: `_CaptureStream` にレベルを通す**

`_CaptureStream.__init__` に `level: CaptureLevel | None = None` を追加し、`self.level = level` を保持する。`_callback` の先頭付近、キューに入れる前に更新する:

```python
    def _callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            logger.warning("%s status: %s", self.label, status)
        self.last_frame = time.monotonic()
        mono = indata[:, 0].copy().astype(np.int16)
        if self.level is not None:
            self.level.add(mono)
        self._queue.put(mono)
```

（既存の `indata[:, 0].copy().astype(np.int16)` を 1 回だけ計算するよう変数に取ること。コールバックは毎秒33回走る）

- [ ] **Step 4: `__init__` と `_open_capture` を繋ぐ**

`_RecorderCaptureMixin.__init__` の `self._device_snapshot` の並びに追加:

```python
        # 入力レベル。sounddevice 経路とバックエンド経路の両方が更新する
        self.levels: dict[str, CaptureLevel] = {
            "mic": CaptureLevel(), "monitor": CaptureLevel()}
```

`_open_capture` が `_CaptureStream` を作るところで `level=self.levels[label]` を渡す。

- [ ] **Step 5: バックエンド経路にも通す**

`_capture_pcm_stream` に `level: CaptureLevel | None = None` を追加し、`audio_queue.put(samples)` の直前で `level.add(samples)` する。`PipeWireBackend.start_monitor_capture` / `PulseAudioBackend.start_monitor_capture` / `WasapiBackend.start_monitor_capture` のシグネチャにも `level` を通す（`AudioBackend` 基底クラスの宣言も更新すること。Stage 1 で `start_monitor_capture` を基底に宣言済み）。

`_daemon_recorder_monitor.py` の `_capture_monitor_backend_once` が `backend.start_monitor_capture(...)` を呼ぶところで `self.levels["monitor"]` を渡す。

- [ ] **Step 6: テストを通す**

Run: `uv run python tests/test_audio_level.py`
Expected: `=== 10/10 PASS ===`

- [ ] **Step 7: 実機でレベルが動くことを確認する**

隔離デーモンで（Global Constraints の手順）、`python` から直接ではなく実際のキャプチャで確認する。次のスクリプトを `$SCRATCH/probe_level.py` として実行する:

```python
from __future__ import annotations
import argparse, queue, threading, time
from shadow_clerk import _daemon_recorder_capture as cap
from shadow_clerk._daemon_audio import detect_backend
from shadow_clerk._daemon_audio_level import CaptureLevel

class Host(cap._RecorderCaptureMixin):
    def __init__(self):  # pylint: disable=super-init-not-called
        self.args = argparse.Namespace(mic=None, monitor=None)
        self.stop_event = threading.Event()
        self.mic_queue, self.monitor_queue = queue.Queue(), queue.Queue()
        self.backend_name, self.backend = detect_backend("auto")
        self.use_mic = self.use_monitor = False
        self._pinned_names, self._monitor_backend = {}, None
        self._manual_device_refresh = False
        self._device_snapshot = {"mic": [], "monitor": [], "updated_at": None}
        self._return_backoff, self._monitor_restart = {}, threading.Event()
        self._monitor_backend_requested = None
        self.levels = {"mic": CaptureLevel(), "monitor": CaptureLevel()}

h = Host()
threading.Thread(target=h._audio_capture_thread, daemon=True).start()
try:
    for _ in range(6):
        time.sleep(1)
        for label in ("mic", "monitor"):
            s = h.levels[label].snapshot()
            print(f"{label:8s} rms={s.rms:8.1f} peak={s.peak:8.0f} crest={s.crest:6.1f}")
        print("---")
finally:
    h.stop_event.set(); time.sleep(1)
```

Run: `uv run python $SCRATCH/probe_level.py`
Expected: mic の rms が 0 でない値を出す。話しかけると crest が 3 以上に跳ねる。実際の出力を報告に貼ること。

- [ ] **Step 8: 回帰ゲートとコミット**

Run: `uv run python tests/test_audio_capture_watchdog.py`
Expected: `=== 8/8 PASS ===`

Run: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`

```bash
git add src/shadow_clerk/_daemon_recorder_capture.py src/shadow_clerk/_daemon_audio.py src/shadow_clerk/_daemon_recorder_monitor.py tests/test_audio_level.py
git commit -m "Feed capture levels from both the PortAudio and subprocess paths"
```

---

### Task 4: バックエンド経路の停滞検知

**Files:**
- Modify: `src/shadow_clerk/_daemon_audio.py`（`_capture_pcm_stream`）
- Test: `tests/test_backend_stall.py`

**Interfaces:**
- Consumes: Task 3 の `level` 引数
- Produces: `_capture_pcm_stream` が `STREAM_STALL_SEC` を超えてフレームを受け取れなければ戻る

**問題:** 現状 `proc.stdout.read(FRAME_SIZE * 2)` はブロックし続ける。pw-record が生きたままフレームを出さなくなると永久に戻らず、`_monitor_backend_thread` のループも回らないので、モニターが無言で死んだままになる。第1段階で sounddevice 経路にだけ入れた停滞検知を、この経路にも与える。

**実装上の注意:** `select` が読み出し可能を報告してから `read(n)` を呼ぶと、n バイト未満しか届いていない場合にそこでブロックしうる。`os.read` で届いた分だけ読み、フレーム境界は呼び出し側でバッファリングして管理する。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_backend_stall.py`:

```python
"""バックエンド経路（pw-record/parec）の停滞検知の検証

実行: uv run python tests/test_backend_stall.py
実デバイス不要。フレームを出さない偽コマンドで停滞を模擬する。
"""
from __future__ import annotations
import queue
import sys
import threading
import time

from shadow_clerk import _daemon_audio as audio
from shadow_clerk._daemon_constants import FRAME_SIZE

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


# 停滞判定を短くして待ち時間を抑える
_orig_stall = audio.STREAM_STALL_SEC
audio.STREAM_STALL_SEC = 1.0
try:
    # --- 1. フレームを一切出さないプロセスからは STALL 後に戻る ---
    q: queue.Queue = queue.Queue()
    stop = threading.Event()
    t0 = time.monotonic()
    audio._capture_pcm_stream(
        [sys.executable, "-c", "import time; time.sleep(30)"], "test", q, stop)
    elapsed = time.monotonic() - t0
    check("1. 無音のまま停滞したら戻る", 1.0 <= elapsed < 5.0, f"{elapsed:.1f}秒で戻った")
    check("2. フレームは流れていない", q.empty(), f"{q.qsize()}件")

    # --- 3. フレームを出し続ける間は戻らない ---
    q2: queue.Queue = queue.Queue()
    stop2 = threading.Event()
    producer = (
        "import sys,time\n"
        f"buf = b'\\x01\\x00' * {FRAME_SIZE}\n"
        "for _ in range(30):\n"
        "    sys.stdout.buffer.write(buf); sys.stdout.buffer.flush(); time.sleep(0.05)\n"
    )
    th = threading.Thread(
        target=audio._capture_pcm_stream,
        args=([sys.executable, "-c", producer], "test", q2, stop2), daemon=True)
    th.start()
    time.sleep(1.5)
    alive_while_flowing = th.is_alive()
    got = q2.qsize()
    stop2.set()
    th.join(timeout=5)
    check("3. フレームが流れている間は戻らない", alive_while_flowing)
    check("4. フレームがキューに入る", got > 5, f"{got}件")
    check("5. stop_event で終了する", not th.is_alive())
finally:
    audio.STREAM_STALL_SEC = _orig_stall

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run python tests/test_backend_stall.py`
Expected: FAIL（チェック 1 がタイムアウトせず、テストが 30 秒ハングしてから失敗する）

- [ ] **Step 3: `_capture_pcm_stream` を停滞検知つきに書き換える**

`_daemon_audio.py` の import に `import os` と `import select` を追加し、`STREAM_STALL_SEC` を `_daemon_constants` から import する。読み出しループを次で置き換える:

```python
    frame_bytes = FRAME_SIZE * 2
    buf = bytearray()
    try:
        while not stop_event.is_set():
            # select で待つのは、フレームが来なくなった pw-record が
            # read() で永久にブロックするのを防ぐため。無音の sink でも
            # 正常なら毎秒約33フレーム届くので、途絶は死亡を意味する
            ready, _, _ = select.select([proc.stdout], [], [], STREAM_STALL_SEC)
            if not ready:
                logger.warning("%s: %.0f 秒フレームが途絶。キャプチャを再開します",
                               name, STREAM_STALL_SEC)
                break
            chunk = os.read(proc.stdout.fileno(), frame_bytes)
            if not chunk:
                break
            buf.extend(chunk)
            while len(buf) >= frame_bytes:
                samples = np.frombuffer(bytes(buf[:frame_bytes]), dtype=np.int16)
                del buf[:frame_bytes]
                if level is not None:
                    level.add(samples)
                audio_queue.put(samples)
    finally:
```

`select` は Windows ではソケットにしか使えない。`sys.platform == "win32"` の場合は従来のブロッキング読み出しに落とすこと（WasapiBackend は `_capture_pcm_stream` を使わないので実害は無いはずだが、確認して報告すること）。

- [ ] **Step 4: テストを通す**

Run: `uv run python tests/test_backend_stall.py`
Expected: `=== 5/5 PASS ===`

- [ ] **Step 5: 実機でバックエンド経路が動くことを確認する**

pw-record 経路が実際に音を拾えることを確認する。`$SCRATCH/probe_backend.py`:

```python
from __future__ import annotations
import queue, threading, time
from shadow_clerk._daemon_audio import PipeWireBackend
from shadow_clerk._daemon_audio_level import CaptureLevel

q: queue.Queue = queue.Queue()
stop = threading.Event()
lv = CaptureLevel()
be = PipeWireBackend()
src = be.detect_monitor_source()
print("target:", src)
th = threading.Thread(target=be.start_monitor_capture, args=(src, q, stop, lv), daemon=True)
th.start()
for _ in range(5):
    time.sleep(1)
    s = lv.snapshot()
    print(f"frames={q.qsize():5d} rms={s.rms:8.1f} crest={s.crest:6.1f}")
stop.set(); th.join(timeout=5)
print("終了:", not th.is_alive())
```

Run: `uv run python $SCRATCH/probe_backend.py`
Expected: フレーム数が増え、スレッドが停止する。**`pw-link -l` で接続先が意図した sink の `monitor_FL`/`monitor_FR` であることも確認すること**（終了コードは証拠にならない）。実際の出力を報告に貼る。

- [ ] **Step 6: 回帰ゲートとコミット**

Run: `uv run python tests/test_audio_capture_watchdog.py`
Expected: `=== 8/8 PASS ===`

```bash
git add src/shadow_clerk/_daemon_audio.py tests/test_backend_stall.py
git commit -m "Detect stalled frames on the pw-record/parec capture path"
```

---

### Task 5: `level` SSE イベントの配信

**Files:**
- Modify: `src/shadow_clerk/_daemon_log_buffer.py`（`FileWatcher._poll`）
- Test: `tests/test_level_event.py`

**Interfaces:**
- Consumes: Task 3 の `recorder.levels`
- Produces: 1 秒ごとの `level` SSE イベント

ペイロード:

```json
{"mic": {"rms": 34.3, "peak": 1799, "crest": 52.4,
         "device": "alsa_input.usb-Shokz_...", "requested": null, "fallback": false},
 "monitor": null}
```

- `device`: 実際に開いているデバイス名。開けていなければ系統ごと `null`
- `requested`: 設定で指定された名前（未指定なら `null`）
- `fallback`: 指定があるのに別のデバイスで代替中なら `true`

**`/api/status` を使わない理由:** ブラウザ側のポーリングは 10 秒間隔（`_daemon_dashboard_js_panels.py`）でメーターには遅すぎる。`FileWatcher.run()` は既に 1 秒周期で回って SSE を配信しているので、そこに相乗りする。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_level_event.py`:

```python
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
```

- [ ] **Step 2: 失敗を確認する**

Run: `uv run python tests/test_level_event.py`
Expected: FAIL（`FileWatcher` に `_poll_levels` が無い、`recorder.open_streams` が無い）

- [ ] **Step 3: 開いているストリームを recorder から見えるようにする**

`_daemon_recorder_capture.py` の `_audio_capture_thread` はストリームを `dict[str, _CaptureStream]` のローカル変数 `streams` で持っている。`FileWatcher` から `device` / `requested` を読めるよう、recorder の属性としても公開する。

`__init__` に追加:

```python
        # 現在開いているキャプチャストリーム。FileWatcher がレベル配信時に
        # デバイス名とフォールバック状態を読む
        self.open_streams: dict[str, _CaptureStream] = {}
```

`_audio_capture_thread` のローカル `streams` を `self.open_streams` に置き換える（別の dict を作らないこと。二重管理は必ずずれる）。`finally` でのクリアも忘れないこと。

**この関数は最も安全性が要求される箇所である。** `refresh_device_list()` は開いている全 PortAudio ストリームを破棄するため、`streams.clear()` してからでないと呼べない。ローカル変数を属性に替えるだけの機械的な置換に留め、制御フローを触らないこと。

**`tests/test_audio_capture_watchdog.py` の `Host` にも `open_streams` を足すこと。** この Host は `Recorder.__init__` を通さず属性を手で用意しているため、足し忘れると監視ループが AttributeError を起こす。テスト側の検出器がそれを報告するので気付けるが、Step 7 の回帰ゲートで初めて落ちるより先に直しておくのが早い。

- [ ] **Step 4: `_poll_levels` を実装する**

`_daemon_log_buffer.py` の `FileWatcher` に追加し、`_poll()` の末尾から呼ぶ:

```python
    def _poll_levels(self) -> None:
        """入力レベルを 1 秒ごとに配信する"""
        levels = getattr(self._recorder, "levels", None)
        if not levels:
            return
        streams = getattr(self._recorder, "open_streams", {})
        payload: dict[str, dict | None] = {}
        for label, level in levels.items():
            snap = level.snapshot()
            stream = streams.get(label)
            if stream is None:
                payload[label] = None
                continue
            requested = stream.requested
            payload[label] = {
                "rms": round(snap.rms, 1),
                "peak": round(snap.peak),
                "crest": round(snap.crest, 1),
                "device": stream.device.name,
                "requested": requested,
                "fallback": bool(requested) and stream.device.name != requested,
            }
        self._broadcast("level", json.dumps(payload, ensure_ascii=False))
```

- [ ] **Step 5: テストを通す**

Run: `uv run python tests/test_level_event.py`
Expected: `=== 8/8 PASS ===`

- [ ] **Step 6: 実機で SSE に流れることを確認する**

隔離デーモンを起動し、SSE を数秒購読する:

Run: `curl -s -N -m 5 localhost:8799/api/events | grep -A1 "^event: level" | head -6`
Expected: `level` イベントと mic の rms を含む JSON が毎秒流れる。実際の出力を報告に貼る。

- [ ] **Step 7: 回帰ゲートとコミット**

Run: `uv run python tests/test_audio_capture_watchdog.py`
Expected: `=== 8/8 PASS ===`

```bash
git add src/shadow_clerk/_daemon_log_buffer.py src/shadow_clerk/_daemon_recorder_capture.py tests/test_level_event.py
git commit -m "Broadcast capture levels as a level SSE event"
```

---

### Task 6: ヘッダのレベル表示

**Files:**
- Modify: `src/shadow_clerk/_daemon_dashboard_html.py`
- Modify: `src/shadow_clerk/_daemon_dashboard_css.py`
- Modify: `src/shadow_clerk/_daemon_dashboard_js_core.py`
- Modify: `src/shadow_clerk/_i18n_ja.py` / `_i18n_en.py`

**Interfaces:**
- Consumes: Task 5 の `level` SSE イベント
- Produces: ヘッダのレベルバー 2 本

**ミュートボタンとは別の要素にすること。** `updateMuteBtn`（`_daemon_dashboard_js_core.py`）が 10 秒ごとにボタンの `title` と class を無条件に書き直すため、同じ要素に 1Hz で書き込むと奪い合いになる。所有権を分ける。

**2 種類の警告を出す。** どちらも判定はブラウザ側で行い、サーバは生の値だけを送る。

1. **定常ノイズ**: 直近 10 回（= 10 秒）の `level` がすべて「`rms >= 100` かつ `crest < 2`」。`rms` の下限を課すのは、無音時に `crest` が 0 になって誤検知するのを防ぐため。この機の内蔵 Digital Microphone（常時 RMS 約2760・crest 1.3）がこれに当たる。
2. **完全無音**: 直近 30 回（= 30 秒）の `level` がすべて `rms === 0 && peak === 0`。

**なぜ完全無音を別扱いするか。** 生きたマイクは静かな部屋でも必ずノイズフロアを持つ（RMS 数〜数十）。厳密にゼロが続くのは「デバイスは開けているが音が届いていない」状態——電源オフのヘッドセット、切断されたドングル、権限を失ったストリーム——を意味する。2026-08-11 に Shokz の電源が入っておらず、48000 サンプルすべてがゼロという状態が実際に起きている。定常ノイズ判定は `rms >= 100` を要求するのでこれを捕まえられない。

窓を 30 秒と長くとるのは、会議中に全員が黙っている時間との誤検知を避けるため。ただし**生きたマイクなら黙っていてもノイズフロアで `rms > 0` になる**ので、厳密なゼロ判定であれば 30 秒は十分に安全側である。

**`peak` も併せて見ること。** `rms` は小数第1位に丸めて配信されるため、16kHz で毎秒 39 サンプルまでの微小信号（±1 LSB 等）は `0.0` に丸められる。ノイズ抑制ゲートの後段など、動いているのに極小の入力を「音が届いていない」と誤判定しうる。`peak` は整数に丸めた最大絶対値なので、デジタル無音の厳密な判別子になる（実測: `rms` が `0.0` に丸まる全ケースで `peak` は 1 以上だった）。

- [ ] **Step 0a: バックエンド経路の表示名を用意する**

Task 5 で追加した `backend_source["monitor"]` には、`pw-record --target` に渡す文字列がそのまま入っている。PipeWire では**数値の `object.serial`（例 `"80"`）**であり、tooltip にそのまま出すとユーザーには無意味である。

読める名前は書き込み地点で既に手元にある。`_daemon_recorder_monitor.py` の `_monitor_target` は、指定デバイス経路では `requested.removesuffix(".monitor")` を serial に変換する直前に sink 名を持っており、自動検出経路では既存の `get_default_sink_name()` が使える。

`backend_source` に**表示名を入れる**よう変更すること（`pw-record` に渡す値は従来どおり serial のまま）。名前が取れなかった場合のみ元の文字列にフォールバックし、その旨をログに残す。`tests/test_level_event.py` に、バックエンド経路の `device` が数字だけの文字列にならないことを確かめるチェックを足すこと。

- [ ] **Step 0: 既存のヘッダ構造を読む**

Run: `grep -n "btnMuteMic" src/shadow_clerk/_daemon_dashboard_html.py`
Run: `grep -n "updateMuteBtn" src/shadow_clerk/_daemon_dashboard_js_core.py`
Run: `grep -n "\.toggle\|\.ph " src/shadow_clerk/_daemon_dashboard_css.py | head`

ミュートボタンがどの要素の中にあり、周囲がどんな class を使っているかを確認する。以降のマークアップは**ここで見た実際の構造に合わせる**こと。

- [ ] **Step 1: i18n キーを追加する**

`_i18n_ja.py`:

```python
    "dash.level_mic": "マイク入力レベル",
    "dash.level_monitor": "スピーカー入力レベル",
    "dash.level_noise": "定常ノイズのみ検出（デバイスを確認してください）",
    "dash.level_silent": "音が届いていません（デバイスの電源・接続を確認してください）",
    "dash.level_fallback": "指定デバイスが見つからないため自動で代替中",
```

`_i18n_en.py`:

```python
    "dash.level_mic": "Mic input level",
    "dash.level_monitor": "Speaker input level",
    "dash.level_noise": "Only steady noise detected (check the device)",
    "dash.level_silent": "No audio arriving (check the device is on and connected)",
    "dash.level_fallback": "Chosen device not found; using the automatic one",
```

- [ ] **Step 2: マークアップと CSS を追加する**

ヘッダの該当箇所は `_daemon_dashboard_html.py` の 1 行の長い Python 文字列で、引用符が `\"` でエスケープされている。現状はこうなっている:

```
<button class="toggle" id="btnMuteMic" onclick="togMute('mic')" title="{{i18n:dash.mute_mic}}">🎤</button>
<button class="toggle" id="btnMuteMonitor" onclick="togMute('monitor')" title="{{i18n:dash.mute_monitor}}">🔊</button>
```

各ミュートボタンの**直後**にバーを挿す（エスケープを合わせること）:

```
<span class="lv" id="lv_mic"><i></i></span>
<span class="lv" id="lv_monitor"><i></i></span>
```

`_daemon_dashboard_css.py` に追加する。配色は既存の変数を使う（`--border` / `--green` / `--yellow` / `--accent` が定義済み）:

```css
.lv{display:inline-block;width:34px;height:6px;border:1px solid var(--border);
    border-radius:3px;overflow:hidden;vertical-align:middle;margin:0 4px 0 1px}
.lv i{display:block;height:100%;width:0;background:var(--green);
      transition:width .25s linear}
.lv.lv-warn i{background:var(--yellow)}
.lv.lv-fallback{border-color:var(--yellow)}
```

`<i>` を中身のバーに使うのは、既存のヘッダが `<span>` を多用していて追加の class を増やしたくないため。意味を持たせない純粋な表示要素である。

- [ ] **Step 3: `level` イベントを受けて描画する**

`_daemon_dashboard_js_core.py` の既存 `es.addEventListener(...)` の並びに追加する:

```javascript
const LV_NOISE = {mic: [], monitor: []};
const LV_SILENT = {mic: [], monitor: []};
es.addEventListener('level', e => {
  const d = JSON.parse(e.data);
  for (const label of ['mic', 'monitor']) updateLevel(label, d[label]);
});
function updateLevel(label, v){
  const bar = document.getElementById('lv_' + label);
  if(!bar) return;
  const fill = bar.firstElementChild;
  if(!v){ fill.style.width = '0%'; bar.className = 'lv'; bar.title = ''; return; }
  // 対数スケール: 十分な入力で満杯、無音で 0 になるよう圧縮する
  const pct = v.rms <= 1 ? 0 : Math.min(100, Math.max(0, 20 * Math.log10(v.rms) - 10));
  fill.style.width = pct.toFixed(0) + '%';
  // 定常ノイズ: 10秒すべてが「音量はあるが crest が低い」
  const noiseHist = LV_NOISE[label];
  noiseHist.push(v.rms >= 100 && v.crest < 2);
  if(noiseHist.length > 10) noiseHist.shift();
  const noisy = noiseHist.length === 10 && noiseHist.every(Boolean);
  // 完全無音: 30秒すべてが厳密にゼロ。生きたマイクはノイズフロアを持つので
  // 黙っているだけならゼロにはならない
  const silHist = LV_SILENT[label];
  silHist.push(v.rms === 0 && v.peak === 0);
  if(silHist.length > 30) silHist.shift();
  const silent = silHist.length === 30 && silHist.every(Boolean);
  bar.className = 'lv' + (v.fallback ? ' lv-fallback' : '')
                + (noisy || silent ? ' lv-warn' : '');
  bar.title = (noisy ? I18N['dash.level_noise'] + ' ' : '')
            + (silent ? I18N['dash.level_silent'] + ' ' : '')
            + (v.fallback ? I18N['dash.level_fallback'] + ': ' + v.requested + ' ' : '')
            + (label === 'mic' ? I18N['dash.level_mic'] : I18N['dash.level_monitor']);
}
```

- [ ] **Step 4: 実機で確認する**

隔離デーモンを起動し（Global Constraints の手順）、ブラウザで `http://localhost:8799` を開く。

1. マイクのバーが話すと動き、黙ると縮む
2. 相手側の音を鳴らすとスピーカーのバーが動く
3. 設定パネルで存在しないデバイス名を保存すると、代替中の表示が出る（`curl` で `mic_device` に架空の名前を POST するのが早い）
4. `{{i18n:` がページに残っていない: `curl -s localhost:8799/ | grep -c "{{i18n:"` → 0
5. JS が構文エラーなくパースできる（`node --check`。node が無ければその旨を報告）

**定常ノイズ警告の確認**: この機の内蔵 Digital Microphone は常時 RMS 約2760・クレストファクタ 1.3 のハムを出す。`mic_device` にそれを指定すれば警告条件を実地で再現できる（`wpctl status --name` の `alsa_input.pci-...Mic1__source`）。10 秒後にバーが警告色になることを確認し、確認後は `null` に戻すこと。

実際の確認内容と、可能ならスクリーンショットまたは `curl` 出力を報告に貼る。

- [ ] **Step 5: チェックとコミット**

Run: `uv run python -m py_compile src/shadow_clerk/_daemon_dashboard_html.py src/shadow_clerk/_daemon_dashboard_css.py src/shadow_clerk/_daemon_dashboard_js_core.py src/shadow_clerk/_i18n_ja.py src/shadow_clerk/_i18n_en.py`
Run: `wc -l src/shadow_clerk/_daemon_dashboard_js_core.py`（700 行以内）
Run: `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/`

```bash
git add src/shadow_clerk/_daemon_dashboard_html.py src/shadow_clerk/_daemon_dashboard_css.py src/shadow_clerk/_daemon_dashboard_js_core.py src/shadow_clerk/_i18n_ja.py src/shadow_clerk/_i18n_en.py
git commit -m "Show input level bars with steady-noise and fallback warnings"
```

---

### Task 7: ドキュメント更新

**Files:**
- Modify: `SPEC.md`（SSE イベント一覧、スレッド構成の記述）
- Modify: `README.md` / `README.ja.md`（レベル表示の説明）

**Interfaces:**
- Consumes: Task 5 の `level` イベント
- Produces: なし

- [ ] **Step 1: 該当箇所を特定する**

Run: `grep -n "recorder_status\|interim_clear" SPEC.md | head`
Run: `grep -n "ダッシュボード\|Dashboard" README.md README.ja.md | head`

- [ ] **Step 2: SPEC.md の SSE イベント一覧に追記する**

既存の並びに合わせて `level` を追加する。1 秒周期であること、系統ごとに `null` になりうること、`crest` が定常ノイズ判別のための指標であることを書く。

- [ ] **Step 3: README にレベル表示を説明する**

ヘッダのバーが何を示すか、警告色が何を意味するか（定常ノイズのみ／指定デバイスの代替中）を、それぞれの言語で自然に書く。長くしないこと。

- [ ] **Step 4: 食い違いがないか確認する**

Run: `grep -n "level" SPEC.md | head`
Run: `git diff --stat`（`src/` が変更されていないこと）

- [ ] **Step 5: コミット**

```bash
git add SPEC.md README.md README.ja.md
git commit -m "Document the level SSE event and the dashboard level bars"
```

---

## 完了条件

1. Task 1〜7 の全ステップにチェックが入っている
2. `uv run python tests/test_audio_capture_watchdog.py` が 8/8 PASS
3. `uv run python tests/test_audio_level.py` が 10/10 PASS
4. `uv run python tests/test_backend_stall.py` が 5/5 PASS
5. `uv run python tests/test_level_event.py` が 8/8 PASS
6. `uv run --with pylint python -m pylint --disable=all --enable=R0801 src/shadow_clerk/` が 10.00/10
7. mypy のエラー数が 101 以下
8. 全ファイルが 700 行以内
9. 実機のダッシュボードでレベルバーが動き、定常ノイズ警告が出ることを確認済み
