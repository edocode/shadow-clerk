# Shadow-clerk 設計仕様

## 概要

Ubuntu 環境で Web会議の音声をリアルタイムで録音・文字起こしし、Claude Code の Skill で議事録生成・翻訳を行うシステム。

## アーキテクチャ

### モジュール A: clerk_daemon.py（録音・文字起こし）

Python スクリプト。常駐してリアルタイムに文字起こしを行う。

- **音声キャプチャ**: マイク（自分）とシステム音声モニター（相手）を同時キャプチャ
- **バックエンド**: PipeWire → PulseAudio → sounddevice の順で自動検出
- **VAD**: webrtcvad によるセグメンテーション（発話区間の検出・分割）
- **文字起こし**: faster-whisper（CPU, int8）。モデルサイズは tiny/base/small/medium/large-v3 から選択
- **出力**: タイムスタンプ・スピーカーラベル付きで transcript ファイルに追記
  - デフォルト: `transcript-YYYYMMDD.txt`（日付が変わったら自動で新ファイルに切り替え）
  - 会議セッション中: `transcript-YYYYMMDDHHMM.txt`
  - 形式: `[YYYY-MM-DD HH:MM:SS] [自分/相手] テキスト`
- **words.txt**: TSV 形式の単語置換リスト。音声認識のよくある誤認識を自動修正。ファイル変更時は自動再読み込み
- **コマンドインターフェース**: `.clerk_command` ファイル経由で以下を受付
  - `set_language <lang>` / `unset_language` — 言語切り替え
  - `set_model <size>` — Whisper モデル切り替え（ランタイム再ロード）
  - `start_meeting` / `end_meeting` — 会議セッション管理
  - `translate_start` / `translate_stop` — 翻訳ループ開始・停止（`llm_provider: api` 時は clerk_daemon.py が直接処理、`claude` 時は SKILL.md 向けにファイルを残す）
- **音声コマンド**: マイク入力から音声コマンドを検出・実行。2つの方式がある:
  - **Push-to-Talk（推奨）**: `voice_command_key`（デフォルト: Menu キー）を押しながら発話すると、プレフィックスなしでコマンドとして認識される。Whisper の「クラーク」誤認識問題を回避できる
  - **プレフィックス方式（フォールバック）**: 「clerk」または「クラーク」に続けてコマンドを発話する
  - 「クラーク、会議開始」/ "clerk, start meeting" — 会議セッション開始
  - 「クラーク、会議終了」/ "clerk, end meeting" — 会議セッション終了
  - 「クラーク、言語 日本語」/ "clerk, language ja" — 言語を日本語に切り替え
  - 「クラーク、言語 英語」/ "clerk, language en" — 言語を英語に切り替え
  - 「クラーク、言語設定なし」/ "clerk, unset language" — 言語を自動検出に戻す
  - 「クラーク、翻訳開始」/ "clerk, start translation" — 翻訳ループを開始
  - 「クラーク、翻訳停止」/ "clerk, stop translation" — 翻訳ループを停止
- **カスタム音声コマンド**: config.yaml の `custom_commands` リストで独自コマンドを登録できる
  - `pattern`: 正規表現（IGNORECASE で適用）
  - `action`: シェルコマンド文字列（`subprocess.Popen(shell=True)` で実行）
  - 組み込みコマンドより低い優先度で評価される
  - 例: `{pattern: "youtube|ユーチューブ", action: "xdg-open https://www.youtube.com"}`
- **LLM フォールバック**: 組み込みコマンドにもカスタムコマンドにもマッチしない音声コマンドは、`api_endpoint` が設定されている場合に LLM にクエリとして送信される
  - `llm_client.py query` サブコマンドをバックグラウンドで実行
  - 結果は stdout に表示し、`.clerk_response` ファイルに保存

### モジュール B: SKILL.md（Claude Code Skill）

Claude Code の Skill として動作。transcript を読み議事録生成・翻訳を行う。

サブコマンド:
- `update` / 引数なし — 差分テキストから議事録(summary.md)を更新
- `full` — 全文から議事録を再生成
- `set language <lang>` — 文字起こし言語を切り替え
- `set model <size>` — Whisper モデルを切り替え
- `config show` — 設定を表示
- `config set <key> <value>` — 設定を変更
- `config init` — デフォルト設定ファイルを生成
- `start meeting` / `end meeting` — 会議セッション管理（auto_translate / auto_summary 連動）
- `start [opts]` — clerk_daemon.py をバックグラウンドで起動
- `stop` — clerk_daemon.py を停止
- `status` — 録音・文字起こしの状態表示
- `translate <lang>` — リアルタイム翻訳モード（ループで新行検出→翻訳→ファイル保存）
- `translate stop` — 翻訳モード停止
- `setup` — 必要な Bash permission を自動設定
- `help` — サブコマンド一覧表示

