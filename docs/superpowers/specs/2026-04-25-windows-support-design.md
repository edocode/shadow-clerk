# Windows対応 設計書

- 作成日: 2026-04-25
- 方針: A1(薄い分岐方式・全要素まとめて1リリース)
- 対象外: macOS対応、バックエンド全面抽象化(将来B案)、Windowsインストーラ

## 背景

shadow-clerk は Linux 専用として開発されてきたが、Windows ユーザーから利用要望があった。`improvement/cross-platform.md` に初期調査メモがあるが、その後コードベースが進化し、cross-platform 対応の地ならしが既に進んでいる。本書はそれを踏まえた最小スコープ Windows 対応の設計をまとめる。

## 現状分析(調査済み)

`cross-platform.md` 執筆時点と現在で前提が変わっている重要事項:

| 項目 | cross-platform.md 時点 | 現在の状態 |
|------|------------------------|-----------|
| マイク入力 | sounddevice 想定 | **既に sounddevice 実装済み** (`_daemon_recorder_capture.py:142-170`) |
| モニター入力 | PipeWire/PulseAudio 直叩き | **既に sounddevice 優先 + バックエンドfallback構造** (`_daemon_recorder_capture.py:172-226`) |
| 音声バックエンド抽象化 | 未着手 | **`AudioBackend` 抽象クラス + `PipeWireBackend`/`PulseAudioBackend` 実装済み** (`_daemon_audio.py:14-176`) |
| PTT入力 | evdev のみ | **`pynput`/`evdev` 両対応済み**(`_HAS_PYNPUT`/`_HAS_EVDEV` フラグ、`_resolve_pynput_key` 実装済み) |
| データディレクトリ | 各所散在想定 | **`get_data_dir()` 1箇所に集約済み**(`__init__.py`)、他モジュールは `DATA_DIR` 参照 |

すなわち Windows 対応で実際に必要な変更は当初想定よりかなり小さい。

## 設計

### 1. データディレクトリ (`__init__.py`)

`get_data_dir()` の中身のみ OS 判定に変更。他モジュールは `DATA_DIR` 参照のままで完全に無変更。

```python
def get_data_dir() -> str:
    if env := os.environ.get("SHADOW_CLERK_DATA_DIR"):
        return env
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return os.path.join(appdata, "shadow-clerk")
        # APPDATA 未設定の異常系のみフォールバック
        return os.path.expanduser("~/AppData/Roaming/shadow-clerk")
    return os.path.expanduser("~/.local/share/shadow-clerk")
```

`platformdirs` ライブラリは導入しない(2分岐のために依存追加するメリットが小さい)。macOS対応する段で必要なら再検討。

### 2. 音声キャプチャ

#### 2.1 モニターデバイス検出 (`_daemon_audio.py:find_monitor_device_sd`)

現状は Linux の命名規則(`.monitor` サフィックス、`Monitor of ` プレフィックス)前提。Windows では WASAPI ループバックデバイスを別ロジックで探す。

WASAPI loopback の動作モデル:
- 通常の出力デバイス(スピーカー)を `WasapiSettings(loopback=True)` 付きで `InputStream` として開くと、その出力をキャプチャできる
- 専用の「monitor」デバイスは存在せず、出力デバイス + loopback フラグの組み合わせで実現

実装方針:
- `find_monitor_device_sd()` を `sys.platform` で分岐
- Windows 分岐: `sd.query_hostapis()` で WASAPI ホストAPIを特定し、その `default_output_device` インデックス(= Windows サウンド設定で既定の再生デバイス)を返す。loopback フラグは呼び出し側でセット
- 戻り値は現状の `int | None` のまま(デバイスインデックス)
- ただし Windows では「loopback フラグが必要」というシグナルを別経路で渡す必要があるため、戻り値を `tuple[int, dict] | None`(デバイスID と sounddevice の `extra_settings` 用 dict)に拡張する

```python
def find_monitor_device_sd() -> tuple[int, dict[str, Any]] | None:
    """戻り値: (デバイスID, InputStreamに渡す追加kwargs) または None"""
    if sys.platform == "win32":
        return _find_monitor_device_wasapi()
    return _find_monitor_device_linux()  # 既存ロジック
```

#### 2.2 モニターキャプチャの呼び出し (`_daemon_recorder_capture.py:_monitor_capture_sounddevice`)

現状の `sd.InputStream(...)` 呼び出しに、`find_monitor_device_sd()` から受け取った追加 kwargs(`extra_settings=WasapiSettings(loopback=True)`)を渡せるように修正。Linux では空 dict なので無影響。

#### 2.3 バックエンド検出 (`_daemon_audio.py:detect_backend`)

`PipeWireBackend.is_available()` / `PulseAudioBackend.is_available()` は `shutil.which("pw-cli")` 等で判定済み → Windows では自動的に False になり、`auto` 検出は `sounddevice` に落ちる。**変更不要**。

