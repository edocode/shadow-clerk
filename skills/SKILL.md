# shadow-clerk: Web会議 議事録アシスタント

recorder.py で録音・文字起こしした transcript を読み、議事録(summary)を生成・更新する。

## Skill invocation name

shadow-clerk

## Instructions

プロジェクトディレクトリはこの SKILL.md があるリポジトリのルートである。
データディレクトリは `~/.claude/skills/shadow-clerk/data` である。以下のファイルはすべてデータディレクトリに保存される:
- transcript ファイル（デフォルト `transcript-YYYYMMDD.txt`、セッション用 `transcript-YYYYMMDDHHMM.txt`）
- `.clerk_session`、`.clerk_command`
- `.transcript_offset`、`.translate_offset`
- summary ファイル（`summary-YYYYMMDD.md`、セッション用 `summary-YYYYMMDDHHMM.md`）
- `words.txt`
- 翻訳ファイル（`transcript-YYYYMMDD-ja.txt` 等）

### clerk-data コマンド

データディレクトリへのアクセスは `~/.claude/skills/shadow-clerk/clerk-data` ラッパースクリプト経由で行う:
- `clerk-data read <file>` — ファイルを読む
- `clerk-data write <file> <text>` — ファイルに書き込む
- `clerk-data append <file> <text>` — ファイルに追記する
- `clerk-data lines <file>` — 行数を表示
- `clerk-data size <file>` — バイト数を表示
- `clerk-data mtime <file>` — 最終更新日時を表示
- `clerk-data exists <file>` — ファイルの存在確認
- `clerk-data ls` — データディレクトリの一覧
- `clerk-data command <cmd>` — recorder.py にコマンドを送信（.clerk_command に書き込み）
- `clerk-data recorder-status` — recorder.py の動作状態を表示（`running` または `stopped`）

以降の説明で `clerk-data` と記載した場合はフルパス `~/.claude/skills/shadow-clerk/clerk-data` を指す。

### サブコマンド

引数なし、または `update`:
1. `clerk-data read .clerk_session` でセッションファイルを確認。あればその中のファイル名を transcript ファイルとして使う。なければ `clerk-data ls` の結果から今日の日付の `transcript-YYYYMMDD.txt` を使う
2. `clerk-data read .transcript_offset` でバイトオフセットを読む（なければ 0）
3. transcript ファイルをオフセット位置から末尾まで読む
4. 差分テキストがなければ「新しい発言はありません」と報告して終了
5. transcript のファイル名から summary のファイル名を導出する（`transcript-` → `summary-`、`.txt` → `.md`）
   - 例: `transcript-20260227.txt` → `summary-20260227.md`
   - 例: `transcript-202602271430.txt` → `summary-202602271430.md`
6. 差分テキストを使い、既存の summary ファイルがあればその内容も踏まえて議事録を更新する
7. summary ファイルを上書き保存する
8. `clerk-data write .transcript_offset <size>` に現在の transcript ファイルのファイルサイズ(バイト数)を書き込む

`full`:
1. `clerk-data read .clerk_session` でセッションファイルを確認。あればその中のファイル名を transcript ファイルとして使う。なければ `clerk-data ls` の結果から今日の日付の `transcript-YYYYMMDD.txt` を使う
2. transcript ファイルを全文読み込む
3. transcript のファイル名から summary のファイル名を導出する（`transcript-` → `summary-`、`.txt` → `.md`）
4. 全内容から議事録を生成し summary ファイルに上書き保存する
5. `clerk-data write .transcript_offset <size>` に現在の transcript ファイルのファイルサイズを書き込む

`set language <lang>`:
- `<lang>` が `ja` または `en` の場合: `clerk-data command set_language <lang>` を実行
- `<lang>` が `auto` の場合: `clerk-data command unset_language` を実行
- recorder.py の文字起こし言語をリアルタイムに切り替える

`set model <size>`:
- `clerk-data command set_model <size>` を実行
- `<size>` は `tiny`, `base`, `small`, `medium`, `large-v3` のいずれか
- recorder.py の Whisper モデルをリアルタイムに切り替える（再ロード中の約10〜30秒は文字起こしが一時停止する）

`start meeting`:
- `clerk-data command start_meeting` を実行
- recorder.py が新しいセッション用 transcript ファイルを作成する

`end meeting`:
- `clerk-data command end_meeting` を実行
- recorder.py が現セッションを終了し、デフォルトの transcript ファイルに戻す

`start [opts]`:
1. `clerk-data recorder-status` で既に動作中か確認。`running` なら「recorder は既に起動しています」と表示して終了
2. プロジェクトディレクトリ（SKILL.md があるリポジトリのルート）で `uv run python recorder.py` をバックグラウンド実行（Bash の `run_in_background` を使用）
3. 引数があれば recorder.py にそのまま渡す（例: `start --language ja --model tiny`）
4. 「recorder を起動しました」と表示

`stop`:
1. `clerk-data recorder-status` で動作中か確認。`stopped` なら「recorder は動作していません」と表示して終了
2. `pkill -f recorder.py` で SIGTERM を送信（recorder.py は SIGTERM をハンドルして graceful shutdown する）
3. 「recorder を停止しました」と表示

`status`:
1. `clerk-data read .clerk_session` でセッションファイルを確認。あればその中のファイル名を transcript ファイルとして使う。なければ今日の日付の `transcript-YYYYMMDD.txt` を使う
2. `clerk-data exists <transcript>`、`clerk-data lines <transcript>`、`clerk-data size <transcript>` で transcript の状態を表示
3. `clerk-data read .transcript_offset` で現在のオフセット値を表示
4. transcript のファイル名から summary のファイル名を導出し、`clerk-data exists <summary>`、`clerk-data mtime <summary>` で summary の状態を表示
5. `clerk-data recorder-status` で recorder.py プロセスが動作中か確認して表示

