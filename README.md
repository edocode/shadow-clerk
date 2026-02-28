# Shadow-clerk

Web会議の音声をリアルタイムで録音・文字起こしし、Claude Code の Skill で議事録を生成するツール。

Ubuntu + PipeWire / PulseAudio 環境で動作する。

## セットアップ

### 1. システムパッケージ

```bash
sudo apt install libportaudio2 portaudio19-dev
```

### 2. Python 環境構築

```bash
cd shadow-clerk
uv venv
uv pip install -e .
```

### 3. Skill のシンボリックリンク（初回のみ）

```bash
ln -s "$(pwd)/skills" ~/.claude/skills/shadow-clerk
```

## 使い方

### 録音・文字起こし

```bash
# 基本（マイク + システム音声を録音、自動文字起こし）
uv run python recorder.py

# デバイス一覧を確認
uv run python recorder.py --list-devices

# オプション指定
uv run python recorder.py \
  --language ja \
  --model small \
  --output ~/my-transcript.txt \
  --verbose
```

録音中は `Ctrl+C` で停止する。

### 音声コマンド

#### Push-to-Talk（推奨）

Menu キー（右 Alt の隣）を押しながらコマンドを発話すると、プレフィックス（「クラーク」）なしでコマンドとして認識される。Whisper の「クラーク」誤認識問題を回避できる:

```
[Menu キー押しながら] 「翻訳開始」 → 翻訳が開始される
[Menu キー押しながら] 「会議開始」 → 会議セッションが開始される
```

トリガーキーは `config.yaml` の `voice_command_key` で変更できる（`ctrl_r`, `ctrl_l`, `alt_r`, `alt_l`, `shift_r`, `shift_l`）。`null` に設定すると無効化される。

#### プレフィックス方式（フォールバック）

録音中にマイクに向かって「クラーク」（または "clerk"）に続けてコマンドを発話すると、ハンズフリーで操作できる:

| 発話例 | 動作 |
|---|---|
| 「クラーク、会議開始」 | 新しい会議セッションを開始 |
| 「クラーク、会議終了」 | 会議セッションを終了 |
| 「クラーク、言語 日本語」 | 文字起こし言語を日本語に切り替え |
| 「クラーク、言語 英語」 | 文字起こし言語を英語に切り替え |
| 「クラーク、言語設定なし」 | 言語を自動検出に戻す |
| 「クラーク、翻訳開始」 | 翻訳ループを開始 |
| 「クラーク、翻訳停止」 | 翻訳ループを停止 |

プレフィックスとコマンドの間の区切り（カンマ、読点、スペース）は省略可能。

#### カスタム音声コマンド

`config.yaml` の `custom_commands` に独自の音声コマンドを登録できる。組み込みコマンドにマッチしない場合に順番に評価される:

```yaml
custom_commands:
  - pattern: "youtube|ユーチューブ"
    action: "xdg-open https://www.youtube.com"
  - pattern: "gmail|メール"
    action: "xdg-open https://mail.google.com"
```

- `pattern`: 正規表現（大文字小文字を区別しない）
- `action`: 実行するシェルコマンド

#### LLM フォールバック

組み込みコマンドにもカスタムコマンドにもマッチしない場合、`api_endpoint` が設定されていれば LLM にクエリとして送信される。回答は stdout に表示され、`.clerk_response` ファイルに保存される。

```
「クラーク、1+1の答えは？」 → LLM が回答を返す
```

### CLI オプション

| オプション | 説明 | デフォルト |
|---|---|---|
| `--output`, `-o` | 出力ファイルパス | `~/.claude/skills/shadow-clerk/data/transcript-YYYYMMDD.txt` |
| `--model`, `-m` | Whisper モデルサイズ (`tiny`, `base`, `small`, `medium`, `large-v3`) | `small` |
| `--language`, `-l` | 言語コード (`ja`, `en` 等)。省略で自動検出 | 自動 |
| `--mic` | マイクデバイス番号 | 自動検出 |
| `--monitor` | モニターデバイス番号 (sounddevice) | 自動検出 |
| `--backend` | 音声バックエンド (`auto`, `pipewire`, `pulseaudio`, `sounddevice`) | `auto` |
| `--list-devices` | デバイス一覧を表示して終了 | - |
| `--verbose`, `-v` | 詳細ログ出力 | - |

### 議事録生成 (Claude Code Skill)

Claude Code から recorder.py の起動・停止・議事録生成を行える:

```
/shadow-clerk start                    # recorder.py をバックグラウンドで起動
/shadow-clerk start --language ja      # オプション付きで起動
/shadow-clerk stop                     # recorder.py を停止
/shadow-clerk          # 差分テキストから議事録を更新
/shadow-clerk full     # 全文から議事録を再生成
/shadow-clerk status   # 現在の状態を確認
```

