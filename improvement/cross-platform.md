# クロスプラットフォーム対応調査

## 現状

shadow-clerk は Linux 専用。主な依存: PipeWire/PulseAudio（音声キャプチャ）、evdev（Wayland PTT入力）。

## 進捗

- 2026-04-25 Windows 対応 Phase A1 部分完了: データディレクトリ・`clerk-util stop/restart/start` の分岐・evdev Linux 限定化。Linux 動作はそのまま温存。
- 2026-04-25 Windows 対応 Phase A2 完了: WASAPI ループバックモニターを `soundcard` パッケージベースで実装 (`WasapiSoundcardBackend`)。`clerk-util` の `pkill` フォールバック・`SIGHUP` 登録・`os.execv` パス解決も Windows 対応済み。
- 残: macOS 対応、PipeWire/PulseAudio 直叩きの完全廃止(Phase B、未着手)。

## プラットフォーム依存箇所

### 1. システム音声（モニター）キャプチャ — 難易度: 高

相手の声をキャプチャする仕組みが OS ごとに根本的に異なる。最大の課題。

| OS | 仕組み | 備考 |
|----|--------|------|
| Linux | PulseAudio/PipeWire の `.monitor` デバイスが自動提供 | 追加設定不要 |
| Windows | WASAPI ループバック API | `soundcard` パッケージ経由で `WasapiSoundcardBackend` として実装済み |
| macOS | OS標準ではシステム音声キャプチャ不可 | BlackHole や Background Music 等の仮想オーディオドライバが必須 |

**対象コード**: `_daemon_audio.py`（バックエンド）、`_daemon_recorder_capture.py`（マイク・モニタースレッド）

### 2. 音声ツール（サブプロセス呼び出し）— 難易度: 中

以下の Linux 専用コマンドを使用中:
- `pw-record`, `pw-cli` — PipeWire 録音・デバイス列挙
- `pactl`, `parec` — PulseAudio デバイス列挙・録音
- `wpctl` — デフォルトシンク検出

**対応方針**: sounddevice（PortAudio ベース、クロスプラットフォーム）に統一し、上記ツール依存を除去

**対象コード**: `_daemon_audio.py`

### 3. PTT キー入力 — 難易度: 低

| ライブラリ | 対応OS | 用途 |
|-----------|--------|------|
| evdev | Linux のみ | Wayland 環境での PTT |
| pynput | Windows/Mac/Linux (X11) | X11 環境での PTT |

**対応方針**: pynput をプライマリに統一。evdev は Linux Wayland 用のオプションとして残す

**対象コード**: `_daemon_recorder_command.py`、`_daemon_constants.py`（import フラグ）

### 4. 設定ファイルパス — 難易度: 低

現在 XDG 規約（`~/.local/share/shadow-clerk`）を使用。

**対応方針**: `platformdirs` ライブラリで OS ごとの標準パスに対応
- Windows: `%APPDATA%\shadow-clerk`
- macOS: `~/Library/Application Support/shadow-clerk`
- Linux: `~/.local/share/shadow-clerk`

### 5. その他 — 難易度: 低

- **マイク入力**: sounddevice でそのまま動作（変更不要）
- **Dashboard**: HTTP サーバーベース（変更不要）
- **シグナル処理**: `SIGTERM` は Windows で制限あり（`SIGINT` のみ対応）
- **Wayland 検出** (`XDG_SESSION_TYPE`): Windows/Mac では不要

## 対応方針まとめ

1. **sounddevice をベースに統一** — PipeWire/PulseAudio ツール依存を除去
2. **モニターデバイス検出を抽象化** — OS ごとのデバイス列挙・選択ロジックを分離
3. **pynput をPTTのプライマリに** — evdev は Linux Wayland オプション
4. **platformdirs でパス解決** — OS 標準のデータディレクトリを使用
5. **macOS はユーザーに仮想オーディオドライバ導入を案内**（BlackHole 等）

## 工数感

- コードの 60-70% はそのまま動作
- 最大の作業はモニターキャプチャの抽象化（Windows WASAPI 対応 + macOS 仮想デバイス対応）
- pyproject.toml の依存を OS ごとに分岐（`evdev` は Linux のみ等）
