# Shadow-clerk

Web会議の音声をリアルタイムで録音・文字起こしするツール。翻訳や議事録生成もできる。

Ubuntu + PipeWire / PulseAudio 環境で動作する。

## 機能と必要なもの

| 機能 | 必要なもの | 品質 | 速度 | 関連設定 |
|---|---|:---:|:---:|---|
| 文字起こし (標準) | faster-whisper（パッケージに含む） | 3 | 4 | `default_model`, `default_language` |
| 文字起こし (Kotoba-Whisper) | 同上（初回に自動DL） | 5 | 3 | `japanese_asr_model: kotoba-whisper` |
| 文字起こし (ReazonSpeech) | `uv sync --extra reazonspeech` | 5 | 4 | `japanese_asr_model: reazonspeech-k2` |
| 中間文字起こし | 同上 | 2 | 5 | `interim_transcription: true`, `interim_model` |
| 翻訳 (LibreTranslate) | LibreTranslate サーバー | 2 | 4 | `translation_provider: libretranslate` |
| 翻訳 (OpenAI 互換 API) | OpenAI 互換 API | 3-5 | 2-5 | `translation_provider: api`, `api_endpoint`, `api_model` |
| 翻訳 (Claude) | Claude Code | 5 | 2 | `translation_provider: claude` |
| 要約 (Claude) | Claude Code | 5 | 3 | `llm_provider: claude` |
| 要約 (OpenAI 互換 API) | OpenAI 互換 API | 3-5 | 2-5 | `llm_provider: api`, `api_endpoint`, `api_model` |
| 音声コマンド (PTT) | なし（組み込み） | — | — | `voice_command_key` |
| 音声コマンド (LLM マッチング) | OpenAI 互換 API | — | — | `api_endpoint`, `api_model` |
| 誤字訂正 (翻訳前) | transformers（初回に自動DL） | — | — | `libretranslate_spell_check: true` |

**LLM なしで使える最小構成:** 文字起こし + LibreTranslate 翻訳であれば、外部 API や Claude Code は不要。すべてローカルで完結する。

スクリーンショット付きの機能紹介は [Feature Tour](docs/feature-tour.md) を参照。

## セットアップ

### 1. システムパッケージ

```bash
sudo apt install libportaudio2 portaudio19-dev
```

### 2. インストール

```bash
uv tool install shadow-clerk
```

ReazonSpeech 対応版（日本語高精度 ASR）:

```bash
uv tool install "shadow-clerk[reazonspeech]" \
  --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"
```

> **注意:** extras なしでインストール済みの場合、後から extras を追加するには `--force` で再インストールが必要:
> ```bash
> uv tool install --force --editable ".[spell-check]"
> ```
> `--force` なしでは「already installed」と表示され、extra が追加されません。

開発用:

```bash
cd shadow-clerk
uv sync                         # 基本
uv sync --extra reazonspeech    # ReazonSpeech 対応
```

これだけで文字起こし機能が使える。以下のオプション extras も利用可能:

### オプション: 日本語 ASR モデル

**Kotoba-Whisper** — 追加インストール不要。初回使用時にモデルが自動ダウンロードされる:

```yaml
# config.yaml
japanese_asr_model: kotoba-whisper
```

**ReazonSpeech k2** — `reazonspeech` extra が必要:

```bash
uv tool install "shadow-clerk[reazonspeech]" \
  --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"
# 開発用:
uv sync --extra reazonspeech
```

```yaml
# config.yaml
japanese_asr_model: reazonspeech-k2
```

### オプション: 誤字訂正（翻訳前補正）

`spell-check` extra が必要（`transformers`, `torch`, `sentencepiece` をインストール）:

```bash
uv tool install "shadow-clerk[spell-check]"
# 開発用:
uv sync --extra spell-check
```

```yaml
# config.yaml
libretranslate_spell_check: true
spell_check_model: mbyhphat/t5-japanese-typo-correction  # デフォルト
```

誤字訂正モデルは初回使用時に自動ダウンロードされる。音声認識の誤字を補正してから LibreTranslate に送信する。

翻訳・要約が必要な場合は以下のオプションを追加する。

### 3. (オプション) LibreTranslate のセットアップ

LLM 不要のローカル翻訳。Docker またはpip でインストール:

