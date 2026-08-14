# Shadow-clerk

[![PyPI version](https://img.shields.io/pypi/v/shadow-clerk.svg)](https://pypi.org/project/shadow-clerk/)
[![Python versions](https://img.shields.io/pypi/pyversions/shadow-clerk.svg)](https://pypi.org/project/shadow-clerk/)

Web会議の音声をリアルタイムで録音・文字起こしするツール。翻訳や議事録生成もできる。

PyPI で公開中: <https://pypi.org/project/shadow-clerk/>

## 動作環境

| OS | 対応状況 | 備考 |
|----|----------|------|
| Linux (PipeWire/PulseAudio) | 対応 | 主開発ターゲット |
| Windows 10/11 | 対応 | WASAPI ループバックでモニターキャプチャ（既定の再生デバイスに追従） |
| macOS | 未対応 | 仮想オーディオドライバ（BlackHole 等）が必要 — 未実装 |

### Windows 固有の注意点

推奨インストール(Windows 用 dep を明示):

```powershell
uv python install 3.13
uv tool install --python 3.13 --with PyAudioWPatch "shadow-clerk[spell-check,gcal]"
# +ReazonSpeech k2(日本語 ASR、オプション):
uv tool install --python 3.13 --with PyAudioWPatch --with sherpa-onnx --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr" "shadow-clerk[spell-check,gcal,reazonspeech]"
```

`--python` と `--with` を明示する理由:

- **`--python 3.13`(uv 管理 Python)**: Microsoft Store 版 Python は AppContainer サンドボックスで動作し、`%APPDATA%\shadow-clerk` への書き込みが `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.X.YY_<id>\LocalCache\Roaming\shadow-clerk\` にリダイレクトされる。Python マイナーバージョン更新で package id が変わるとデータディレクトリが別パスに移り、過去の transcript/config が「消えた」状態になる。uv 管理 Python はサンドボックス外で動くので回避できる。daemon 起動時に Store Python を検知すると WARNING を出す。
- **`--with PyAudioWPatch`**: WASAPI ループバックモニターキャプチャに [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch) を使用。`pyproject.toml` で Windows 限定 dep として宣言してあるが、uv のバージョンによって local editable install から PEP 508 marker を確実に解決しない場合があるため明示するのが安全。
- **`--with sherpa-onnx`**(ReazonSpeech 利用時のみ): 同様の理由。Windows wheel(`onnxruntime.dll` 同梱)を確実に選ばせ、Linux wheel が誤って入って `libonnxruntime.so` が見つからなくなる事故を防ぐ。

その他:

- **マイク権限**: 起動するターミナルにマイクアクセスを許可する(Windows 設定 → プライバシーとセキュリティ → マイク)。
- **モニターキャプチャ**: WASAPI ループバックでシステムの既定の再生デバイスを録音。サウンド設定で既定デバイスを切り替えると、キャプチャ対象も切り替わる。
- **データディレクトリ**: `%APPDATA%\shadow-clerk`(README 内の `~/.local/share/shadow-clerk` は Windows ではこのパスにマップされる)。`SHADOW_CLERK_DATA_DIR` 環境変数で上書き可。
- **リモートデスクトップ(RDP)**: RDP セッション内で動作している場合、ホストの「リモート オーディオ」仮想デバイスは自動でスキップされる(セグフォするか何も拾えないため)。代わりに非 RDP の loopback デバイスがあればそれを使う。無い場合はモニターキャプチャ無効でマイクのみで動作する。
- **`voice_command_key`**: デフォルトの `f23` は Linux/xremap 用の慣習。Windows では `null`(PTT 無効)または `menu`/`ctrl_r`/`ctrl_l`/`alt_r`/`alt_l`/`shift_r`/`shift_l` のいずれかを `config.yaml` で設定する。
- **daemon の停止**: `clerk-util stop` が動作する(Windows では内部で `taskkill` を使用)。`clerk-util start` はフォアグラウンドで起動し Ctrl+C で停止できる(Linux と同じ挙動)。

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
| 言語検出（翻訳前） | langdetect（同梱） | — | — | 翻訳元言語を自動検出してプロンプトを切り替える |
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

PyPI からインストール:

|  | コマンド |
|---|---|
| 基本 | `uv tool install shadow-clerk` |
| + ReazonSpeech | `uv tool install "shadow-clerk[reazonspeech]" --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"` |
| + スペルチェック | `uv tool install "shadow-clerk[spell-check]"` |
| + 両方 (ReazonSpeech + スペルチェック) | `uv tool install "shadow-clerk[spell-check,reazonspeech]" --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"` |
| + Google Calendar | `uv tool install "shadow-clerk[gcal]"` |
| すべて | `uv tool install "shadow-clerk[spell-check,gcal,reazonspeech]" --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"` |

> **注意:** `uv tool install` はツールごとに1つの環境を管理します。異なる extras で再インストールする場合は `--force` を付けてください。`--force` なしでは「already installed」と表示され、extra が追加されません。指定した extras のみが含まれ、以前の extras は削除されます。

> **`reazonspeech-k2-asr` を `--with` で別途指定する理由:** `reazonspeech-k2-asr` は PyPI ではなく Git のみで配布されており、PyPI のメタデータには直接 URL 参照を書けないため `reazonspeech` extra に含められない。ReazonSpeech k2 を使う場合は常に `--with` で追加すること。

別の方法: `pipx install shadow-clerk` や venv 内で `pip install shadow-clerk` でも可。

### 2a. 開発用

```bash
git clone https://github.com/edocode/shadow-clerk.git
cd shadow-clerk
```

|  | コマンド |
|---|---|
| 基本 | `uv sync` |
| + ReazonSpeech | `uv sync --extra reazonspeech` |
| + スペルチェック | `uv sync --extra spell-check` |
| + 両方 (ReazonSpeech + スペルチェック) | `uv sync --extra spell-check --extra reazonspeech` |
| + Google Calendar | `uv sync --extra gcal` |
| すべて | `uv sync --extra spell-check --extra gcal --extra reazonspeech` |

これだけで文字起こし機能が使える。以下のオプション extras も利用可能:

### オプション: 日本語 ASR モデル

**Kotoba-Whisper** — 追加インストール不要。初回使用時にモデルが自動ダウンロードされる:

```yaml
# config.yaml
japanese_asr_model: kotoba-whisper
```

**ReazonSpeech k2** — `reazonspeech` extra と `reazonspeech-k2-asr` パッケージが必要。`reazonspeech-k2-asr` は PyPI ではなく Git でのみ配布されているため別途インストールが必要:

```bash
uv tool install "shadow-clerk[reazonspeech]" \
  --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"
# 開発用:
uv sync --extra reazonspeech
uv pip install "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"
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

### オプション: Google Calendar 連携

Google カレンダーのスケジュールに基づいて会議セッションを自動開始・終了する。`gcal` extra が必要:

```bash
uv tool install "shadow-clerk[gcal]"
# 開発用:
uv sync --extra gcal
```

認証と設定:

```bash
# 初回のみ OAuth 認証（ブラウザが開く）
clerk-util gcal-auth ~/credentials.json

# config を有効化（gcal-auth 成功時に自動設定される）
clerk-util write-config-value gcal_integration true
clerk-util write-config-value gcal_credentials_file ~/credentials.json
```

有効にすると、clerk-daemon が 60 秒ごとに Google カレンダーをポーリングする。予定時刻に `start_meeting` / `end_meeting` が自動送信され、`transcript-YYYYMMDDHHMM@予定タイトル.txt` として記録される。

`credentials.json` の取得方法は [docs/google-calendar-setup.md](docs/google-calendar-setup.md) を参照。

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

### 5. (オプション) Claude CLI を LLM プロバイダーとして使う

Claude Code (`claude` コマンドが `$PATH` 上にある状態) を翻訳・要約のバックエンドとして使う場合、`config.yaml` に:

```yaml
llm_provider: claude
claude_cli_model: haiku   # sonnet / opus / モデル ID も指定可
# claude_cli_path: claude  # PATH 上にない場合はフルパス
```

既存の Claude Code OAuth ログインをそのまま使う。追加セットアップ不要、翻訳・要約は daemon 内のバックグラウンドスレッドで実行されるので Claude Code セッションを開きっぱなしにする必要なし。

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
| `--mic` | マイクデバイス番号 | 自動検出（または `mic_device` 設定） |
| `--monitor` | モニターデバイス番号 (sounddevice) | 自動検出（または `monitor_device` 設定） |
| `--backend` | 音声バックエンド (`auto`, `pipewire`, `pulseaudio`, `sounddevice`) | `auto` |
| `--list-devices` | デバイス一覧を表示して終了 | - |
| `--verbose`, `-v` | 詳細ログ出力 | - |
| `--dashboard` / `--no-dashboard` | ダッシュボード有効/無効 | 有効 |
| `--dashboard-port` | ダッシュボードポート番号 | `8765` |
| `--beam-size` | Whisper beam size (`1`=高速, `5`=高精度) | `5` |
| `--compute-type` | Whisper 計算精度 (`int8`, `float16`, `float32`) | `int8` |
| `--device` | Whisper デバイス (`cpu`, `cuda`) | `cpu` |

### 翻訳・要約のプロバイダ

翻訳と要約にはそれぞれ複数のプロバイダを選択できる。プロバイダによって動作方式が異なる:

#### Claude モード (`translation_provider: claude` / `llm_provider: claude`)

clerk-daemon が `claude -p` を subprocess 起動して翻訳・要約を実行する。既存の Claude Code OAuth ログインをそのまま使う。

- **最も高品質** — 特に日本語の同音異義語修正（ja→ja）で顕著
- **`claude` コマンドが PATH 上にあること** — Claude Code をインストール済みなら自動で見つかる
- **Claude Code セッションは不要** — daemon が単独でジョブごとに `claude -p` を起動するので、ターミナルで Claude Code を開きっぱなしにする必要なし
- **翻訳・要約とも daemon 内のスレッドで完結** — api / libretranslate と同じ仕組み
- **コスト記録**: `claude -p --output-format json` のレスポンスから `total_cost_usd` を daemon ログに記録

```yaml
# config.yaml
translation_provider: claude   # 翻訳を Claude で実行
llm_provider: claude           # 要約を Claude で実行（デフォルト）
claude_cli_path: claude        # フルパス指定可（PATH 上にない場合）
claude_cli_model: haiku        # haiku / sonnet / opus または完全なモデル ID
```

#### API モード (`translation_provider: api` / `llm_provider: api`)

clerk-daemon が内部的に外部 API（OpenAI 互換）を呼び出して翻訳・要約を行う。Claude Code は不要。

- **Claude Code なしで動作** — clerk-daemon 単体で翻訳・要約が完結
- **品質はモデル依存** — GPT-4o 等の高性能モデルなら高品質、小型モデルでは日本語修正が弱い場合あり
- **翻訳の動作**: clerk-daemon 内部のスレッドが翻訳を処理。音声コマンドやダッシュボードからの指示で開始・停止
- **要約も同様**: `clerk-util summarize` コマンドで外部 API を使って議事録を生成

```yaml
# config.yaml
translation_provider: api     # 翻訳を外部 API で実行
llm_provider: api             # 要約を外部 API で実行
api_endpoint: https://api.openai.com/v1
api_model: gpt-4o
```

#### LibreTranslate モード (`translation_provider: libretranslate`)

翻訳のみ。ローカルで動作し、外部 API や Claude Code は不要（要約は別途 `llm_provider` で設定）。

#### 推奨構成

| 用途 | 翻訳 | 要約 | 特徴 |
|---|---|---|---|
| 高品質（Claude CLI） | `translation_provider: claude` | `llm_provider: claude` | 最高品質、`claude` コマンドが必要 |
| 自律動作（外部 API） | `translation_provider: api` | `llm_provider: api` | OpenAI 互換 API、品質はモデル依存 |
| ローカル完結 | `translation_provider: libretranslate` | — | LLM 不要、品質は低い |
| ハイブリッド | `translation_provider: api` | `llm_provider: claude` | 翻訳は自動、要約は高品質 |

### 議事録生成

会議終了時の自動生成、ダッシュボードからのオンデマンド生成、`clerk-util` からのコマンドライン生成、の3経路がある:

```
clerk-util start                                   # daemon 起動（バックグラウンド）
clerk-util stop                                    # daemon 停止
clerk-util recorder-status                         # 動作状態
clerk-util summarize                               # 差分から議事録を更新
clerk-util summarize --mode full                   # 全文から再生成
clerk-util summarize 20260425 --mode full          # 日付指定
clerk-util command start_meeting                   # 会議セッション開始
clerk-util command end_meeting                     # 会議セッション終了（auto_summary 連動）
clerk-util command translate_start                 # 翻訳ループ開始
clerk-util command translate_stop                  # 翻訳ループ停止
```

会議の開始・終了は **音声コマンド**（「シェルク、会議開始」「シェルク、会議終了」）または **ダッシュボードのボタン** からも操作可能。ダッシュボードの「要約生成」ボタンで任意のタイミングで議事録生成も可能。

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
mic_device: null              # マイクデバイス名 (null=OS デフォルトに追従。番号ではない — 番号は起動ごとに変わり、稼働中にも移動する)
monitor_device: null          # スピーカー（モニター）デバイス名 (null=OS デフォルトに追従)。ダッシュボードの設定パネルから選択できる
llm_provider: claude          # 要約の LLM ("claude" or "api")
translation_provider: null    # 翻訳プロバイダ (null=llm_provider を使用, "claude", "api", "libretranslate")
api_endpoint: null            # OpenAI Compatible API の base URL
api_model: null               # API モデル名 (gpt-4o, etc.)
api_key_env: SHADOW_CLERK_API_KEY  # API キーを格納する環境変数名
api_disable_thinking: false   # 翻訳・中間翻訳で reasoning モデルの思考を無効化 (Qwen3 等; enable_thinking=false を送信)。要約は常に思考する
summary_source: null          # 要約ソース (null=auto: translationがあれば優先 / "transcript" / "translate")
summary_language: null        # 要約の言語 (null=ui_language にフォールバック / ja, en, zh, ...)
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
interim_translation: true      # 中間文字起こしを翻訳して dashboard interim パネルに表示
interim_translation_provider: null  # null=自動 / "api" / "libretranslate" / "claude"
japanese_asr_model: default    # 日本語 ASR モデル (default/kotoba-whisper/reazonspeech-k2)
kotoba_whisper_model: kotoba-tech/kotoba-whisper-v2.0-faster  # Kotoba-Whisper モデル
interim_japanese_asr_model: default  # 中間文字起こし用の日本語 ASR モデル
reazonspeech_precision: fp32   # ReazonSpeech k2: fp32 / int8 / int8-fp32 (fp16 は無効)
ui_language: ja                # UI言語 (ja/en) — ダッシュボード・ターミナル出力・LLMプロンプト
```

Claude Code から設定を操作:

```
clerk-util read-config                                # 現在の設定を表示
clerk-util write-config-value default_model tiny      # 設定値を変更
clerk-util write-config-value auto_translate true     # 自動翻訳を有効化
```

`auto_translate: true` にすると、会議セッション開始時に自動で翻訳が開始される。
`auto_summary: true` にすると、会議セッション終了時に自動で議事録が生成される。

### 翻訳ファイルからの要約生成

`summary_source` が未指定 (null/auto) の場合、翻訳ファイルが存在すれば自動的にそれを要約ソースとして使う (なければ transcript にフォールバック)。明示的に挙動を固定したい場合:

```
clerk-util write-config-value summary_source transcript   # 強制的に transcript
clerk-util write-config-value summary_source translate    # 強制的に translation (無ければ transcript にフォールバック)
```

### 要約の言語

`summary_language` で要約の出力言語を指定する。未指定 (null) の場合は `ui_language` をデフォルトとして使用:

```
clerk-util write-config-value summary_language en   # 英語で要約
clerk-util write-config-value summary_language ja   # 日本語で要約
```

### 音声デバイスの選択

`mic_device` / `monitor_device` はデバイスを**名前**で固定する（番号ではない — 番号は daemon 起動ごとに変わり、稼働中にも移動しうる）。デフォルトの `null` は OS のデフォルトデバイスに追従する。ダッシュボードの設定パネルから選択できる。

指定したデバイスが見つからなくなった場合（抜線、シンク削除など）、daemon は自動デバイスにフォールバックして録音を継続し、デバイスが復帰すると自動で元に戻る。設定値はフォールバック中も書き換えられない。デバイス自体は存在するのに開けなかった場合（他アプリに排他的に掴まれている等）は自動では再試行しない。手が空いたら「一覧を更新」で再試行させる。

`--mic` / `--monitor` CLI オプション（番号指定、上記の CLI オプション参照）は `mic_device` / `monitor_device` より優先される。CLI オプションが有効な間は、ダッシュボードの対応するドロップダウンは操作不能になる。

daemon 起動後に接続したデバイスは、一覧を更新するまでドロップダウンに表示されない（設定パネルの「一覧を更新」ボタン）。更新中は両方のキャプチャストリームが一瞬途切れる。

### 入力レベル表示

ダッシュボードのヘッダーには、ミュートボタンの隣にキャプチャ系統（マイク/スピーカー）ごとのレベルバーが表示される。バーはクレストファクタ（peak を rms で割った値）で音声とノイズを見分ける。音声は 3〜10 以上あるが、内蔵マイクのハムのような定常的な電気ノイズは 1〜2 しかない。

「音量はあるのに変化がない」状態が10秒続くとバーが黄色（定常ノイズ）になる。これはマイク・スピーカーいずれの系統にも適用される。マイクはさらに、完全な無音（音量が正確にゼロ）が30秒続くと赤色（無音デバイス）になる——生きたマイクには常にノイズフロアがあるため、厳密にゼロが続くのは音が届いていない証拠（例：電源が切れた状態でもドングルだけはデバイスとして認識されるヘッドセット）。スピーカー側の監視（monitor）にはこの判定を適用しない。sink monitor は何も再生していない間、厳密なゼロを返すのが正常な待機状態であり、故障ではないため。指定デバイスが使えず自動デバイスで代替中の系統には、いずれもフォールバックと同じ意味でリング状の枠が付く。

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

~/.local/share/shadow-clerk/           # ランタイムデータ
  transcript-YYYYMMDD.txt              # 文字起こし結果（日付ベース）
  transcript-YYYYMMDDHHMM.txt          # 会議セッション用（ad-hoc）
  transcript-YYYYMMDDHHMM@会議名.txt   # 会議セッション用（カレンダー連携 or 名前付き）
  transcript-YYYYMMDD-<lang>.txt       # 翻訳結果
  summary-YYYYMMDD.md                  # 議事録（transcript に対応）
  glossary.txt                         # 用語集 (TSV: 翻訳用語 & reading ベースのテキスト置換)
  config.yaml                          # 設定ファイル
  gcal_token.json                      # Google Calendar OAuth トークン（gcal-auth で生成）
```

## トラブルシューティング

### デバイスが見つからない

```bash
# デバイス一覧を確認
clerk-daemon --list-devices

# PipeWire: ステータス確認
wpctl status

# PulseAudio: ソース一覧
pactl list short sources
```

### モニターソース（システム音声）が検出されない

PipeWire 環境では `wpctl status` で sink（出力）デバイスを確認する。
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

**中間翻訳:**

`interim_transcription` が有効なとき、daemon は確定前の各行を翻訳してダッシュボードの interim パネルに流す。これを制御するキーが2つ:

- `interim_translation: true` — 中間 ASR は残しつつ中間翻訳パネルだけオフにする場合は false
- `interim_translation_provider: null | "api" | "libretranslate" | "claude"` — バックエンドを明示。`null` は `translation_provider` を踏襲し、それが `claude` なら interim には遅すぎるため `api` → `libretranslate` の順で自動フォールバック(claude は1呼び出し 5〜10秒)。`claude` を直接指定するのは遅延を承知の場合だけ

中間パネルは1秒以下のレスポンスが前提なので、`libretranslate`(ローカル)が最も推奨、`api` も高速モデルなら可。確定 transcript の翻訳は `translation_provider` を使い、ここの設定の影響は受けない。
