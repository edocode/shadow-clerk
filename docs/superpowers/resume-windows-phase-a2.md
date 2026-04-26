# Windows対応 Phase A2 引き継ぎメモ

- 作成日: 2026-04-25
- ブランチ: `windows-support`
- 関連ドキュメント:
  - 設計書: `docs/superpowers/specs/2026-04-25-windows-support-design.md`
  - 実装プラン(Phase A1): `docs/superpowers/plans/2026-04-25-windows-support.md`

## ここまでで何をやったか(Phase A1)

`origin/main` (ea1800d) からこのブランチで以下8つの機能コミットを積んだ:

```
2cf5cd5 Resolve data dir per platform (Windows: %APPDATA%)
e59402b Support WASAPI loopback for monitor capture on Windows  ← Critical defect 含む
0ed4feb Use taskkill for stop on Windows; keep SIGTERM on Linux
4a0e593 Mark evdev as Linux-only dependency
30fbf25 Untrack uv.lock (it is gitignored)
220f743 Document Windows setup and platform support matrix
56fbf4e Update cross-platform notes: mark Windows phase done
881deb1 Add Windows verification checklist for requester
```

加えて設計/プランの2コミット(`e74edbf`, `08897ff`)。

Linux 動作は smoke test で確認済み(stop/start/monitor/translation/summary すべて回帰なし)。

## Critical defect: Windows モニターキャプチャは動かない

`e59402b` で追加した `_find_monitor_device_wasapi` (`src/shadow_clerk/_daemon_audio.py`) は **動かない API を呼んでいる**:

```python
settings = sd.WasapiSettings(loopback=True)  # TypeError
```

実機検証 (sounddevice 0.5.5):

```
WasapiSettings init signature: (self, exclusive=False, auto_convert=False, explicit_sample_format=False)
TypeError: WasapiSettings.__init__() got an unexpected keyword argument 'loopback'
```

`sounddevice` は WASAPI loopback を Python API レベルで露出していない。`AttributeError` の except 節は `TypeError` を捕まえないので、Windows では起動時に未捕捉例外が伝播する。

Phase A1 設計書(`docs/superpowers/specs/2026-04-25-windows-support-design.md` §2.1)とプラン(同 Task 2)は、私(Claude)が `WasapiSettings(loopback=True)` を実在 API と誤認したハルシネーションが原因。**設計の前提が誤っていた**ので Phase A2 で作り直す必要がある。

## Phase A2 でやるべきこと

### 1. WASAPI loopback を別の方法で実装(Critical)

選択肢:

- **`soundcard` パッケージ** — pure Python、WASAPI loopback ネイティブ対応、保守活発。`microphone(include_loopback=True)` で loopback デバイス取得可能。Linux/macOS でも動くので将来 macOS 対応の足がかりにもなる。
- **`pyaudiowpatch`** — `pyaudio` の fork、loopback 専用。`pyaudio` 自体重い(C 拡張、ビルド要)が、Windows 向けには確実。
- **PortAudio CFFI を直叩き** — `paWinWasapiLoopback` フラグを `PaWasapiStreamInfo` 経由でセット。複雑、保守困難。非推奨。

推奨: **`soundcard` パッケージ**。Linux でも sounddevice と共存可能なので Linux 側に害がない。Windows 専用のキャプチャクラスとして `_daemon_audio.py` に追加し、`_find_monitor_device_wasapi` は捨てて、`_monitor_capture_thread` に Windows 分岐を1本足す形が自然。

ただし `soundcard` の音声フレーム取得 API は sounddevice の callback 形式とは違う(numpy 配列を polling で取る)ので、`_daemon_recorder_capture.py:_monitor_capture_sounddevice` とは別に Windows 専用メソッド `_monitor_capture_soundcard` を作るほうが綺麗。

### 2. Important issues の修正

最終 code reviewer が見つけた、Phase A1 でカバーできていない箇所:

