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

### CLI オプション

| オプション | 説明 | デフォルト |
|---|---|---|
| `--output`, `-o` | 出力ファイルパス | `~/.claude/skills/shadow-clerk/data/transcript.txt` |
| `--model`, `-m` | Whisper モデルサイズ (`tiny`, `base`, `small`, `medium`, `large-v3`) | `small` |
| `--language`, `-l` | 言語コード (`ja`, `en` 等)。省略で自動検出 | 自動 |
| `--mic` | マイクデバイス番号 | 自動検出 |
| `--monitor` | モニターデバイス番号 (sounddevice) | 自動検出 |
| `--backend` | 音声バックエンド (`auto`, `pipewire`, `pulseaudio`, `sounddevice`) | `auto` |
| `--list-devices` | デバイス一覧を表示して終了 | - |
| `--verbose`, `-v` | 詳細ログ出力 | - |

### 議事録生成 (Claude Code Skill)

recorder.py で録音中、別ターミナルの Claude Code から:

```
/shadow-clerk          # 差分テキストから議事録を更新
/shadow-clerk full     # 全文から議事録を再生成
/shadow-clerk status   # 現在の状態を確認
```

生成された議事録は `~/.claude/skills/shadow-clerk/data/summary.md` に保存される。

## ファイル構成

```
shadow-clerk/                          # リポジトリ
  pyproject.toml                       # プロジェクト定義・依存関係
  recorder.py                          # 録音・VAD・文字起こし
  skills/
    SKILL.md                           # Claude Code Skill 定義
    clerk-data                         # データディレクトリ操作ラッパー
  SPEC.md                              # 設計仕様
  README.md                            # このファイル

~/.claude/skills/shadow-clerk/         # シンボリックリンク先
  data/                                # ランタイムデータ (実行時生成)
    transcript.txt                     # 文字起こし結果
    transcript-YYYYMMDDHHMM.txt        # 会議セッション用
    transcript-<lang>.txt              # 翻訳結果
    summary.md                         # 議事録
    words.txt                          # 単語置換リスト (TSV)
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
