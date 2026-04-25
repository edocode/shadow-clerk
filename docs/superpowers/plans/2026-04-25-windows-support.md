# Windows Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Windows support to shadow-clerk by branching only the platform-specific bits (data directory, WASAPI loopback monitor capture, process stop), keeping the existing Linux PipeWire/PulseAudio path untouched.

**Architecture:** Thin `sys.platform == "win32"` branches in 3 narrow points (`get_data_dir`, `find_monitor_device_sd`, `clerk-util stop`). Mic capture, PTT (pynput), audio backend abstraction, and signal registration are already cross-platform-friendly. Linux behavior is preserved bit-for-bit.

**Tech Stack:** Python 3.11+, `sounddevice` (PortAudio with WASAPI host on Windows), `pynput` (cross-platform PTT), no new third-party dependencies.

**Verification model:** This repo has no automated test suite. Each task ends in:
1. `uv run python -m py_compile <file>` to confirm syntax,
2. A Linux smoke check that exercises the changed code path on the developer's own machine,
3. A documented Windows verification step (deferred to the requester or whoever has Windows).

**Project conventions reminder (from `CLAUDE.md`):**
- All Python under `src/shadow_clerk/`
- Use `uv run python …` (never bare `python3`)
- Type hints mandatory; `from __future__ import annotations` at top of every file
- Max 700 lines per file (relevant: see Task 1 note about `i18n.py`)
- Logger-based logging (no `print` outside CLI output)
- Commit messages in English, concise

---

## File map

| File | Change |
|------|--------|
| `src/shadow_clerk/__init__.py` | Modify `get_data_dir()` to branch on `sys.platform` |
| `src/shadow_clerk/_daemon_audio.py` | Modify `find_monitor_device_sd()` signature + add Windows WASAPI lookup helper |
| `src/shadow_clerk/_daemon_recorder_capture.py` | Plumb extra kwargs from `find_monitor_device_sd()` into `sd.InputStream(...)` |
| `src/shadow_clerk/clerk_util.py` | Add Windows branch in `cmd_stop` and `_is_pid_alive` |
| `pyproject.toml` | Make `evdev` Linux-only via PEP 508 marker |
| `README.md` / `README.ja.md` | Add Windows setup section |
| `improvement/cross-platform.md` | Update line refs and mark Windows phase implemented |

No new files. All changes additive or local-branch.

---

## Task 1: Platform-aware `get_data_dir()`

**Files:**
- Modify: `src/shadow_clerk/__init__.py:1-27`

- [ ] **Step 1.1: Inspect current state**

Run: `cat src/shadow_clerk/__init__.py`

Confirm it matches the snapshot in the spec (`get_data_dir()` returns `~/.local/share/shadow-clerk` with `SHADOW_CLERK_DATA_DIR` override).

- [ ] **Step 1.2: Edit `get_data_dir()`**

Replace the entire function body with:

```python
def get_data_dir() -> str:
    """データディレクトリのパスを返す。

    SHADOW_CLERK_DATA_DIR 環境変数で上書き可能。
    デフォルト:
      - Windows: %APPDATA%\\shadow-clerk
      - Linux/その他: ~/.local/share/shadow-clerk
    """
    if env := os.environ.get("SHADOW_CLERK_DATA_DIR"):
        return env
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, "shadow-clerk")
        return os.path.expanduser("~/AppData/Roaming/shadow-clerk")
    return os.path.expanduser("~/.local/share/shadow-clerk")
```

Also add `import sys` to the imports at the top of the file (after `import os`).

- [ ] **Step 1.3: Syntax check**

Run: `uv run python -m py_compile src/shadow_clerk/__init__.py`

Expected: no output (silent success).

- [ ] **Step 1.4: Verify Linux behavior unchanged**

Run: `uv run python -c "import shadow_clerk; print(shadow_clerk.DATA_DIR)"`

Expected: `/home/<user>/.local/share/shadow-clerk` (the `SHADOW_CLERK_DATA_DIR` env var must be unset for this to be meaningful — `unset SHADOW_CLERK_DATA_DIR` first if needed).

- [ ] **Step 1.5: Verify Windows path resolution (simulated)**