### モジュール C: llm_client.py（外部 API 翻訳・Summary 生成）

`llm_provider: api` の場合に使用する Python スクリプト。OpenAI Compatible API で翻訳と議事録生成を行う。

サブコマンド:
- `translate <lang>` — stdin から transcript 行を受け取り翻訳して stdout に出力
  - タイムスタンプ・スピーカーラベル保持、マーカー行はそのまま
  - 音声認識の誤認識を文脈から補正してから翻訳
- `query <prompt>` — LLM に自由形式のクエリを投げて回答を stdout に出力
  - 音声コマンドの LLM フォールバックから呼び出される
- `summarize --mode full --file <transcript>` — transcript 全文から議事録生成
- `summarize --mode update --file <transcript> --existing <summary>` — 既存 summary を踏まえた差分更新

設定:
- 起動時にデータディレクトリの `.env` ファイルを読み込み、環境変数にセットする（既存の環境変数は上書きしない）
- API キーは `os.environ[config["api_key_env"]]` から取得（config にキー自体は保存しない）
- ローカル API（Ollama 等）で認証不要の場合は `api_key_env: null` でダミーキーを使用

### clerk-util（データディレクトリ操作ラッパー）

データディレクトリ (`~/.claude/skills/shadow-clerk/data`) への操作を1つのシェルスクリプトに集約。
Claude Code の permission パターンを `Bash(<clerk-util のフルパス> *)` の1行で済ませる。
`config.yaml` の `output_directory` を自動参照し、`transcript-*`/`summary-*` ファイルは指定ディレクトリから解決する。

サブコマンド: `read`, `read-from`, `write`, `append`, `lines`, `size`, `mtime`, `exists`, `ls`, `command`, `recorder-status`, `read-config`, `write-config`, `path`

### モジュール D: Web ダッシュボード（clerk_daemon.py 内蔵）

clerk_daemon.py に統合された Web ダッシュボード。ブラウザから transcript・翻訳・ログのリアルタイム監視とコマンド送信が可能。

- **サーバー**: Python 標準ライブラリの `ThreadingHTTPServer` + SSE（Server-Sent Events）
- **ポート**: 8765（`--dashboard-port` で変更可能）
- **有効化**: デフォルトで有効（`--no-dashboard` で無効化）
- **エンドポイント**:
  - `GET /` — ダッシュボード HTML
  - `GET /api/events` — SSE イベントストリーム（transcript/translation/log/recorder_status/session/command/response/config）
  - `GET /api/status` — recorder 状態 JSON
  - `GET /api/files` — transcript ファイル一覧 + アクティブファイル
  - `GET /api/transcript?file=xxx` — transcript の末尾 50 行
  - `GET /api/translation?file=xxx` — 翻訳ファイルの末尾 50 行
  - `GET /api/logs` — ログ末尾 100 行
  - `POST /api/command` — コマンド送信（`.clerk_command` に書き込み）
- **UI**: ダークテーマ、transcript/翻訳パネル（speaker 色分け）、ログパネル、コマンドボタン

## アーキテクチャ図 (PlantUML)

### システム全体構成

```plantuml
@startuml system-overview
skinparam backgroundColor #FEFEFE
skinparam componentStyle rectangle

title Shadow-clerk システム全体構成

package "clerk_daemon.py" as recorder {
  [Audio Capture\n(Mic + Monitor)] as capture
  [VAD Segmenter\n(webrtcvad)] as vad
  [Transcriber\n(faster-whisper)] as transcriber
  [Voice Command\nDetector] as vcmd
  [Word Replacer\n(words.txt)] as replacer
  [Command Watcher\n(.clerk_command)] as cmdwatch
  [Key Listener\n(Push-to-Talk)] as ptt
  [Translate Loop] as translate
  [Dashboard Server\n(HTTP + SSE)] as dashboard
  [FileWatcher\n(SSE Broadcaster)] as filewatcher
}

package "Claude Code" as claude {
  [SKILL.md\n(議事録生成・翻訳)] as skill
  [clerk-util\n(データ操作)] as util
}

[llm_client.py\n(外部 API)] as llm
[i18n.py\n(多言語対応)] as i18n
[Browser\n(Dashboard UI)] as browser

database "Data Directory" as data {
  [transcript-*.txt] as transcript
  [summary-*.md] as summary
  [config.yaml] as config
  [.clerk_command] as clkcmd
  [.clerk_session] as session
  [words.txt] as words
  [glossary.txt] as glossary
}

capture --> vad : audio frames\n(Queue)
vad --> transcriber : segments\n(Queue)
transcriber --> vcmd : mic text
transcriber --> replacer : text
replacer --> transcript : append
vcmd --> llm : LLM fallback
cmdwatch --> clkcmd : poll
ptt --> vcmd : command_mode flag
translate --> llm : translate API
dashboard --> browser : SSE events
browser --> dashboard : POST /api/command
filewatcher --> transcript : poll diff
filewatcher --> browser : broadcast
skill --> util : subprocess
util --> data : read/write
llm --> config : read settings
llm --> glossary : load terms
i18n --> config : read ui_language
i18n --> recorder : t() / t_all()
i18n --> llm : t()

@enduml
```