生成された議事録は `~/.claude/skills/shadow-clerk/data/summary-YYYYMMDD.md` に保存される。

### 設定ファイル

`~/.claude/skills/shadow-clerk/data/config.yaml` でデフォルト値や自動機能を設定できる:

```yaml
# shadow-clerk 設定
translate_language: ja        # 翻訳先言語 (ja/en/etc)
auto_translate: false         # start meeting 時に自動翻訳を開始
auto_summary: false           # end meeting 時に自動 summary 生成
default_language: null        # recorder.py のデフォルト言語 (null=自動検出)
default_model: small          # recorder.py のデフォルト Whisper モデル
output_directory: null        # transcript 出力先ディレクトリ (null=データディレクトリ)
llm_provider: claude          # 翻訳・Summary の LLM ("claude" or "api")
api_endpoint: null            # OpenAI Compatible API の base URL
api_model: null               # API モデル名 (gpt-4o, etc.)
api_key_env: SHADOW_CLERK_API_KEY  # API キーを格納する環境変数名
custom_commands: []               # カスタム音声コマンド (pattern + action のリスト)
initial_prompt: null              # Whisper の initial_prompt (音声認識のヒント語彙)
voice_command_key: menu        # Push-to-Talk キー (null=無効)
```

Claude Code から設定を操作:

```
/shadow-clerk config show                     # 現在の設定を表示
/shadow-clerk config set default_model tiny   # 設定値を変更
/shadow-clerk config set auto_translate true  # 自動翻訳を有効化
/shadow-clerk config init                     # デフォルト設定ファイルを生成
```

`auto_translate: true` にすると、`/shadow-clerk start meeting` 時に自動で翻訳が開始される。
`auto_summary: true` にすると、`/shadow-clerk end meeting` 時に自動で議事録が生成される。

### 外部 API モード

`llm_provider: api` に設定すると、翻訳と議事録生成を OpenAI Compatible API 経由で実行できる。Claude Code 以外の LLM（OpenAI、Ollama 等）で処理したい場合に使う。

```
# OpenAI の場合
/shadow-clerk config set llm_provider api
/shadow-clerk config set api_endpoint https://api.openai.com/v1
/shadow-clerk config set api_model gpt-4o
# API キーは ~/.claude/skills/shadow-clerk/data/.env に記載:
#   SHADOW_CLERK_API_KEY=sk-...

# Ollama（ローカル）の場合
/shadow-clerk config set llm_provider api
/shadow-clerk config set api_endpoint http://localhost:11434/v1
/shadow-clerk config set api_model llama3
/shadow-clerk config set api_key_env null
```

## ファイル構成

```
shadow-clerk/                          # リポジトリ
  pyproject.toml                       # プロジェクト定義・依存関係
  recorder.py                          # 録音・VAD・文字起こし
  llm_client.py                        # 外部 API 翻訳・Summary 生成
  skills/
    SKILL.md                           # Claude Code Skill 定義
    clerk-data                         # データディレクトリ操作ラッパー
  SPEC.md                              # 設計仕様
  README.md                            # このファイル

~/.claude/skills/shadow-clerk/         # シンボリックリンク先
  data/                                # ランタイムデータ (実行時生成)
    transcript-YYYYMMDD.txt            # 文字起こし結果（日付ベース）
    transcript-YYYYMMDDHHMM.txt        # 会議セッション用
    transcript-YYYYMMDD-<lang>.txt     # 翻訳結果
    summary-YYYYMMDD.md                # 議事録（transcript に対応）
    words.txt                          # 単語置換リスト (TSV)
    config.yaml                        # 設定ファイル
    .clerk_session                     # アクティブセッション情報
    .transcript_offset                 # 議事録用オフセット
    .translate_offset                  # 翻訳用オフセット
```

## トラブルシューティング

### デバイスが見つからない

```bash
# デバイス一覧を確認
uv run python recorder.py --list-devices

# PipeWire が動作しているか確認
pw-cli info

# PulseAudio ソース一覧
pactl list short sources
```

### モニターソース（システム音声）が検出されない

PipeWire 環境では `pw-record --list-targets` で monitor デバイスを確認する。
PulseAudio 環境では `pactl list short sources` で `.monitor` を含むソースを確認する。

手動でデバイス番号を指定することもできる:

```bash
uv run python recorder.py --monitor 5
```

### PortAudio エラー

`libportaudio2` がインストールされているか確認:

```bash
dpkg -l | grep portaudio
```

### 文字起こしが遅い

`--model tiny` で軽量モデルを使う:

```bash
uv run python recorder.py --model tiny
```
