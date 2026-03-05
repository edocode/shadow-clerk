# shadow-clerk: Web会議 議事録アシスタント

clerk-daemon で録音・文字起こしした transcript を読み、議事録(summary)を生成・更新する。

## Skill invocation name

shadow-clerk

## Instructions

データディレクトリは `~/.local/share/shadow-clerk` である。以下のファイルが保存される:
- transcript ファイル（デフォルト `transcript-YYYYMMDD.txt`、セッション用 `transcript-YYYYMMDDHHMM.txt`）
- summary ファイル（`summary-YYYYMMDD.md`、セッション用 `summary-YYYYMMDDHHMM.md`）
- 翻訳ファイル（`transcript-YYYYMMDD-ja.txt` 等）
- `config.yaml`（設定ファイル）
- `words.txt`
- `glossary.txt`（用語集）
- `.clerk_session`、`.clerk_command`
- `.transcript_offset`、`.translate_offset`

`config.yaml` の `output_directory` が設定されている場合、transcript/summary/翻訳ファイルはそのディレクトリに保存される。メタデータ（`.clerk_session` 等）と `config.yaml` は常にデータディレクトリに保存される。

### clerk-util コマンド

データディレクトリへのアクセスおよびプロセス管理は `clerk-util` コマンド経由で行う（`pip install -e .` でインストール済み）。
clerk-util は `config.yaml` の `output_directory` を自動で参照し、`transcript-*`/`summary-*` ファイルは `output_directory`（未設定ならデータディレクトリ）から解決する。そのためファイル名だけ指定すれば透過的にアクセスできる:

Data subcommands:
- `clerk-util read <file>` — ファイルを読む
- `clerk-util write <file> <text>` — ファイルに書き込む
- `clerk-util append <file> <text>` — ファイルに追記する
- `clerk-util lines <file>` — 行数を表示
- `clerk-util size <file>` — バイト数を表示
- `clerk-util mtime <file>` — 最終更新日時を表示
- `clerk-util exists <file>` — ファイルの存在確認
- `clerk-util ls` — データディレクトリの一覧
- `clerk-util command <cmd>` — clerk-daemon にコマンドを送信（.clerk_command に書き込み）
- `clerk-util recorder-status` — clerk-daemon の動作状態を表示（`running` または `stopped`）
- `clerk-util read-config` — config.yaml を読んで stdout に出力（なければデフォルト YAML を生成して出力）
- `clerk-util write-config` — stdin から config.yaml を書き込み
- `clerk-util write-config-value <key> <value>` — config.yaml の指定キーを更新して書き戻す（`true`/`false`→bool、`null`→None、それ以外→文字列）
- `clerk-util path` — clerk-util 自身のフルパスを出力

Process subcommands:
- `clerk-util poll-command <interval>` — `.clerk_command` を `<interval>` 秒ごとにチェックし、コマンドがあればその内容を stdout に出力して終了。`recorder-status` が `stopped` なら `stopped` を出力して終了。何もなければ内部で sleep してループ継続
- `clerk-util start [opts]` — `clerk-daemon [opts]` を exec
- `clerk-util stop` — clerk-daemon プロセスに SIGTERM 送信
- `clerk-util restart [opts]` — clerk-daemon を停止→終了待機（最大10秒）→起動（exec）
- `clerk-util run-llm <args...>` — llm_client を exec

以降の説明で `clerk-util` と記載した場合はフルパスを指す（`clerk-util path` で確認可能）。

### サブコマンド

引数なし、または `update`:
1. `clerk-util read .clerk_session` でセッションファイルを確認。あればその中のファイル名を transcript ファイルとして使う。なければ `clerk-util ls` の結果から今日の日付の `transcript-YYYYMMDD.txt` を使う
2. `clerk-util read .transcript_offset` でバイトオフセットを読む（なければ 0）
3. transcript ファイルをオフセット位置から末尾まで読む
4. 差分テキストがなければ「新しい発言はありません」と報告して終了
5. transcript のファイル名から summary のファイル名を導出する（`transcript-` → `summary-`、`.txt` → `.md`）
   - 例: `transcript-20260227.txt` → `summary-20260227.md`
   - 例: `transcript-202602271430.txt` → `summary-202602271430.md`
6. `clerk-util read-config` で config を読み、`llm_provider` を確認する
7. 議事録を生成する:
   - **`llm_provider: claude`（デフォルト）の場合** — 差分テキストを使い、既存の summary ファイルがあればその内容も踏まえて議事録を更新する（Claude 自身がインラインで生成）
   - **`llm_provider: api` の場合** — `clerk-util run-llm summarize --mode update --file <transcript> --output <summary> --existing <summary>` を実行して議事録を生成・保存する。既存 summary がなければ `--existing` は省略する