### スレッドアーキテクチャ

```plantuml
@startuml thread-architecture
skinparam backgroundColor #FEFEFE

title clerk_daemon.py スレッドアーキテクチャ

rectangle "Main Thread\n(Recorder.run)" as main #LightBlue
rectangle "mic-capture" as mic #LightGreen
rectangle "monitor-capture" as mon #LightGreen
rectangle "vad-mic" as vadm #LightYellow
rectangle "vad-monitor" as vadmon #LightYellow
rectangle "transcribe" as trans #Orange
rectangle "interim-transcribe" as interim #LightCoral
rectangle "cmd-watch" as cmd #Plum
rectangle "key-listener" as key #Plum
rectangle "translate-loop" as tl #LightCyan
rectangle "file-watcher" as fw #Khaki
rectangle "dashboard-server" as dash #Pink

note right of mic : sounddevice InputStream
note right of mon : PipeWire/PulseAudio subprocess
note right of vadm : mic_queue -> VADSegmenter
note right of vadmon : monitor_queue -> VADSegmenter
note right of trans : faster-whisper + 音声コマンド検出
note right of interim : tiny model -> SSE broadcast
note right of cmd : .clerk_command ファイル監視
note right of key : pynput/evdev Push-to-Talk
note right of tl : transcript diff -> llm_client.py
note right of fw : ファイル差分検出 -> SSE broadcast
note right of dash : ThreadingHTTPServer port 8765

queue "mic_queue" as mq
queue "monitor_queue" as moq
queue "transcribe_queue" as tq
queue "interim_queue" as iq

main -[#blue]-> mic : spawn
main -[#blue]-> mon : spawn
main -[#blue]-> vadm : spawn
main -[#blue]-> vadmon : spawn
main -[#blue]-> trans : spawn
main -[#blue]-> interim : spawn
main -[#blue]-> cmd : spawn
main -[#blue]-> key : spawn
main -[#blue]-> fw : spawn
main -[#blue]-> dash : spawn

mic --> mq
mon --> moq
mq --> vadm
moq --> vadmon
vadm --> tq
vadmon --> tq
vadm ..> iq : if interim
vadmon ..> iq : if interim
tq --> trans
iq --> interim

note bottom of main
  stop_event.set() で
  全スレッドに停止を通知
end note

@enduml
```

### 音声キャプチャ → 文字起こしフロー

```plantuml
@startuml audio-to-transcript
skinparam backgroundColor #FEFEFE
skinparam sequenceMessageAlign center

title 音声キャプチャ → 文字起こし シーケンス図

participant "Microphone\nDevice" as Mic
participant "Monitor\nDevice" as Mon
participant "mic_queue /\nmonitor_queue" as Q
participant "VADSegmenter\n(webrtcvad)" as VAD
participant "transcribe_queue" as TQ
participant "Transcriber\n(faster-whisper)" as Whisper
participant "WordReplacer" as WR
participant "transcript\nファイル" as File
participant "FileWatcher" as FW
participant "Browser\n(Dashboard)" as Browser

== 音声キャプチャ ==

Mic -> Q : PCM frame (30ms, int16)\nvia sounddevice callback
Mon -> Q : PCM frame (30ms, int16)\nvia PipeWire/PulseAudio

== VAD セグメンテーション ==

Q -> VAD : frame
VAD -> VAD : webrtcvad.is_speech(frame)

alt 発話検出 (speech frames >= 10)
  VAD -> VAD : 音声フレームを蓄積

  alt 無音検出 (silence frames >= 30) or 最大30秒
    VAD -> TQ : (segment, timestamp,\nlabel, command_mode)
  end
end

== 文字起こし ==

TQ -> Whisper : segment
Whisper -> Whisper : model.transcribe(audio)
Whisper -> Whisper : ハルシネーション\nフィルタリング

alt label == "mic" かつ 音声コマンド検出
  Whisper -> Whisper : _check_voice_command()\nまたは _match_command_body()
  note right: 音声コマンドの場合は\nファイル書き込みをスキップ
else 通常の発話
  Whisper -> WR : text
  WR -> WR : words.txt で置換
  WR --> Whisper : corrected text
  Whisper -> File : append\n"[HH:MM:SS] [自分/相手] text"
  Whisper -> Whisper : print (ターミナル表示)
end

== ダッシュボード更新 ==

FW -> File : poll diff (1秒間隔)
FW -> Browser : SSE event: "transcript"\n{data: new lines}

@enduml
```