Run:
```
SHADOW_CLERK_DATA_DIR= APPDATA='C:\\Users\\test\\AppData\\Roaming' \
  uv run python -c "
import sys
sys.platform = 'win32'  # not actually how this works, fall back to direct call
import shadow_clerk
print(shadow_clerk.get_data_dir())
"
```

That trick doesn't actually work because `sys.platform` is read at startup. Use this instead:

```
uv run python -c "
import os, sys
os.environ.pop('SHADOW_CLERK_DATA_DIR', None)
os.environ['APPDATA'] = r'C:\Users\test\AppData\Roaming'
# Manually re-implement the Windows branch logic to verify the path it would produce
from shadow_clerk import get_data_dir
import shadow_clerk
shadow_clerk.sys = type('S', (), {'platform': 'win32'})  # monkeypatch
print(get_data_dir())
"
```

If the monkeypatch is too fragile, skip this step and trust the syntax check + Windows runtime verification scheduled in Task 8.

- [ ] **Step 1.6: Commit**

```
git add src/shadow_clerk/__init__.py
git commit -m "Resolve data dir per platform (Windows: %APPDATA%)"
```

---

## Task 2: WASAPI monitor device lookup + signature change

> **⚠️ Phase A1 のこのタスクは設計上の誤り(ハルシネーション)により廃棄。`WasapiSettings(loopback=True)` は実在しない API。**
> **Phase A2 で `soundcard` パッケージベースの `WasapiSoundcardBackend` に作り直し済み。**
> **詳細は設計書 §2.1 を参照。以下のステップは歴史的記録として残す。**

**Files:**
- Modify: `src/shadow_clerk/_daemon_audio.py:241-276` (rewrite `find_monitor_device_sd`)
- Modify: `src/shadow_clerk/_daemon_audio.py:288-291` (call site in `list_all_devices`)
- Modify: `src/shadow_clerk/_daemon_recorder_capture.py:172-238` (call site in `_monitor_capture_thread` and `_monitor_capture_sounddevice`)

The function changes its return type from `int | None` to `tuple[int, dict[str, Any]] | None`. The dict is empty `{}` on Linux and contains `{"extra_settings": <WasapiSettings instance>}` on Windows. Callers unpack the tuple.

- [ ] **Step 2.1: Add `import sys` to `_daemon_audio.py`**

The file currently imports `os`, `shutil`, `subprocess`, etc. Add `import sys` near the top (alphabetical).

- [ ] **Step 2.2: Add the Windows helper**

Insert immediately above the existing `find_monitor_device_sd()` function:

```python
def _find_monitor_device_wasapi() -> tuple[int, dict[str, Any]] | None:
    """Windows WASAPI ループバック用デバイスを返す。

    既定の再生デバイス(スピーカー/ヘッドホン)を loopback フラグ付き
    InputStream として開けるよう、(デバイスID, extra_settings) を返す。
    """
    import sounddevice as sd
    try:
        hostapis = sd.query_hostapis()
    except sd.PortAudioError as e:
        logger.error("PortAudio ホストAPI取得失敗: %s", e)
        return None
    wasapi_idx = next(
        (i for i, h in enumerate(hostapis) if h["name"] == "Windows WASAPI"),
        None,
    )
    if wasapi_idx is None:
        logger.warning("Windows WASAPI ホストAPIが見つかりません")
        return None
    default_out = hostapis[wasapi_idx].get("default_output_device")
    if default_out is None or default_out < 0:
        logger.warning("WASAPI 既定の出力デバイスが見つかりません")
        return None
    try:
        settings = sd.WasapiSettings(loopback=True)
    except AttributeError:
        # 古い sounddevice では `WasapiSettings` 未提供
        logger.error(
            "sounddevice の WasapiSettings が利用できません。"
            "sounddevice>=0.4.6 が必要です。"
        )
        return None
    dev_info = sd.query_devices(default_out)
    logger.debug(
        "WASAPI loopback デバイス選択: #%d %s", default_out, dev_info["name"]
    )
    return default_out, {"extra_settings": settings}
```

- [ ] **Step 2.3: Refactor existing `find_monitor_device_sd()`**

Replace the existing function body with the dispatcher and rename the Linux body to `_find_monitor_device_linux`:

