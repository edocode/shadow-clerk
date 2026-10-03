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

## Windows handoff: talk mode の Claude の声を会議に届ける（Phase 2-1）

Linux 版は PR #25（branch `feat/talk-route`、spec は `improvement/claude-talk-route.md`）で実装済み。
Windows 版は実機での確認が欠かせないので、Windows 上で設計・実装する。ここはその引き継ぎ。

### いまの状態

- **経路の抽象**: `src/shadow_clerk/_daemon_talk_route.py` の `TalkRoute` Protocol
  （`available()` / `targets()` / `connect(app, source_port)` / `disconnect()` / `status()`）。
  `make_route()` は Linux で PipeWire のツールがそろえば `PipeWireRoute`、それ以外は `NullRoute` を返す。
  Windows ではいま `NullRoute` なので、開始モーダルの「Claude の声を届ける先」は選べない（無効表示）
- **TalkDriver の経路の使い方**（`_daemon_talk.py` の `start()`）: `route` が指定されると
  `route_factory()` → `available()` を確かめ → `PwCatSink` を起動 → `TtsPlayer(backend, sink.play, …)` →
  `route.connect(route, source_port)`。**つまり今の driver は「経路あり = pw-cat で鳴らす」を前提にしている**。
  Windows 版ではここを一般化する必要がある（下の「実装の方向」）
- **経路なしのとき**: `make_player()` が `play_on_devices(talk_output_devices)` で、指定した出力デバイス
  すべてに同時に鳴らす（sounddevice、`PORTAUDIO_LOCK` で排他）。**Windows でもこの経路はそのまま動く**
- `_daemon_tts_pipewire.py` は `fcntl` を `_spawn` の中で読み込むので、Windows でも import は通る

### 方式の候補

Windows の音声エンジンは、同じ再生デバイスに来た複数の共有モードのストリームを混ぜる。これを使う。

- **A（第一候補）: OS に混ぜてもらう**
  1. VB-CABLE を入れる（再生デバイス「CABLE Input」と録音デバイス「CABLE Output」ができる）
  2. サウンド設定の「録音」→ 実マイクのプロパティ →「聴く」で「このデバイスを聴く」、再生先を CABLE Input
  3. shadow-clerk は TTS をヘッドセットと CABLE Input の両方に鳴らす
  4. 会議アプリのマイクを CABLE Output にする → 相手には実マイク + Claude の声が届く
  - 利点: マイクの中継コードが要らない。shadow-clerk が止まっても自分の声は届く
  - 懸念: 「このデバイスを聴く」の遅延・音質。会議アプリのエコーキャンセルとの相性
- **B（A が駄目なとき）: shadow-clerk がマイクを中継する**
  - 実マイクを（ASR 用の 16kHz とは別に）48kHz で開き、TTS を重ねて CABLE Input へ出す
  - 欠点: 数十 ms の遅延が乗る。会議の音声経路が shadow-clerk に依存する（止まると自分の声も届かない）

### 最初にやるスパイク（コード変更なしで A を確かめる）

1. VB-CABLE を入れ、上の A の 1〜2 を設定する
2. `config.yaml` の `talk_output_devices` に、ヘッドセットと CABLE Input のデバイス名を並べる
   （例 `["<ヘッドセット名>", "CABLE Input (VB-Audio Virtual Cable)"]`。名前はダッシュボードの音声デバイス一覧に合わせる）
3. ボイスレコーダー（録音デバイス = CABLE Output）か会議アプリのマイクテスト（マイク = CABLE Output）で録りながら
   「Claude と会議」で話す
4. 見ること: 自分の声と Claude の声の両方が入るか / 自分の声の遅延・音質 / エコーキャンセルで Claude の声が消えないか /
   ヘッドセットからも Claude が聞こえるか

### 実装の方向（A で行けた場合）

- Windows では「届ける先」= 会議アプリではなく **仮想デバイス（CABLE Input など）の再生デバイス**。
  `targets()` は出力デバイスのうち仮想デバイスらしいもの（名前で判定。候補を広めに出して選ばせてもよい）を返す
- driver の「経路あり = pw-cat」を一般化する。例: 経路オブジェクトが再生の仕方も持つ
  （`TalkRoute.make_play(config) -> (PlayFn, cleanup)` のような口を足し、PipeWire 版は `PwCatSink`、
  Windows 版は `play_on_devices(talk_output_devices + [選んだ仮想デバイス])` を返す）。
  ここは Windows 上で brainstorming → spec → 計画の流れで決める
- 「このデバイスを聴く」の設定は shadow-clerk からは変えない。README（英日）に手順を書き、
  ダッシュボードの「届ける先」の注記にも「実マイクを CABLE Input で聴く設定が必要」と出す
- 実デバイスでの手動確認を必ず行う（Linux 側でも、テストの偽物では `pw-cat --raw` の抜けを拾えなかった）

### Phase 2-2 に向けた Windows の実験（相手の発言を読み、Claude の声を除く）

talk mode 中も monitor（相手の声）を文字起こしするには、手元で鳴らした Claude の声を monitor から除く必要がある。
Linux は会議アプリの再生ストリームだけを `pw-link` で録れば済むが、Windows の WASAPI ループバックは出力デバイス
全体を録るので、Claude の声が混ざる。候補は2つ:

- 流した TTS の波形とループバックの録音を相互相関で位置合わせし、差し引く（重なった相手の声は残せる）
- TTS（手元のヘッドセット向けだけ）に聞こえない目印（19kHz 付近）を重ね、目印のある区間を捨てる

どちらも「ループバックに戻る音が、流した音とどれだけ一致するか」で決まる。既知の WAV をヘッドセットに鳴らしながら
`soundcard` のループバックで録り、遅延・音量比・残差（差し引いたあとの残り）を測るスパイクを先にやる。
OS の音量やエンハンスメント（音響効果）で波形が変わる環境があるので、オン・オフ両方で見る。

### Windows で気をつけること

- `tests/test_windows_port.py` は main でも落ちている（`open_console_pty()` に増えた `rows` 引数に未追従）。Windows で直すのがよい
- テストは `uv run python tests/<file>.py`。音を鳴らす確認・実デバイスの確認は手動
- デバイスは名前で扱う（index は起動ごとに変わる）
- VB-CABLE は寄付ウェアのフリーソフト。shadow-clerk には同梱せず、README で案内するだけにする