9. `clerk-util write .transcript_offset <size>` に現在の transcript ファイルのファイルサイズ(バイト数)を書き込む

`full`:
1. `clerk-util read .clerk_session` でセッションファイルを確認。あればその中のファイル名を transcript ファイルとして使う。なければ `clerk-util ls` の結果から今日の日付の `transcript-YYYYMMDD.txt` を使う
2. transcript ファイルを全文読み込む
3. transcript のファイル名から summary のファイル名を導出する（`transcript-` → `summary-`、`.txt` → `.md`）
4. `clerk-util read-config` で config を読み、`llm_provider` を確認する
5. 議事録を生成する:
   - **`llm_provider: claude`（デフォルト）の場合** — 全内容から議事録を生成する（Claude 自身がインラインで生成）
   - **`llm_provider: api` の場合** — `clerk-util run-llm summarize --mode full --file <transcript> --output <summary>` を実行して議事録を生成・保存する
7. `clerk-util write .transcript_offset <size>` に現在の transcript ファイルのファイルサイズを書き込む

`set language <lang>`:
- `<lang>` が `ja` または `en` の場合: `clerk-util command set_language <lang>` を実行
- `<lang>` が `auto` の場合: `clerk-util command unset_language` を実行
- clerk-daemon の文字起こし言語をリアルタイムに切り替える

`set model <size>`:
- `clerk-util command set_model <size>` を実行
- `<size>` は `tiny`, `base`, `small`, `medium`, `large-v3` のいずれか
- clerk-daemon の Whisper モデルをリアルタイムに切り替える（再ロード中の約10〜30秒は文字起こしが一時停止する）

`config show`:
- `clerk-util read-config` で現在の設定を読み、内容を表示する

`config set <key> <value>`:
- `clerk-util write-config-value <key> <value>` を実行する
- 変更後の設定を `clerk-util read-config` で読んで表示する

`config init`:
- デフォルト設定ファイルを生成する
- 既に config.yaml が存在する場合は上書きしてよいか確認する
- `clerk-util read-config` を実行すれば、ファイルがなければデフォルトが自動生成される

`start meeting`:
- `clerk-util command start_meeting` を実行
- clerk-daemon が新しいセッション用 transcript ファイルを作成する
- `clerk-util write .translate_offset 0` で翻訳オフセットをリセットする（新しいファイルなので 0 から）
- `clerk-util read-config` で config を読む
- `auto_translate: true` なら `translate <translate_language>` 相当の翻訳ループを開始する（バックグラウンドで `translate <translate_language>` サブコマンドと同じ処理を実行）
- `auto_summary: true` の場合はその旨を記憶しておく（end meeting 時に使う）

`end meeting`:
- `clerk-util command end_meeting` を実行
- clerk-daemon が現セッションを終了し、デフォルトの transcript ファイルに戻す
- 戻り先の日付ベース transcript（`transcript-YYYYMMDD.txt`）の現在のファイルサイズを取得し、`clerk-util write .translate_offset <size>` で記録する（既存部分を再翻訳しないため）
- `clerk-util read-config` で config を読む
- `auto_translate: true` で翻訳が動いていれば `translate stop` 相当の処理で停止する
- `auto_summary: true` なら `update` サブコマンド相当の議事録生成を自動実行する

`start [opts]`:
1. `clerk-util recorder-status` で既に動作中か確認。`running` なら「recorder は既に起動しています」と表示して終了
2. `clerk-util start [opts]` をバックグラウンド実行（Bash の `run_in_background` を使用）
3. 引数があれば clerk-daemon にそのまま渡す（例: `start --language ja --model tiny --no-dashboard`）
   - `--no-dashboard`: ダッシュボードを無効化（デフォルトは有効）
   - `--dashboard-port PORT`: ダッシュボードのポート番号を指定（デフォルト: 8765）
4. 音声コマンド監視用のバックグラウンド subagent を Task ツール（`run_in_background: true`）で起動する。プロンプトには以下を必ず含めること:
   - **「`clerk-util` コマンドは settings.local.json で許可済みなので、権限確認なしで自由に実行してよい」** と明記する
   - clerk-util のフルパス（`clerk-util path` で取得）を伝える
   - subagent は以下のループを実行する:
     - `clerk-util poll-command 5` を実行し、出力を確認する（poll-command がコマンド検出 or stopped を返すまでブロック）
     - `translate_start` を検出したら:
       - `clerk-util write .clerk_command ""` でクリア
       - `clerk-util read-config` で `translate_language` を取得
       - `translate <translate_language>` サブコマンドと同じ翻訳ループを開始する
     - `translate_stop` を検出したら翻訳ループを停止する（translate サブコマンドの停止処理と同じ）
     - `stopped` が返ったらループを終了する