```python
def find_monitor_device_sd() -> tuple[int, dict[str, Any]] | None:
    """sounddevice でモニターデバイスを検索

    戻り値: (デバイスID, sd.InputStream に追加で渡す kwargs) または None。
    Linux では追加 kwargs は空 dict。Windows では WASAPI loopback 設定を含む。
    """
    if sys.platform == "win32":
        return _find_monitor_device_wasapi()
    return _find_monitor_device_linux()


def _find_monitor_device_linux() -> tuple[int, dict[str, Any]] | None:
    """Linux (PipeWire/PulseAudio) でモニターデバイスを検索

    PipeWire: `.monitor` サフィックスを持つ入力デバイス
    PulseAudio: "Monitor of " プレフィックスを持つ入力デバイス
    デフォルト Sink に対応するモニターを優先する。
    """
    import sounddevice as sd
    devices = sd.query_devices()
    candidates = []
    for i, dev in enumerate(devices):
        name = dev["name"]
        is_monitor = (
            name.endswith(".monitor")
            or name.lower().startswith("monitor of ")
        )
        if is_monitor and dev["max_input_channels"] > 0:
            candidates.append((i, name))
            logger.debug("monitor 候補: #%d %s", i, name)

    if not candidates:
        logger.debug("monitor 候補なし")
        return None

    # デフォルト Sink に対応するモニターを優先
    default_sink = _get_default_sink_name()
    if default_sink:
        expected_monitor = default_sink + ".monitor"
        for idx, name in candidates:
            if name == expected_monitor:
                logger.debug("デフォルト Sink のモニター選択: #%d %s", idx, name)
                return idx, {}

    # 見つからなければ最初の候補
    logger.debug("デフォルト Sink 不明、最初の候補を選択: #%d %s", *candidates[0])
    return candidates[0][0], {}
```

Note the change from `return idx`/`return candidates[0][0]` to returning a tuple.

- [ ] **Step 2.4: Add `Any` import**

If `Any` is not already imported in `_daemon_audio.py`, add `from typing import Any` near the top.

- [ ] **Step 2.5: Update `list_all_devices()` (same file)**

Find lines around 288-291:

```python
    monitor_sd = find_monitor_device_sd()
    if monitor_sd is not None:
        print(t("rec.auto_detect_sd", device=monitor_sd))
```

Replace with:

```python
    monitor_sd = find_monitor_device_sd()
    if monitor_sd is not None:
        device_idx, _ = monitor_sd
        print(t("rec.auto_detect_sd", device=device_idx))
```

- [ ] **Step 2.6: Update `_monitor_capture_thread()` in `_daemon_recorder_capture.py`**

Lines 172-184 currently:

```python
        monitor_device = self.args.monitor
        if monitor_device is None:
            monitor_device = find_monitor_device_sd()

        if monitor_device is not None:
            dev_info = sd.query_devices(monitor_device)
            logger.info("sounddevice monitor キャプチャ開始 (device=%s: %s)", monitor_device, dev_info["name"])
            if self._monitor_capture_sounddevice(monitor_device):
                return
```

Replace with:

```python
        monitor_device = self.args.monitor
        monitor_extra: dict[str, Any] = {}
        if monitor_device is None:
            found = find_monitor_device_sd()
            if found is not None:
                monitor_device, monitor_extra = found

        if monitor_device is not None:
            dev_info = sd.query_devices(monitor_device)
            logger.info("sounddevice monitor キャプチャ開始 (device=%s: %s)", monitor_device, dev_info["name"])
            if self._monitor_capture_sounddevice(monitor_device, monitor_extra):
                return
```

(Ensure `Any` is imported. The file already imports `from typing import Any` lazily inside `_mic_capture_thread`; promote it to a top-of-file import for consistency.)

- [ ] **Step 2.7: Update `_monitor_capture_sounddevice()` signature**

Currently starts at line 228:

```python
    def _monitor_capture_sounddevice(self, device: int) -> bool:
        """sounddevice でモニターデバイスをキャプチャ。成功なら True、失敗なら False。"""
        from typing import Any
        import sounddevice as sd

        def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            if status:
                logger.warning("モニター status: %s", status)
            self.monitor_queue.put(indata[:, 0].copy().astype(np.int16))
```