```bash
# Docker（推奨）
docker run -d -p 5000:5000 libretranslate/libretranslate

# または pip
pip install libretranslate
libretranslate --host 0.0.0.0 --port 5000
```

設定:

```yaml
# config.yaml
translation_provider: libretranslate
libretranslate_endpoint: http://localhost:5000
```

### 4. (オプション) OpenAI 互換 API のセットアップ

翻訳・要約・音声コマンドの LLM マッチングに使用:

```yaml
# config.yaml — OpenAI の場合
llm_provider: api
api_endpoint: https://api.openai.com/v1
api_model: gpt-4o
# ~/.local/share/shadow-clerk/.env に SHADOW_CLERK_API_KEY=sk-... を記載
```

```yaml
# config.yaml — Ollama（ローカル）の場合
llm_provider: api
api_endpoint: http://localhost:11434/v1
api_model: llama3
```

### 5. (オプション) Claude Code Skill の登録

Claude Code から議事録生成・翻訳・操作を行う場合:

```bash
clerk-util claude-setup
```

`~/.claude/skills/shadow-clerk/SKILL.md` が生成され、`~/.claude/settings.local.json` に permission が追加される。

## 使い方

### デーモンの起動

`uv tool install` でインストールした場合:

```bash
clerk-daemon
```

開発用（`uv sync`）の場合:

```bash
uv run clerk-daemon
```

> **注意:** `uv run` はプロジェクトの `.venv` を、`uv tool install` は専用の隔離環境を使用します。extras（`spell-check`, `reazonspeech` など）は対応する環境にインストールしてください。

### 録音・文字起こし

```bash
# 基本（マイク + システム音声を録音、自動文字起こし）
clerk-daemon

# デバイス一覧を確認
clerk-daemon --list-devices

# オプション指定
clerk-daemon \
  --language ja \
  --model small \
  --output ~/my-transcript.txt \
  --verbose
```

録音中は `Ctrl+C` で停止する。

### 音声コマンド

#### Push-to-Talk（推奨）

Menu キー（右 Alt の隣）を押しながらコマンドを発話すると、ウェイクワードなしでコマンドとして認識される:

```
[Menu キー押しながら] 「翻訳開始」 → 翻訳が開始される
[Menu キー押しながら] 「会議開始」 → 会議セッションが開始される
```

トリガーキーは `config.yaml` の `voice_command_key` で変更できる（`ctrl_r`, `ctrl_l`, `alt_r`, `alt_l`, `shift_r`, `shift_l`）。`null` に設定すると無効化される。

#### プレフィックス方式（フォールバック）

録音中にマイクに向かってウェイクワード（デフォルト「シェルク」）に続けてコマンドを発話すると、ハンズフリーで操作できる:

| 発話例 | 動作 |
|---|---|
| 「シェルク、会議開始」 | 新しい会議セッションを開始 |
| 「シェルク、会議終了」 | 会議セッションを終了 |
| 「シェルク、言語 日本語」 | 文字起こし言語を日本語に切り替え |
| 「シェルク、言語 英語」 | 文字起こし言語を英語に切り替え |
| 「シェルク、言語設定なし」 | 言語を自動検出に戻す |
| 「シェルク、翻訳開始」 | 翻訳ループを開始 |
| 「シェルク、翻訳停止」 | 翻訳ループを停止 |