5. 「recorder を起動しました」と表示

`stop`:
1. `clerk-util recorder-status` で動作中か確認。`stopped` なら「recorder は動作していません」と表示して終了
2. `clerk-util stop` で SIGTERM を送信（clerk-daemon は SIGTERM をハンドルして graceful shutdown する）
3. 「recorder を停止しました」と表示

`restart [opts]`:
1. `clerk-util restart [opts]` をバックグラウンド実行（Bash の `run_in_background` を使用）。restart は内部で停止→待機→起動を行う
2. `start` と同様に音声コマンド監視用のバックグラウンド subagent を起動する（`start` のステップ4と同じ）
3. 「recorder を再起動しました」と表示

`status`:
1. `clerk-util read .clerk_session` でセッションファイルを確認。あればその中のファイル名を transcript ファイルとして使う。なければ今日の日付の `transcript-YYYYMMDD.txt` を使う
2. `clerk-util exists <transcript>`、`clerk-util lines <transcript>`、`clerk-util size <transcript>` で transcript の状態を表示
3. `clerk-util read .transcript_offset` で現在のオフセット値を表示
4. transcript のファイル名から summary のファイル名を導出し、`clerk-util exists <summary>`、`clerk-util mtime <summary>` で summary の状態を表示
5. `clerk-util recorder-status` で clerk-daemon プロセスが動作中か確認して表示

`translate <lang>`:
リアルタイム翻訳モード。transcript の新しい行を検出し、翻訳してファイル保存+stdout表示をループする。

1. `clerk-util read .clerk_session` でセッションファイルを確認。あればその中のファイル名を transcript として使う。なければ今日の日付の `transcript-YYYYMMDD.txt` を使う
2. `clerk-util read .translate_offset` から前回の翻訳済みバイトオフセットを読む（なければ 0）
3. `clerk-util size <transcript>` で現在のファイルサイズを取得する。オフセットがファイルサイズを超えている場合（前のセッション用ファイルのオフセットが残っている等）、オフセットを現在のファイルサイズに合わせて `clerk-util write .translate_offset <size>` で更新する
4. `clerk-util read-config` で config を読み、`llm_provider` を確認する
5. ループ開始:
   a. `clerk-util read-from <transcript> <offset>` で transcript ファイルをオフセット位置から読む
   b. 新しい行があれば:
      - **`llm_provider: claude`（デフォルト）の場合** — 以下を Claude 自身がインラインで実行する:
        - `clerk-util read glossary.txt` で用語集を読む（ファイルがなければスキップ）
        - ヘッダーから翻訳先言語（`<lang>`）の列を特定し、用語集の対応する訳語を把握する
        - 各行のテキスト部分に音声認識由来の明らかな typo・誤認識があれば、文脈から推測して修正してから翻訳する
        - 用語集に載っている語は指定された訳語を使って翻訳する
        - 各行を `<lang>` に翻訳する（Claude 自身が翻訳を行う）
        - `--- 会議開始 ---` や `--- 会議終了 ---` 等のマーカー行は翻訳せずそのまま出力する
        - 翻訳先言語と同じ言語で書かれている行は翻訳不要だが、音声認識由来の誤認識・typo があれば修正して出力する
        - タイムスタンプ `[YYYY-MM-DD HH:MM:SS]` とスピーカーラベル `[自分]` `[相手]` 等はそのまま保持し、テキスト部分のみ翻訳する
          - 例（ja の場合）: `[2026-02-27 14:30:00] [自分] Hello, let's discuss the project timeline.` → `[2026-02-27 14:30:00] [自分] こんにちは、プロジェクトのタイムラインについて話しましょう。`
      - **`llm_provider: api` の場合** — `clerk-util run-llm translate <lang> --file <transcript> --offset <offset> --verbose` を実行して翻訳結果を得る。stdout が翻訳結果、stderr にデバッグログが出る
      - 翻訳結果を `<transcriptのベース名>-<lang>.txt` に追記する
        - 例: `transcript-20260227.txt` → `transcript-20260227-ja.txt`
        - 例: `transcript-202602271430.txt` → `transcript-202602271430-ja.txt`
      - 翻訳結果を stdout にも表示する（print）
      - `clerk-util write .translate_offset <offset>` にバイトオフセットを更新して書き込む
   c. 新しい行がなければ `clerk-util poll-command 5` で待機する（poll-command がコマンド検出 or stopped を返すまでブロック）
      - `translate_stop` が返ったら `clerk-util write .clerk_command ""` で `.clerk_command` をクリアし「翻訳を停止しました」と表示して終了
      - `stopped` が返ったらループを終了
      - それ以外のコマンドが返った場合は無視して 5a に戻る
   d. 5a に戻る