Modify the signature and the `sd.InputStream(...)` call to pass `**extra` through. The full method should look like (read the existing call to `stream = sd.InputStream(...)` — it lives just below the callback — and merge `**extra` into it):

```python
    def _monitor_capture_sounddevice(
        self, device: int, extra: dict[str, Any] | None = None
    ) -> bool:
        """sounddevice でモニターデバイスをキャプチャ。成功なら True、失敗なら False。

        extra: sd.InputStream に追加で渡す kwargs(WASAPI loopback 設定等)。
        """
        import sounddevice as sd
        extra = extra or {}

        def callback(indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
            if status:
                logger.warning("モニター status: %s", status)
            self.monitor_queue.put(indata[:, 0].copy().astype(np.int16))

        try:
            with self._stream_lock:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    blocksize=FRAME_SIZE,
                    device=device,
                    callback=callback,
                    **extra,
                )
                stream.start()
            self.stop_event.wait()
            stream.stop()
            stream.close()
            return True
        except sd.PortAudioError as e:
            logger.error("sounddevice モニターキャプチャエラー: %s", e)
            return False
```

If the existing implementation differs from the snippet above (read it first via `Read` tool!), preserve its semantics — only modify the **signature** and the **`sd.InputStream(...)` keyword args** to accept `**extra`. Do not rewrite unrelated logic.

- [ ] **Step 2.8: Syntax check**

Run:
```
uv run python -m py_compile src/shadow_clerk/_daemon_audio.py src/shadow_clerk/_daemon_recorder_capture.py
```

Expected: silent success.

- [ ] **Step 2.9: Linux smoke test (regression)**

```
clerk-util restart
# wait ~5s
clerk-util recorder-status   # expect: running
```

Open a YouTube video, speak, watch dashboard transcript. Confirm both mic and monitor still produce text on Linux. If not, fix before moving on.

- [ ] **Step 2.10: Commit**

```
git add src/shadow_clerk/_daemon_audio.py src/shadow_clerk/_daemon_recorder_capture.py
git commit -m "Support WASAPI loopback for monitor capture on Windows"
```

---

## Task 3: Cross-platform `clerk-util stop`

**Files:**
- Modify: `src/shadow_clerk/clerk_util.py:158-164` (`_is_pid_alive`)
- Modify: `src/shadow_clerk/clerk_util.py:328-345` (`cmd_stop` and `cmd_restart` reuse)

`os.kill(pid, 0)` for liveness probe works on Windows in Python 3.x (raises `OSError(EINVAL)` for nonexistent PIDs), so `_is_pid_alive` likely needs no change — but verify. The `cmd_stop` path needs to use `taskkill` because `os.kill(pid, signal.SIGTERM)` on Windows can't reach a console app's `signal.SIGTERM` handler reliably.

- [ ] **Step 3.1: Read current implementations**

Run: `sed -n '140,200p;320,360p' src/shadow_clerk/clerk_util.py`

Note exact line numbers and surrounding context — what imports, helper variables.

- [ ] **Step 3.2: Add `sys` import if missing**

Confirm `import sys` is present in `clerk_util.py`. If not, add it.

- [ ] **Step 3.3: Add a Windows-aware terminate helper**

Insert above `cmd_stop`:

```python
def _terminate_pid(pid: int) -> None:
    """OS に応じて clerk-daemon プロセスを終了させる。

    Linux: SIGTERM。
    Windows: taskkill /PID (graceful) → 5秒待っても残るなら taskkill /F。
    """
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid)],
                capture_output=True, timeout=5, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        # 残っていたら強制終了
        for _ in range(10):
            if not _is_pid_alive(pid):
                return
            _time.sleep(0.5)
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, timeout=5, check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        return
    os.kill(pid, _signal.SIGTERM)
```

`_signal` and `_time` are the existing aliases used in `clerk_util.py` (verify by grep — if the file imports `signal` directly, use `signal.SIGTERM` and `time.sleep`). Adjust the snippet accordingly.

- [ ] **Step 3.4: Replace `os.kill(pid, _signal.SIGTERM)` calls with `_terminate_pid(pid)`**