`translate <lang>`:
リアルタイム翻訳モード。transcript の新しい行を検出し、翻訳してファイル保存+stdout表示をループする。

1. `clerk-data read .clerk_session` でセッションファイルを確認。あればその中のファイル名を transcript として使う。なければ今日の日付の `transcript-YYYYMMDD.txt` を使う
2. `clerk-data read .translate_offset` から前回の翻訳済みバイトオフセットを読む（なければ 0）
3. ループ開始:
   a. `clerk-data read-from <transcript> <offset>` で transcript ファイルをオフセット位置から読む
   b. 新しい行があれば:
      - 各行のテキスト部分に音声認識由来の明らかな typo・誤認識があれば、文脈から推測して修正してから翻訳する
      - 各行を `<lang>` に翻訳する（Claude 自身が翻訳を行う）
      - `--- 会議開始 ---` や `--- 会議終了 ---` 等のマーカー行は翻訳せずそのまま出力する
      - 翻訳先言語と同じ言語で書かれている行はそのまま出力する（翻訳不要）
      - タイムスタンプ `[YYYY-MM-DD HH:MM:SS]` とスピーカーラベル `[自分]` `[相手]` 等はそのまま保持し、テキスト部分のみ翻訳する
        - 例（ja の場合）: `[2026-02-27 14:30:00] [自分] Hello, let's discuss the project timeline.` → `[2026-02-27 14:30:00] [自分] こんにちは、プロジェクトのタイムラインについて話しましょう。`
      - 翻訳結果を `<transcriptのベース名>-<lang>.txt` に追記する
        - 例: `transcript-20260227.txt` → `transcript-20260227-ja.txt`
        - 例: `transcript-202602271430.txt` → `transcript-202602271430-ja.txt`
      - 翻訳結果を stdout にも表示する（print）
      - `clerk-data write .translate_offset <offset>` にバイトオフセットを更新して書き込む
   c. 新しい行がなければ 5 秒待機する（`sleep 5`）
   d. 3a に戻る
4. ユーザーが中断（Ctrl+C）するまで継続

`translate stop`:
- 翻訳ループを中断する（手動で Ctrl+C しなくても停止できる用）
- 「翻訳を停止しました」と表示する

`help`:
以下のサブコマンド一覧を表示する:
```
shadow-clerk — Web会議 議事録アシスタント

サブコマンド:
  (引数なし) / update    transcript の差分から議事録(summary)を更新
  full                   transcript 全文から議事録を再生成
  set language <lang>    文字起こし言語を切り替え (ja / en / auto)
  set model <size>       Whisper モデルを切り替え (tiny / base / small / medium / large-v3)
  start meeting          新しい会議セッションを開始
  end meeting            会議セッションを終了
  start [opts]           recorder.py をバックグラウンドで起動
  stop                   recorder.py を停止
  status                 録音・文字起こしの状態を表示
  translate <lang>       リアルタイム翻訳モードを開始
  translate stop         翻訳モードを停止
  setup                  必要な Bash permission を設定
  help                   このヘルプを表示

データディレクトリ: ~/.claude/skills/shadow-clerk/data
```

`setup`:
プロジェクトの `.claude/settings.local.json` を編集し、shadow-clerk が使用する Bash コマンドの permission を追加する。
以下のエントリを `permissions.allow` 配列に追加する（既に存在するものはスキップ）。
パスは `clerk-data path` コマンドでフルパスを取得して使う:
- `Bash(<clerk-data のフルパス> *)` — データディレクトリ操作全般（recorder-status 含む）
- `Bash(sleep *)` — translate ループの待機用
- `Bash(pkill -f recorder.py)` — stop 用
- `Bash(uv run python recorder.py*)` — start 用（プロジェクトディレクトリで実行）
追加完了後、追加したエントリの一覧を表示する。

### 議事録フォーマット (summary-YYYYMMDD.md)

```markdown
# 議事録

- **日時**: YYYY-MM-DD HH:MM〜HH:MM（transcript のタイムスタンプから推定）
- **参加者**: （判別できれば記載、不明なら省略）

## 要約
（会議全体の要約を3〜5文で）

## 主な議題と決定事項
- **議題1**: 内容の要約
  - 決定事項: ...
- **議題2**: ...

## アクションアイテム
- [ ] 担当者: タスク内容（期限があれば記載）

## 詳細メモ
（重要な発言や補足情報）
```

### words.txt（単語置換リスト）
- TSV 形式（`間違い<TAB>正しい語`）で音声認識のよくある誤認識を定義する
- recorder.py が文字起こしテキストを transcript に保存する際に自動適用する
- ファイルが変更された場合は自動で再読み込みされる
- `#` で始まる行はコメントとして無視される

### summary ファイル名の導出ルール
transcript のファイル名から `transcript-` を `summary-` に、`.txt` を `.md` に置換する:
- `transcript-20260227.txt` → `summary-20260227.md`
- `transcript-202602271430.txt` → `summary-202602271430.md`

### 注意事項
- transcript の各行は `[YYYY-MM-DD HH:MM:SS] テキスト` 形式
- 日本語と英語が混在する場合がある。議事録は日本語で作成する
- 文字起こしの誤認識と思われる箇所は文脈から推測して補正する
- `.transcript_offset` はプレーンテキストで数値のみ記載する