### 音声コマンド検出・実行フロー

```plantuml
@startuml voice-command-flow
skinparam backgroundColor #FEFEFE

title 音声コマンド検出・実行 シーケンス図

actor User
participant "KeyListener\n(pynput/evdev)" as Key
participant "VADSegmenter" as VAD
participant "Transcriber" as Trans
participant "VoiceCommand\nMatcher" as Match
participant "Recorder\n(_execute_command)" as Exec
participant "llm_client.py\n(match-command)" as LLM
participant "FileSystem" as FS

== Push-to-Talk 方式 ==

User -> Key : Menu キー押下
Key -> VAD : command_mode = True

User -> User : コマンド発話\n(例: "会議開始")
VAD -> Trans : (segment, command_mode=True)
Trans -> Trans : transcribe → "会議開始"
Trans -> Match : _match_command_body("会議開始")

alt 組み込みコマンドにマッチ
  Match --> Exec : "start_meeting"
else カスタムコマンドにマッチ
  Match --> Exec : "custom_exec <action>"
else LLM フォールバック
  Match -> LLM : match-command\n{text, commands}
  LLM --> Match : {command, confidence}
  alt confidence >= 80
    Match --> Exec : matched command
  else confidence < 80
    Match -> FS : アラート表示
  end
end

User -> Key : Menu キー離す
Key -> VAD : command_mode = False\n(1.5秒の猶予あり)

== プレフィックス方式 ==

User -> User : "クラーク、翻訳開始"
VAD -> Trans : (segment, command_mode=False)
Trans -> Trans : transcribe → "クラーク、翻訳開始"
Trans -> Match : _check_voice_command()
Match -> Match : VOICE_CMD_PREFIX regex で\n"クラーク" を除去
Match -> Match : 残り "翻訳開始" を\nVOICE_COMMANDS とマッチ
Match --> Exec : "translate_start"

== コマンド実行 ==

alt start_meeting
  Exec -> FS : 新規 transcript-YYYYMMDDHHMM.txt 作成
  Exec -> FS : .clerk_session に保存
  Exec -> FS : "--- 会議開始 ---" マーカー書き込み
else end_meeting
  Exec -> FS : "--- 会議終了 ---" マーカー書き込み
  Exec -> FS : .clerk_session 削除
  Exec -> FS : output_path をデフォルトに戻す
else set_language <lang>
  Exec -> Trans : language = lang
else translate_start
  Exec -> Exec : _translate_loop スレッド起動\nまたは .clerk_command に書き込み
else custom_exec
  Exec -> FS : subprocess.Popen(action, shell=True)
end

@enduml
```

### ダッシュボード通信フロー