In `cmd_stop` (line ~333):

```python
    pid = _read_pid()
    if pid and _is_pid_alive(pid):
        os.kill(pid, _signal.SIGTERM)
```

becomes:

```python
    pid = _read_pid()
    if pid and _is_pid_alive(pid):
        _terminate_pid(pid)
```

In `cmd_restart` (line ~345):

```python
        if pid and _is_pid_alive(pid):
            os.kill(pid, _signal.SIGTERM)
```

becomes:

```python
        if pid and _is_pid_alive(pid):
            _terminate_pid(pid)
```

- [ ] **Step 3.5: Syntax check**

Run: `uv run python -m py_compile src/shadow_clerk/clerk_util.py`

Expected: silent success.

- [ ] **Step 3.6: Linux smoke test**

```
clerk-util start   # if not already running
clerk-util recorder-status   # running
clerk-util stop
clerk-util recorder-status   # stopped
clerk-util start
```

Confirm SIGTERM still works on Linux.

- [ ] **Step 3.7: Commit**

```
git add src/shadow_clerk/clerk_util.py
git commit -m "Use taskkill for stop on Windows; keep SIGTERM on Linux"
```

---

## Task 4: Optional `evdev` dependency

**Files:**
- Modify: `pyproject.toml:7-17`

- [ ] **Step 4.1: Edit `pyproject.toml`**

Find:

```
    "pynput>=1.7.6",
    "evdev>=1.6.0",
```

Replace the `evdev` line with:

```
    "evdev>=1.6.0; sys_platform == 'linux'",
```

- [ ] **Step 4.2: Re-sync the lockfile**

Run: `uv sync`

Expected: success, no `evdev` removal on Linux (still installed because the marker matches).

- [ ] **Step 4.3: Confirm imports still resolve**

Run: `uv run python -c "from shadow_clerk._daemon_constants import _HAS_EVDEV, _HAS_PYNPUT; print(_HAS_EVDEV, _HAS_PYNPUT)"`

Expected: `True True` on Linux.

- [ ] **Step 4.4: Commit**

```
git add pyproject.toml uv.lock
git commit -m "Mark evdev as Linux-only dependency"
```

---

## Task 5: README Windows section

**Files:**
- Modify: `README.md` (English)
- Modify: `README.ja.md` (Japanese)

- [ ] **Step 5.1: Find an existing platform/install section in `README.md`**

Run: `grep -n -i "install\|requirement\|platform\|linux" README.md | head`

Note where to insert the Windows subsection.

- [ ] **Step 5.2: Insert Windows section in `README.md`**

Add a `## Windows Support` (or a "Platform support" section if more natural) with:

```markdown
## Platform support

| OS | Status | Notes |
|----|--------|-------|
| Linux (PipeWire/PulseAudio) | Supported | Primary development target |
| Windows 10/11 | Supported | Monitor capture via WASAPI loopback (default playback device) |
| macOS | Not supported yet | Requires a virtual audio driver (e.g. BlackHole) — not implemented |

### Windows setup

1. Install [uv](https://docs.astral.sh/uv/).
2. Install shadow-clerk:
   ```
   uv tool install shadow-clerk
   ```
3. Allow microphone access for the terminal you launch from (Windows Settings → Privacy → Microphone).
4. Start the daemon:
   ```
   clerk-daemon
   ```
5. Open the dashboard at <http://localhost:8765>.

The data directory is `%APPDATA%\shadow-clerk`. Monitor capture follows the system default playback device — switching the default device in Windows sound settings switches what gets captured.

To stop the daemon:
```
clerk-util stop
```
```

- [ ] **Step 5.3: Mirror the change in `README.ja.md`**

Translate the same content into Japanese, matching the existing tone.

- [ ] **Step 5.4: Commit**

```
git add README.md README.ja.md
git commit -m "Document Windows setup and platform support matrix"
```

---

## Task 6: Update `cross-platform.md` notes

**Files:**
- Modify: `improvement/cross-platform.md`

- [ ] **Step 6.1: Read the current file**

The file references stale line numbers (`clerk_daemon.py L195-427`, etc.) — that file was split into `_daemon_*` modules.