ウェイクワードは `config.yaml` の `wake_word` で変更できる。

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
「シェルク、1+1の答えは？」 → LLM が回答を返す
```

### CLI オプション

| オプション | 説明 | デフォルト |
|---|---|---|
| `--output`, `-o` | 出力ファイルパス | `~/.local/share/shadow-clerk/transcript-YYYYMMDD.txt` |
| `--model`, `-m` | Whisper モデルサイズ (`tiny`, `base`, `small`, `medium`, `large-v3`) | `small` |
| `--language`, `-l` | 言語コード (`ja`, `en` 等)。省略で自動検出 | 自動 |
| `--mic` | マイクデバイス番号 | 自動検出 |
| `--monitor` | モニターデバイス番号 (sounddevice) | 自動検出 |
| `--backend` | 音声バックエンド (`auto`, `pipewire`, `pulseaudio`, `sounddevice`) | `auto` |
| `--list-devices` | デバイス一覧を表示して終了 | - |
| `--verbose`, `-v` | 詳細ログ出力 | - |
| `--dashboard` / `--no-dashboard` | ダッシュボード有効/無効 | 有効 |
| `--dashboard-port` | ダッシュボードポート番号 | `8765` |
| `--beam-size` | Whisper beam size (`1`=高速, `5`=高精度) | `5` |
| `--compute-type` | Whisper 計算精度 (`int8`, `float16`, `float32`) | `int8` |
| `--device` | Whisper デバイス (`cpu`, `cuda`) | `cpu` |

### 議事録生成 (Claude Code Skill)

Claude Code から clerk-daemon の起動・停止・議事録生成を行える:

```
/shadow-clerk start                    # clerk-daemon をバックグラウンドで起動
/shadow-clerk start --language ja      # オプション付きで起動
/shadow-clerk stop                     # clerk-daemon を停止
/shadow-clerk          # 差分テキストから議事録を更新
/shadow-clerk full     # 全文から議事録を再生成
/shadow-clerk status   # 現在の状態を確認
```

生成された議事録は `~/.local/share/shadow-clerk/summary-YYYYMMDD.md` に保存される。

### 設定ファイル

`~/.local/share/shadow-clerk/config.yaml` でデフォルト値や自動機能を設定できる:

```yaml
# shadow-clerk 設定
translate_language: en        # 翻訳先言語 (ja/en/etc)
auto_translate: false         # start meeting 時に自動翻訳を開始
auto_summary: false           # end meeting 時に自動 summary 生成
default_language: null        # clerk-daemon のデフォルト言語 (null=自動検出)
default_model: small          # clerk-daemon のデフォルト Whisper モデル
output_directory: null        # transcript 出力先ディレクトリ (null=データディレクトリ)
llm_provider: claude          # 要約の LLM ("claude" or "api")
translation_provider: null    # 翻訳プロバイダ (null=llm_provider を使用, "claude", "api", "libretranslate")
api_endpoint: null            # OpenAI Compatible API の base URL
api_model: null               # API モデル名 (gpt-4o, etc.)
api_key_env: SHADOW_CLERK_API_KEY  # API キーを格納する環境変数名
summary_source: transcript    # 要約ソース ("transcript" or "translate")
libretranslate_endpoint: null     # LibreTranslate API URL (例: http://localhost:5000)
libretranslate_api_key: null      # LibreTranslate API キー (不要なら null)
libretranslate_spell_check: false # LibreTranslate 翻訳前の誤字訂正
spell_check_model: mbyhphat/t5-japanese-typo-correction  # 誤字訂正モデル
custom_commands: []               # カスタム音声コマンド (pattern + action のリスト)
initial_prompt: null              # Whisper の initial_prompt (音声認識のヒント語彙)
voice_command_key: f23         # Push-to-Talk キー (null=無効)
wake_word: シェルク              # ウェイクワード（音声コマンドのトリガーワード）
whisper_beam_size: 5           # Whisper beam size (1=高速, 5=高精度)
whisper_compute_type: int8     # 計算精度 (int8/float16/float32)
whisper_device: cpu            # デバイス (cpu/cuda)
interim_transcription: false   # 中間文字起こし（発話中にリアルタイム表示）
interim_model: base            # 中間文字起こし用モデル
japanese_asr_model: default    # 日本語 ASR モデル (default/kotoba-whisper/reazonspeech-k2)
kotoba_whisper_model: kotoba-tech/kotoba-whisper-v2.0-faster  # Kotoba-Whisper モデル
interim_japanese_asr_model: default  # 中間文字起こし用の日本語 ASR モデル
ui_language: ja                # UI言語 (ja/en) — ダッシュボード・ターミナル出力・LLMプロンプト
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

### 翻訳ファイルからの要約生成

デフォルトでは transcript から要約を生成する。`summary_source: translate` に設定すると、翻訳ファイルから要約を生成できる:

```
/shadow-clerk config set summary_source translate
```

## ファイル構成