```plantuml
@startuml dashboard-communication
skinparam backgroundColor #FEFEFE

title ダッシュボード SSE 通信 シーケンス図

participant "Browser" as B
participant "DashboardHandler\n(HTTP Server)" as DH
participant "FileWatcher" as FW
participant "Recorder" as Rec
participant "transcript\nファイル" as TF
participant "config.yaml" as Cfg

== 初期ロード ==

B -> DH : GET /
DH -> DH : _serve_html()\ni18n プレースホルダ展開\nI18N JSON 注入
DH --> B : HTML + JS + CSS

B -> DH : GET /api/status
DH --> B : {running, session, model, language}

B -> DH : GET /api/files
DH --> B : {transcript_files, translation_files, active}

B -> DH : GET /api/transcript?file=xxx
DH --> B : 末尾 50 行

== SSE 接続 ==

B -> DH : GET /api/events
DH -> FW : add_client(client_queue)
note right of FW: 1秒間隔でポーリング

loop FileWatcher._poll() (1秒ごと)
  FW -> TF : ファイルサイズ確認

  alt 新しい行がある
    FW -> TF : 差分を読み取り
    FW -> B : SSE "transcript"\n{file, content}
  end

  FW -> Cfg : mtime 確認
  alt 設定変更あり
    FW -> B : SSE "config"\n{yaml content}
  end
end

== コマンド送信 ==

B -> DH : POST /api/command\n{command: "start_meeting"}
DH -> Rec : _execute_command("start_meeting")
Rec -> TF : 新セッションファイル作成
FW -> B : SSE "session"\n{file: "transcript-..."}

== 設定変更 ==

B -> DH : POST /api/config\n{yaml content}
DH -> Cfg : ファイル書き込み
FW -> B : SSE "config"

note over B
  ui_language 変更時は
  location.reload() で
  ページ再読み込み
end note

== 議事録生成 ==

B -> DH : POST /api/summary\n{file: "transcript-..."}
DH -> DH : subprocess:\nllm_client.py summarize
DH --> B : {summary content}

@enduml
```

### 会議セッションライフサイクル

```plantuml
@startuml meeting-lifecycle
skinparam backgroundColor #FEFEFE

title 会議セッション ライフサイクル

actor "ユーザー" as User
participant "Recorder" as Rec
participant "Transcriber" as Trans
participant "Translate Loop" as TL
participant "llm_client.py" as LLM
participant "FileSystem" as FS
participant "FileWatcher" as FW
participant "Browser" as B
participant "Claude Code\n(SKILL.md)" as Skill

== 録音開始 (常時) ==

User -> Rec : uv run python clerk_daemon.py\n(または /shadow-clerk start)
Rec -> Rec : スレッド群を起動
Rec -> FS : transcript-YYYYMMDD.txt に追記開始

== 会議開始 ==

User -> Rec : 音声: "会議開始"\n(PTT or プレフィックス)
Rec -> FS : transcript-YYYYMMDDHHMM.txt 作成
Rec -> FS : "--- 会議開始 YYYY-MM-DD HH:MM ---" 書き込み
Rec -> FS : .clerk_session にパス保存
FW -> B : SSE "session"

alt auto_translate: true
  Rec -> TL : _translate_loop スレッド起動
  note right: config.yaml の\ntranslate_language を使用
end

== 会議中 ==

loop 発話ごと
  Trans -> FS : "[HH:MM:SS] [自分/相手] text" 追記
  FW -> B : SSE "transcript"

  opt 翻訳ループ動作中
    TL -> FS : transcript 差分を読み取り
    TL -> LLM : translate API
    LLM --> TL : 翻訳テキスト
    TL -> FS : transcript-YYYYMMDDHHMM-ja.txt に追記
    FW -> B : SSE "translation"
  end
end

== 会議終了 ==

User -> Rec : 音声: "会議終了"
Rec -> FS : "--- 会議終了 ---" 書き込み

opt auto_translate: true
  Rec -> TL : translate_stop_event.set()
  TL -> TL : ループ終了
end

Rec -> FS : output_path をデフォルトに戻す
Rec -> FS : .clerk_session 削除
FW -> B : SSE "session" (空)

opt auto_summary: true かつ api_endpoint 設定済み
  Rec -> LLM : summarize --mode full\n--file transcript-YYYYMMDDHHMM.txt
  LLM --> Rec : 議事録テキスト
  Rec -> FS : summary-YYYYMMDDHHMM.md 保存
end

== 録音継続 ==

note over Rec
  会議終了後も transcript-YYYYMMDD.txt
  への追記は継続される
end note

== 議事録生成 (手動) ==

User -> Skill : /shadow-clerk update
Skill -> FS : transcript 差分を読み取り
Skill -> Skill : 既存 summary を踏まえ\n議事録を更新
Skill -> FS : summary-YYYYMMDD.md 保存

@enduml
```

### グレースフルシャットダウン