ただし `preferred="pipewire"` 等が Windows で指定された場合に「PipeWire が利用できません」警告のみ出すのは挙動として正しいので維持。

### 3. PTT入力

`_daemon_recorder_command.py` は既に `_HAS_PYNPUT`/`_HAS_EVDEV` フラグで分岐できる構造。実装としては:
- pynput が利用可能なら pynput を使用
- evdev も利用可能(Linux Wayland 等)なら追加で使用

Windows での動作確認ポイント:
- `pynput` が Windows でデフォルト入力デバイスのキー監視を行えること
- `_resolve_pynput_key()` が `voice_command_key` 設定値(例: `ctrl_r`)を Windows でも正しく解決できること(pynput の API は OS 透過のはずなので問題ない見込み)
- 起動時の `initially_held` 検出は evdev 専用。pynput 側ではこの処理を行わない既存の挙動でOK

**結論**: コード変更は基本不要。テストして必要があれば微修正。

### 4. シグナル処理

`_daemon_main.py` で `SIGTERM` を扱っている部分を確認し、Windows では `SIGINT` のみ登録。`signal.SIGTERM` は Windows でも定義されているが Console アプリへの実用的な発火経路がないため、登録はしてもよいが頼らない。

`clerk-util stop` の Windows 実装:
- 現状 `os.kill(pid, signal.SIGTERM)` 想定
- Windows では `subprocess.run(["taskkill", "/PID", str(pid)], timeout=5)` を実行 → 戻り値非0 または5秒以内にプロセスが終了しなければ `["taskkill", "/F", "/PID", str(pid)]` フォールバック

### 5. 依存関係 (`pyproject.toml`)

- `evdev` を Linux 限定: `evdev; sys_platform == "linux"`
- `pynput` は全プラットフォームで必須
- `sounddevice` は既に必須
- 新規追加なし

### 6. ドキュメント

- `README.md` / `README.ja.md` に Windows セットアップ節追加
  - インストール手順 (`uv tool install`)
  - WASAPI ループバックの仕組み簡単説明(マイク許可 + デフォルト出力デバイスがキャプチャされる)
  - 既知の制限(macOS 未対応)
- `improvement/cross-platform.md` を更新:
  - 行番号 stale 参照を現行モジュールに修正
  - 「Windows対応 実装済み(2026-04-25)」マーク追加
  - 残タスクとして「macOS対応」「バックエンド全面抽象化」を残す

## スコープ外(明示)

- macOS対応(BlackHole 等の前提があり別議論。ユーザーから具体要望が出てから検討)
- バックエンド全面抽象化(B案)。Linux PipeWire/PulseAudio 直叩きは温存
- WSL固有最適化
- Windows 用パッケージング(MSI インストーラ等)。`uv tool install shadow-clerk` で完結する範囲で十分とする
- ダッシュボードのブラウザ自動起動(現状 URL 表示のみ。Linux と挙動を揃える)

## テスト計画

Linux 側回帰:
- 既存 PipeWire 環境で起動 → モニター/マイク/PTT/翻訳/要約 が従来通り動作
- `make dupcheck` 実施(pylint インストール後)

Windows 側初期検証(要望者協力前提):
- `uv tool install` でインストール完了
- `clerk-daemon --backend sounddevice` で起動
- マイクのみで日本語認識ができる
- WASAPI ループバックでブラウザ動画の音声がキャプチャされる
- ダッシュボード(`http://localhost:8765`)が開く
- PTT キー(設定の `voice_command_key`)で音声コマンド受付
- データディレクトリが `%APPDATA%\shadow-clerk` に作られている
- Ctrl+C で正常終了、`clerk-util stop` で停止できる

## 工数見積

- 実装: 0.5〜1日(コード変更点が小さい)
- Linux 回帰: 0.5日
- Windows 実機検証: 要望者ターン(本リポジトリ担当者では実機なし想定)
- 合計: 1〜2日(検証フィードバック待ちは除く)

## 想定リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| WASAPI loopback のデバイス検出ロジックが想定と違う | Windows でモニター取れない | sounddevice の `query_hostapis()` で WASAPI を明示指定。検出失敗時は明示ログ |
| pynput のキーマッピングに OS 差 | PTT 効かない | 起動時の押下検出ログを残し、要望者の検証で実マッピングを確認 |
| `taskkill` がフォアグラウンド権限を要求 | `clerk-util stop` 失敗 | Ctrl+C 案内をフォールバックドキュメント化 |
| 16kHz リサンプル品質 | 認識精度低下 | sounddevice の `samplerate=16000` 直接指定で動かないデバイスがあれば、48kHz キャプチャ + 既存リサンプラに通す |
