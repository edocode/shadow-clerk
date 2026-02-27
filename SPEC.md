# Shadow-clerk 設計仕様

## 概要

Ubuntu 環境で Web会議の音声をリアルタイムで録音・文字起こしし、Claude Code の Skill で議事録生成・翻訳を行うシステム。

## アーキテクチャ

### モジュール A: recorder.py（録音・文字起こし）

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
- **音声コマンド**: マイク入力から音声コマンドを検出・実行。プレフィックス「clerk」または「クラーク」に続けてコマンドを発話する
  - 「クラーク、会議開始」/ "clerk, start meeting" — 会議セッション開始
  - 「クラーク、会議終了」/ "clerk, end meeting" — 会議セッション終了
  - 「クラーク、言語 日本語」/ "clerk, language ja" — 言語を日本語に切り替え
  - 「クラーク、言語 英語」/ "clerk, language en" — 言語を英語に切り替え
  - 「クラーク、言語設定なし」/ "clerk, unset language" — 言語を自動検出に戻す

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
- `start [opts]` — recorder.py をバックグラウンドで起動
- `stop` — recorder.py を停止
- `status` — 録音・文字起こしの状態表示
- `translate <lang>` — リアルタイム翻訳モード（ループで新行検出→翻訳→ファイル保存）
- `translate stop` — 翻訳モード停止
- `setup` — 必要な Bash permission を自動設定
- `help` — サブコマンド一覧表示

### clerk-data（データディレクトリ操作ラッパー）

データディレクトリ (`~/.claude/skills/shadow-clerk/data`) への操作を1つのシェルスクリプトに集約。
Claude Code の permission パターンを `Bash(<clerk-data のフルパス> *)` の1行で済ませる。

サブコマンド: `read`, `read-from`, `write`, `append`, `lines`, `size`, `mtime`, `exists`, `ls`, `command`, `recorder-status`, `read-config`, `write-config`, `path`

## データディレクトリ

`~/.claude/skills/shadow-clerk/data/` にすべてのランタイムデータを保存:

| ファイル | 説明 |
|---|---|
| `transcript-YYYYMMDD.txt` | デフォルトの文字起こしファイル（日付ベース） |
| `transcript-YYYYMMDDHHMM.txt` | 会議セッション用 transcript |
| `transcript-YYYYMMDD-<lang>.txt` | 翻訳結果ファイル |
| `summary-YYYYMMDD.md` | 議事録（transcript に対応） |
| `summary-YYYYMMDDHHMM.md` | 会議セッション用議事録 |
| `words.txt` | 単語置換リスト (TSV) |
| `.clerk_session` | アクティブな会議セッションのファイルパス |
| `.clerk_command` | recorder.py へのコマンド（一時ファイル） |
| `.transcript_offset` | 議事録生成用のバイトオフセット |
| `.translate_offset` | 翻訳用のバイトオフセット |
| `config.yaml` | 設定ファイル |

## 設定ファイル (config.yaml)

`~/.claude/skills/shadow-clerk/data/config.yaml` にユーザー設定を保存する。

```yaml
# shadow-clerk 設定
translate_language: ja        # 翻訳先言語 (ja/en/etc)
auto_translate: false         # start meeting 時に自動翻訳を開始
auto_summary: false           # end meeting 時に自動 summary 生成
default_language: null        # recorder.py のデフォルト言語 (null=自動検出)
default_model: small          # recorder.py のデフォルト Whisper モデル
output_directory: null        # transcript 出力先ディレクトリ (null=データディレクトリ)
```

- recorder.py 起動時に config.yaml を読み込み、CLI 引数が未指定の場合のみ `default_model`、`default_language`、`output_directory` を適用する
- `start meeting` 実行時に `auto_translate: true` なら翻訳を自動開始する
- `end meeting` 実行時に `auto_translate` の翻訳を停止し、`auto_summary: true` なら議事録を自動生成する

## 依存関係

- Python 3.12+
- faster-whisper, sounddevice, webrtcvad, numpy, pyyaml
- システム: libportaudio2, PipeWire or PulseAudio