- **`clerk_util.py` の `pkill` フォールバック** (`cmd_stop` 365行付近, `cmd_restart` 376行付近)
  - PID ファイル不存在時のフォールバックが `subprocess.run(["pkill", ...])`。Windows に `pkill` はない。
  - 修正: Windows 分岐で `taskkill /F /IM clerk-daemon.exe` を試す。または「このパスは Linux 専用」と割り切ってログ警告だけ出す。

- **`clerk_util.py:cmd_poll` の `signal.SIGHUP` 登録**
  - `signal.SIGHUP` は Windows 未定義 → `AttributeError`。
  - 修正: `if sys.platform != "win32": signal.signal(signal.SIGHUP, ...)` でガード。
  - **これは pre-existing で Phase A1 が直接導入したわけではない**が、Windows 検証で直ちに踏む。

- **`clerk_util.py:_exec_clerk_daemon` の `os.execv("clerk-daemon")`**
  - Windows では `.exe` 拡張子なしの実行ファイルを `os.execv` が見つけられない可能性大。
  - 修正案: Windows では `subprocess.Popen([clerk-daemon-full-path], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)` を使い、親 (`clerk-util`) は終了する。または `shutil.which("clerk-daemon")` で `.exe` 含む解決をしてから渡す。
  - 影響範囲: `clerk-util start` / `clerk-util restart` 全体。

### 3. Minor 修正(任意)

- `clerk_util.py:cmd_stop` の docstring と help 文(`SIGTERM 送信`)を「Linux: SIGTERM, Windows: taskkill」に書き換え。
- `__init__.py` に `from __future__ import annotations` を追加(プロジェクト規約)。

### 4. プラン/スペックの修正

- `docs/superpowers/specs/2026-04-25-windows-support-design.md` §2 を `soundcard` ベースに書き直す。
- `docs/superpowers/plans/2026-04-25-windows-support.md` Task 2 を修正(または Phase A2 用の新プランを作る)。
- `improvement/cross-platform.md` の「Phase A1 完了」記載は **誤り**(Windows モニターキャプチャは未完成)。トーンを「Phase A1 部分完了、モニターキャプチャは Phase A2 に持ち越し」に修正。

## 再開手順

```bash
git fetch origin
git checkout windows-support
git pull --ff-only origin windows-support  # 念のため
```

新セッションで Claude に伝える内容:

1. 「`docs/superpowers/resume-windows-phase-a2.md` を読んで Phase A2 を進めて」
2. このメモの「Critical defect」と「Phase A2 でやるべきこと」を出発点として、`superpowers:brainstorming` → `superpowers:writing-plans` → `superpowers:subagent-driven-development` の順に進める。
3. ブランチは `windows-support` のまま継続。新規ブランチは作らない。

## 既知の状態

- 現在の `windows-support` HEAD: 881deb1 + (このメモのコミット)
- `origin/main` は `ea1800d` (Meeting sort PR まで)。**Windows 関連は origin/main にはまだ入っていない**。
- ローカル `main` ブランチも `origin/main` にリセット済(本ブランチ作成後)。
- `uv.lock` は `.gitignore` 入り(プロジェクト方針)。Phase A2 で依存追加する際は `pyproject.toml` のみコミット。

## 補足: Phase A1 で「正しく動く」コミット

Critical defect は `e59402b` のみ。以下は単独で正しい変更で、Phase A2 でも温存できる:

- `2cf5cd5` データディレクトリ分岐
- `0ed4feb` `_terminate_pid` (Linux 動作も保たれている)
- `4a0e593` evdev marker
- `30fbf25` uv.lock untrack
- `220f743` README Windows 章
- `56fbf4e` cross-platform.md 更新
- `881deb1` 検証チェックリスト

`e59402b` は revert または上書き(soundcard ベースに置き換え)。`220f743` と `56fbf4e` の「動く」ニュアンスは Phase A2 完了後に再調整。