```
shadow-clerk/                          # リポジトリ
  pyproject.toml                       # プロジェクト定義・依存関係
  src/shadow_clerk/                    # メインパッケージ
    __init__.py                        # データディレクトリ設定
    clerk_daemon.py                    # 録音・VAD・文字起こし・ダッシュボード
    llm_client.py                      # 外部 API 翻訳・Summary 生成
    i18n.py                            # 多言語対応 (ja/en)
    clerk_util.py                      # データディレクトリ操作・プロセス管理
    data/
      SKILL.md.template                # Claude Code Skill テンプレート
  skills/
    SKILL.md                           # Claude Code Skill 定義（開発用）

~/.local/share/shadow-clerk/           # ランタイムデータ
  transcript-YYYYMMDD.txt              # 文字起こし結果（日付ベース）
  transcript-YYYYMMDDHHMM.txt          # 会議セッション用
  transcript-YYYYMMDD-<lang>.txt       # 翻訳結果
  summary-YYYYMMDD.md                  # 議事録（transcript に対応）
  glossary.txt                         # 用語集 (TSV: 翻訳用語 & reading ベースのテキスト置換)
  glossary.txt                         # 翻訳用語集 (TSV)
  config.yaml                          # 設定ファイル
```

## トラブルシューティング

### デバイスが見つからない

```bash
# デバイス一覧を確認
clerk-daemon --list-devices

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
clerk-daemon --monitor 5
```

### PortAudio エラー

`libportaudio2` がインストールされているか確認:

```bash
dpkg -l | grep portaudio
```

`PortAudioError: Error initializing PortAudio: ... PulseAudio_Initialize: Can't connect to server` と表示される場合、PulseAudio 互換サービスがクラッシュしている可能性がある。PipeWire 環境では `pipewire-pulse` を再起動する:

```bash
systemctl --user restart pipewire-pulse
```

### 文字起こしが遅い

`--model tiny` で軽量モデルを使う:

```bash
clerk-daemon --model tiny
```

### 日本語 ASR モデル

`japanese_asr_model` で `language=ja` 時に使用する ASR バックエンドを選択できる。言語が `ja` 以外に変わると自動的に標準 Whisper に戻る。

| 値 | モデル | 必要なもの | 日本語精度 | CPU速度 |
|---|---|---|---|---|
| `default` | 標準 Whisper | — | モデルサイズに依存 | モデルサイズに依存 |
| `kotoba-whisper` | [Kotoba-Whisper](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0) | 初回に自動DL | 高い（large-v3 相当） | medium 程度 |
| `reazonspeech-k2` | [ReazonSpeech k2](https://github.com/reazon-research/ReazonSpeech) | `uv sync --extra reazonspeech` | 高い | 速い |

**Kotoba-Whisper** は large-v3 のエンコーダ全体（32層）を持ちつつ、デコーダを2層に蒸留したモデル。デコーダが2層しかないため、**beam=5 でも速度への影響がほとんどない**。

**ReazonSpeech k2** は sherpa-onnx で推論する。選択時、Whisper 固有の設定（`default_model`, `whisper_beam_size`, `whisper_compute_type`, `initial_prompt`）は使用されない。

**選び方ガイド:**

| ユースケース | 設定 |
|---|---|
| 日本語メイン・精度重視 | `japanese_asr_model: kotoba-whisper`, `whisper_beam_size: 5` |
| 日本語メイン・高速＆高精度 | `japanese_asr_model: reazonspeech-k2` |
| 日本語メイン・速度重視 (CPU) | `japanese_asr_model: default`, `default_model: small`, `whisper_beam_size: 3` |
| 多言語 | `japanese_asr_model: kotoba-whisper`, `default_model: small`（ja 時は Kotoba、他は small） |

**中間文字起こし:**

`interim_japanese_asr_model` は中間文字起こし（発話中のリアルタイム表示）で使用する日本語 ASR モデルの設定。CPU 環境ではデフォルト（`default` + tiny/base 等の軽量モデル）を推奨。

```yaml
# 日本語精度重視（GPU 推奨）
japanese_asr_model: kotoba-whisper
interim_japanese_asr_model: kotoba-whisper
whisper_beam_size: 5

# 日本語精度重視 + 中間は速度重視（CPU 推奨）
japanese_asr_model: kotoba-whisper
interim_japanese_asr_model: default
interim_model: base
whisper_beam_size: 5        # Kotoba はデコーダ2層なので beam=5 でも軽い

# ReazonSpeech（高速＆高精度、CPU 向き）
japanese_asr_model: reazonspeech-k2
interim_japanese_asr_model: default
interim_model: base

# 速度最優先（CPU）
japanese_asr_model: default
default_model: small
interim_model: base
whisper_beam_size: 1
```