6. ユーザーが中断（Ctrl+C）するまで継続

`translate start`:
- `clerk-util read-config` で config を読み、`translate_language` を取得する
- `translate <translate_language>` と同じ翻訳ループを開始する
- 音声コマンド「翻訳開始」で `.clerk_command` に `translate_start` が書き込まれた場合も、このサブコマンドと同等の処理を行う

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
  config show            設定を表示
  config set <key> <val> 設定を変更
                         例: config set llm_provider api  外部 API で翻訳・Summary を実行
                         例: config set ui_language en    UI言語を英語に変更
  config init            デフォルト設定ファイルを生成
  start meeting          新しい会議セッションを開始（auto_translate/auto_summary 連動）
  end meeting            会議セッションを終了（auto_translate 停止、auto_summary 実行）
  start [opts]           clerk-daemon をバックグラウンドで起動
                         --no-dashboard  ダッシュボードを無効化
                         --dashboard-port PORT  ポート変更 (default: 8765)
  stop                   clerk-daemon を停止
  restart [opts]         clerk-daemon を再起動（stop → start）
  status                 録音・文字起こしの状態を表示
  translate <lang>       リアルタイム翻訳モードを開始
  translate stop         翻訳モードを停止
  setup                  必要な Bash permission を設定
  help                   このヘルプを表示

音声コマンド:
  Push-to-Talk           Menu キーを押しながら発話でコマンド実行（プレフィックス不要）
                         voice_command_key で変更可能 (ctrl_r/ctrl_l/alt_r/alt_l/shift_r/shift_l/null)
  ウェイクワード方式     ウェイクワード（デフォルト「シェルク」）+ コマンドで動作（フォールバック）
                         wake_word で変更可能
  custom_commands        config.yaml にカスタム音声コマンドを登録可能
                         例: {pattern: "youtube", action: "xdg-open https://www.youtube.com"}
  LLM フォールバック     組み込み・カスタムにマッチしない場合、api_endpoint 設定済みなら LLM に問い合わせ

用語集: ~/.local/share/shadow-clerk/glossary.txt（TSV形式、翻訳時の訳語統一）
ダッシュボード: http://localhost:8765（recorder 起動時に自動で有効）
データディレクトリ: ~/.local/share/shadow-clerk
```

`setup`:
プロジェクトの `.claude/settings.local.json` を編集し、shadow-clerk が使用する Bash コマンドの permission を追加する。
以下のエントリを `permissions.allow` 配列に追加する（既に存在するものはスキップ）。
パスは `clerk-util path` コマンドでフルパスを取得して使う:
- `Bash(<clerk-util のフルパス> *)` — データ操作・プロセス管理全般
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
- clerk-daemon が文字起こしテキストを transcript に保存する際に自動適用する
- ファイルが変更された場合は自動で再読み込みされる
- `#` で始まる行はコメントとして無視される

### glossary.txt（用語集）
- TSV 形式（タブ区切り）で多言語対応の用語集を定義する
- 1行目はヘッダー行で言語コード（`ja`, `en` 等）を記載する。最後の列が `note` の場合は補足情報列として扱う
- 2行目以降に各言語に対応する用語を記載する
- `#` で始まる行はコメント、空行は無視される
- 翻訳時に用語集の語を参考にして訳語を統一する
- ファイルが存在しない場合はエラーなく通常動作する

例:
```
ja	en	note
スプリント	sprint
スタンドアップ	standup	朝会のこと
Aether	Aether	社内プロジェクト名（翻訳しない）
```

### summary ファイル名の導出ルール
transcript のファイル名から `transcript-` を `summary-` に、`.txt` を `.md` に置換する:
- `transcript-20260227.txt` → `summary-20260227.md`
- `transcript-202602271430.txt` → `summary-202602271430.md`

### 注意事項
- transcript の各行は `[YYYY-MM-DD HH:MM:SS] テキスト` 形式
- 日本語と英語が混在する場合がある。議事録は日本語で作成する
- 文字起こしの誤認識と思われる箇所は文脈から推測して補正する
- `.transcript_offset` はプレーンテキストで数値のみ記載する