- [ ] **Step 6.2: Apply edits**

At the top of the file, after the `## 現状` section, insert:

```markdown
## 進捗

- 2026-04-25 Windows 対応(Phase A1) 実装済み: データディレクトリ・WASAPI ループバックモニター・`clerk-util stop` の3点を分岐。Linux 動作はそのまま温存。
- 残: macOS 対応、PipeWire/PulseAudio 直叩きの完全廃止(Phase B、未着手)。
```

For each "対象コード" line that points to `clerk_daemon.py L<n>-<m>`, replace with the current module:
- 音声キャプチャ: `_daemon_audio.py`(バックエンド), `_daemon_recorder_capture.py`(マイク・モニタースレッド)
- PTT 入力: `_daemon_recorder_command.py`, `_daemon_constants.py`(import フラグ)

Don't bother chasing every line number — module paths are sufficient and won't go stale on the next refactor.

- [ ] **Step 6.3: Commit**

```
git add improvement/cross-platform.md
git commit -m "Update cross-platform notes: mark Windows phase done"
```

---

## Task 7: Final regression check on Linux

- [ ] **Step 7.1: Restart the daemon with the latest code**

```
clerk-util restart
clerk-util recorder-status   # running
```

- [ ] **Step 7.2: Functional smoke**

- Open dashboard at <http://localhost:8765>.
- Speak into mic → transcript line appears with `[Self]` (or whichever speaker label your config uses).
- Play a YouTube video → another transcript line with `[Other]`.
- Press the configured PTT key while saying a known voice command → command fires.
- `clerk-util stop` → status flips to `stopped` within a few seconds.
- `clerk-util start` → recovers cleanly.

If any of these regress, treat it as a blocker for this plan and fix before declaring done.

- [ ] **Step 7.3: No commit needed** — verification only.

---

## Task 8: Windows verification protocol (handoff)

This task is documentation, not code. The actual verification happens on whoever has Windows.

- [ ] **Step 8.1: Append a verification checklist to `docs/superpowers/specs/2026-04-25-windows-support-design.md`**

Add a new section at the bottom:

```markdown
## Windows verification checklist (for the requester)

Run these on a Windows 10/11 machine after `uv tool install shadow-clerk`:

- [ ] `clerk-daemon --help` runs without error
- [ ] `clerk-daemon` starts and prints data directory under `%APPDATA%\shadow-clerk`
- [ ] Mic capture: speaking produces transcript lines tagged `[Self]`
- [ ] Monitor capture: playing audio (YouTube etc.) produces transcript lines tagged `[Other]`
- [ ] Dashboard reachable at <http://localhost:8765>
- [ ] PTT key (set in `config.yaml`) triggers a voice command
- [ ] `clerk-util stop` terminates the daemon within ~5 seconds
- [ ] After exit, no orphan `clerk-daemon.exe` in Task Manager

If anything fails, capture:
- The full daemon log (`%APPDATA%\shadow-clerk\daemon.log`)
- The terminal output during start
- Output of `python -c "import sounddevice as sd; print(sd.query_hostapis()); print(sd.query_devices())"`

and report back.
```

- [ ] **Step 8.2: Commit**

```
git add docs/superpowers/specs/2026-04-25-windows-support-design.md
git commit -m "Add Windows verification checklist for requester"
```

---

## Self-review summary

- **Spec coverage:** every numbered section in the spec maps to a task here:
  - Spec §1 (data dir) → Task 1
  - Spec §2 (audio) → Task 2
  - Spec §3 (PTT) → no code change needed; covered in Task 7 smoke + Task 8 Windows checklist
  - Spec §4 (signal) → Task 3
  - Spec §5 (deps) → Task 4
  - Spec §6 (docs) → Tasks 5 & 6
  - Test plan → Tasks 7 & 8
- **No placeholders:** all steps include concrete code, paths, commands.
- **Type consistency:** `find_monitor_device_sd()` switches to `tuple[int, dict[str, Any]] | None` in Task 2.2/2.3 and is unpacked consistently at every call site listed.
- **Out-of-scope items** stay out: macOS, full backend abstraction, MSI packaging, browser auto-launch.