```plantuml
@startuml graceful-shutdown
skinparam backgroundColor #FEFEFE

title グレースフルシャットダウン シーケンス図

actor "ユーザー" as User
participant "Signal Handler" as Sig
participant "Main Thread\n(Recorder.run)" as Main
participant "mic-capture" as Mic
participant "monitor-capture" as Mon
participant "vad-mic /\nvad-monitor" as VAD
participant "transcribe" as Trans
participant "cmd-watch /\nkey-listener" as Aux
participant "dashboard\nserver" as Dash

User -> Sig : Ctrl+C (SIGINT)\nまたは SIGTERM

Sig -> Main : stop_event.set()
note right of Main: 全スレッドが\nstop_event を参照

Main -> Main : ループ脱出

par 全スレッドが停止を検知
  Main -> Mic : stop_event 検知 → 終了
  Main -> Mon : stop_event 検知 → 終了
  Main -> VAD : stop_event 検知\n→ flush() で残余セグメント出力\n→ 終了
  Main -> Trans : stop_event 検知\n→ キュー残りを処理\n→ 終了
  Main -> Aux : stop_event 検知 → 終了
  Main -> Dash : shutdown()
end

Main -> Main : for th in threads:\n  th.join(timeout=5.0)

Main -> Main : logger.info\n("Recorder shutdown complete")

@enduml
```

## データディレクトリ

`~/.claude/skills/shadow-clerk/data/` にランタイムデータを保存する（`output_directory` 設定時、transcript/summary は指定ディレクトリに保存）:

| ファイル | 説明 |
|---|---|
| `transcript-YYYYMMDD.txt` | デフォルトの文字起こしファイル（日付ベース） |
| `transcript-YYYYMMDDHHMM.txt` | 会議セッション用 transcript |
| `transcript-YYYYMMDD-<lang>.txt` | 翻訳結果ファイル |
| `summary-YYYYMMDD.md` | 議事録（transcript に対応） |
| `summary-YYYYMMDDHHMM.md` | 会議セッション用議事録 |
| `words.txt` | 単語置換リスト (TSV) |
| `.clerk_session` | アクティブな会議セッションのファイルパス |
| `.clerk_command` | clerk_daemon.py へのコマンド（一時ファイル） |
| `.transcript_offset` | 議事録生成用のバイトオフセット |
| `.translate_offset` | 翻訳用のバイトオフセット |
| `config.yaml` | 設定ファイル |
| `.clerk_response` | LLM フォールバックの回答（最新の1件） |
| `.env` | API キー等の環境変数（llm_client.py が読み込む） |

## 設定ファイル (config.yaml)

`~/.claude/skills/shadow-clerk/data/config.yaml` にユーザー設定を保存する。

```yaml
# shadow-clerk 設定
translate_language: ja        # 翻訳先言語 (ja/en/etc)
auto_translate: false         # start meeting 時に自動翻訳を開始
auto_summary: false           # end meeting 時に自動 summary 生成
default_language: null        # clerk_daemon.py のデフォルト言語 (null=自動検出)
default_model: small          # clerk_daemon.py のデフォルト Whisper モデル
output_directory: null        # transcript 出力先ディレクトリ (null=データディレクトリ)
llm_provider: claude          # 翻訳・Summary の LLM ("claude"=インライン / "api"=外部 API)
api_endpoint: null            # OpenAI Compatible API の base URL
api_model: null               # API モデル名 (gpt-4o, etc.)
api_key_env: SHADOW_CLERK_API_KEY  # API キーを格納する環境変数名
custom_commands: []               # カスタム音声コマンド (pattern + action のリスト)
initial_prompt: null              # Whisper の initial_prompt (音声認識のヒント語彙)
voice_command_key: menu        # Push-to-Talk キー (null=無効, ctrl_r/ctrl_l/alt_r/alt_l/shift_r/shift_l)
whisper_beam_size: 5           # Whisper beam size (1=高速, 5=高精度)
whisper_compute_type: int8     # 計算精度 (int8/float16/float32)
whisper_device: cpu            # デバイス (cpu/cuda)
ui_language: ja                # UI言語 (ja/en) — ダッシュボード・ターミナル出力・LLMプロンプトの言語
```

- clerk_daemon.py 起動時に config.yaml を読み込み、CLI 引数が未指定の場合のみ `default_model`、`default_language`、`output_directory` を適用する
- `start meeting` 実行時に `auto_translate: true` なら翻訳を自動開始する
- `end meeting` 実行時に `auto_translate` の翻訳を停止し、`auto_summary: true` なら議事録を自動生成する

## 依存関係

- Python 3.12+
- faster-whisper, sounddevice, webrtcvad, numpy, pyyaml, openai, pynput
- システム: libportaudio2, PipeWire or PulseAudio
- pynput が未インストールの場合、Push-to-Talk は無効（警告ログを出力し、従来のプレフィックス方式のみで動作）
