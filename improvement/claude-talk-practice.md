# Claude Talk Mode: 語学の練習（clerk-practice）

前提: `improvement/claude-talk-mode.md`、`improvement/claude-talk-skill.md`。talk mode で英語の練習をした
ところ手応えがあったので、練習の進め方を skill にし、直しや例文をダッシュボードの AI分析 タブに出す。

## Problem

- 練習のやり方（会話・発音・英作文）は、その場の Claude の判断で毎回組み立て直している。直した表現は最後に
  作業ディレクトリへ md で書かれるだけで、ダッシュボードには出ず、次回の練習にもつながらない
- 日付が変わると書き込み先のファイルが変わるが、`/api/watch` はつないだ時点のファイルを見続けるので、
  Claude にユーザーの発言が届かなくなる（talk・meeting-helper とも同じ）。実際に 0 時をまたいだ練習で、
  Claude が反応しなくなった（Claude は「聞き取る言語が日本語に戻った」と説明したが、ログ上は言語は en のまま
  だった。原因は書き込み先の切り替え）
- Claude の読み上げは VOICEVOX なので、英語は日本語なまりになる。お手本の発音を聞く手段がない

## Goal

- talk mode 中に「英語の練習をしたい」と言うと、Claude が練習用の会議を作り、前回までの練習を踏まえて
  今日の練習を提案する
- 練習の形は 会話・発音・英作文 の3つ。英語以外の言語でも同じ流れで使える
- 練習中、AI分析 タブの Advice に「いまの直し」、Analysis に「練習の記録と例文」が出る
- 例文は、ダッシュボードでクリックすると練習中の言語の発音で読み上げられる
- Claude が話す練習言語の文（例文・お手本・英語での会話）は、ブラウザの読み上げ（Chrome の英語の声など）で
  読まれる。skill が `/api/say` に言語を付けて送る。日本語の説明はこれまでどおり VOICEVOX
- 日付をまたいでも、Claude にユーザーの発言が届き続ける

Non-goals: 発音の自動採点（判定は音声認識に通るかどうかで行う）、観察役の Claude を別に立てる構成（必要なら
後で足す）、届け先（会議アプリ）ありの talk mode でブラウザの読み上げを使うこと（練習は 1 対 1 で相手がいない前提）。

## Approach

練習は「会議」として記録する。会議にすると、ファイルが日付で切り替わらず、同じ会議名の過去回として履歴が
たまる。各回の最後に Claude が今日のまとめを話して transcript に残すので、次の回は過去回の末尾を読むだけで
何をやってきたかが分かる。

練習の進行も Advice / Analysis の記入も、talk の Claude（clerk-talk から切り替える clerk-practice skill）が
自分で行う。出題した本人が書くので記録がずれず、Claude のセッションも1つで済む。talk の console は許可の確認で
会話が止まらないよう `curl` だけを使うので、会議の開始・終了とファイルの記入は daemon の API で行う。

## Components

### daemon

#### `/api/watch` が書き込み先の変化を追う

- `file` を指定しない監視（いまの書き込み先を流すもの）は、毎回 `recorder.output_path` を見る（1 回の確認で 1 度だけ読む）。
  変わっていたら（日付の切り替え・会議の開始と終了の両方）:
  1. 前のファイルの残り（前回の確認から書かれた行。会議の最後の発言や `--- 会議終了 ---` の印）を、前のファイル名で
     流しきる
  2. `<notice>書き込み先が <ファイル名> に変わりました</notice>` を流す
  3. 新しいファイルは先頭からではなく、recorder が書き込み先を変えた時点の大きさから流す。recorder は
     `output_path` を変えるたびにそのファイルの大きさを `output_switch_offset` に覚える（無いファイルは 0）。
     会議が終わって戻る日付ファイルはすでにあるので、先頭から流すとその日の発言を丸ごと流し直してしまう。
     切り替えたあと次の確認までに書かれた行は流れる
- `file` を指定した監視と `kind=advice` は、これまでどおり指定のファイルを見続ける

#### `POST /api/meeting` — 会議の開始・終了（localhost のみ）

| body | 動作 |
|---|---|
| `{"action": "start", "name": "英語練習", "analyze": false}` | `start_meeting <name>` と同じ。`analyze: false` なら `auto_analyze` が有効でも AI アシスタントを起動しない（既定 true）。会議中なら何もしない |
| `{"action": "end"}` | `end_meeting` と同じ。会議中でなければ何もしない |

- 応答は `{"status": "ok", "meeting": <会議名>, "transcript": <パス>, "in_meeting": bool}`
- `name` は `sanitize_meeting_name` を通し、空や 100 字超は拒否する。`/api/command` は使わない（任意の
  コマンドを通すため）

#### `POST /api/generated` — いまの会議の Advice / Analysis を書く（localhost のみ）

- body: `{"kind": "advice" | "analysis", "mode": "replace" | "append", "text": "…"}`
- 書き先は、いまの書き込み先（`recorder.output_path`）の `advice-<stem>.md` / `analysis-<stem>.md`。パスは
  受け取らない
- `text` は 20,000 字まで。`append` は末尾に改行を補ってから足す
- 書いたあと、ダッシュボードの表示はこれまでどおりファイル監視で更新される

#### `POST /api/mute` — マイク・スピーカーのミュートを切り替える（localhost のみ）

- body: `{"source": "mic" | "monitor", "muted": true | false}`。応答は `{"status": "ok", "source": …, "muted": …, "previous": <切り替え前>}`
- ダッシュボードのミュートボタンと同じ状態を切り替える。`/api/command` は使わない（任意のコマンドを通すため）

#### `GET /api/meeting-history` に `tail=N`

- `tail`（0〜50、既定 0）を付けると、各回に `"tail": [transcript の末尾 N 行]` を足す。`curl` しか使えない
  skill が前回のまとめを読むため

### ダッシュボード: 例文をクリックで読み上げ

- Advice / Analysis の描画後、本文が `🔊` で始まる段落・リスト項目・引用に `.say` を付ける。クリックで
  ブラウザの Web Speech API（`speechSynthesis`）が `🔊` の後ろの文を読み上げる
- 読み上げる言語は、いま聞き取っている言語（ダッシュボードの言語の選択欄、`/api/status` の `language`。`auto` なら指定しない。`/api/session` の `language` は翻訳先の言語なので使わない）。その言語の
  声がブラウザに無ければ既定の声で読む
- `speechSynthesis` が無いブラウザでは何もしない（クリックできる見た目にもしない）
- 読み上げはスピーカーから鳴るので、monitor が聞こえていると `[相手]` として書かれる。練習中は skill が
  スピーカー（monitor）をミュートするので起きない（下記）。練習の外で例文をクリックしたときは書かれうるが、まれなので許容する

### Claude の発話: 練習言語の文はブラウザで読む

練習は 1 対 1 で相手がいない前提なので、会議アプリへの届け先も echo の除去も考えなくてよい。

- **指定**: `/api/say` に `lang` を足す（`{"text": "They are there.", "lang": "en"}`）。`lang` が無い、または
  VOICEVOX の言語（`talk_language` で決まる読み上げ言語）と同じなら VOICEVOX で読む。違えばブラウザで読む。
  文の言語は話す本人（skill）が分かっているので、daemon は推測しない。日本語と英語が混ざる文は skill が分けて送る
  （「ゼイ アー ゼア」の部分を `lang: "en"` の `They are there.` に、説明を `lang` なしに）
- 届け先ありの talk mode では `lang` を無視して VOICEVOX で読む（ブラウザの音は会議アプリに届かない）
- 順番は1本の再生キューで保つ（VOICEVOX の文とブラウザの文が交互でも、送った順に鳴る）
- **鳴らすタブ**: ダッシュボードは `speechSynthesis` があり、その言語の声を持つときに
  `POST /api/talk-speech/ready {"tab": <id>, "langs": [...]}` を送る（ページを開いたとき・声の一覧が変わったとき、
  以後 30 秒ごと）。daemon は最後に名乗ったタブ1つだけに `talk_speak {id, tab, text, lang}` を SSE で送り、
  ほかのタブは無視する
- **再生の状態**: タブは `onend` / `onerror` で `POST /api/talk-speech/done {"id": …}` を返す。再生キューは done か
  タイムアウト（文字数から見積もった長さ + 5 秒）まで次の文に進まない（`is_busy()` も真のまま）。制止の言葉で
  止めるときは `talk_speak_cancel` を送り、タブは `speechSynthesis.cancel()` する
- **鳴らせるタブが無い**（60 秒以内に ready が無い、ready のタブに声が無い）ときは、その文を VOICEVOX で読む
- `[Claude]` 行の書き込み、`on_played` の通知（echo 用）はこれまでどおり（区間はタブの開始・終了から取らず、
  見積もりで足りる。練習中は monitor をミュートしているので echo の判定は効かない）

### skill: `clerk-practice`（新規、1.0.0）

`clerk-talk` と同じく talk の console で動く。`allowed-tools` は `clerk-talk` と同じ（`curl` と Monitor）。
`clerk-talk` には「語学の練習を頼まれたら `clerk-practice` に切り替える」を足す（1.6.0）。`clerk-util
install-skill` で一緒に入る。

1. **始める**: 練習する言語を確かめ（例:「英語ですね」）、「練習用の会議を作りますね」と言って
   `POST /api/meeting` で `<言語名>練習`（例: 英語練習）を `analyze: false` で始める。元の聞き取り言語（`/api/status` の `language`）を覚えて
   から `/api/language` で切り替える。`/api/mute` でスピーカー（monitor）をミュートし、切り替え前の状態を覚える
   （練習は一人で行うので monitor は要らない。ダッシュボードで例文を読み上げても `[相手]` に入らない）。
   練習言語の文は `/api/say` に `lang`（例: `en`）を付けて送り、ブラウザの声で読ませる。説明の文は `lang` なし`/api/watch` は書き込み先の変化を追うので貼り直さなくてよい
2. **前回を踏まえて提案する**: `/api/meeting-history?meeting=<会議名>&count=3&tail=15` で過去回の末尾を読み、
   前回のまとめから今日の練習を1〜2個提案して選んでもらう（初回なら3つの形を紹介する）
3. **練習する**:
   - **会話**: やさしく短い英語で話す。会話の途中では直さず、正しい言い方で言い直して見せる程度にする。
     直しは Advice にためる
   - **発音**: 音声認識に通るかで判定する。認識は文脈で補うので、単語単体や紛らわしい組（light / right など）
     で試す。通らなければ、どう聞こえたか（認識結果）と、口の形のコツを短く伝える
   - **英作文**: 日本語でお題を出し、英語で言ってもらう。言えたら自然な言い方を返す
   - 説明はユーザーの母語、練習する文は練習する言語で話す。1回の発話は短く
4. **書く**（話の切れ目、返事を待つ間にまとめて。応答のたびではない）:
   - **Advice（replace）**: 見出し「いまの直し」。今日の重点1つ、直近の直し（言ったこと / 自然な言い方 /
     ポイント の表、最大5件）、発音のコツ。お手本の文は `🔊 ` で始める
   - **Analysis（append）**: 時刻見出しの下に、出題・言えた文・結果（○ / △ / ×）、次に言ってみる例文
     （`🔊 ` で始める）
5. **終える**: ユーザーに確かめてから、「今日の練習のまとめ: …」で始まる発話（やったこと、できたこと、次の課題）
   を `/api/say` で話す。これが transcript の末尾に残り、次回の手がかりになる。聞き取り言語とスピーカーの
   ミュートを元に戻し、`POST /api/meeting` で会議を終える。talk mode 自体を終えるかは確かめる（終えるなら `/api/talk-end`）

## Error Handling

| 事象 | 挙動 |
|---|---|
| 練習を始めたときに別の会議が進行中 | skill はその会議を終わらせず、ユーザーに伝えて練習の会議を作らずに続ける（記録はその会議に入る） |
| `/api/generated` を会議の外で呼んだ | いまの書き込み先（日付のファイル）の advice / analysis に書く |
| 過去回が無い | 初回として3つの形を紹介する |
| ブラウザに読み上げ機能・その言語の声が無い | `.say` を付けない / 既定の声で読む |
| watch 中に書き込み先が変わった | 前のファイルの残りを流しきり、notice を流して、新しいファイルに切り替え時点の大きさから移る |
| ブラウザの読み上げが終わらない・タブが閉じた | タイムアウトで次の文に進み、そのタブが ready を送り直すまで VOICEVOX で読む。ready が 60 秒途絶えたときも VOICEVOX に戻す |
| 届け先ありの talk mode で `lang` 付きの `/api/say` | `lang` を無視して VOICEVOX で読む |
| `lang` が既知の言語コードでない | 拒否する |
| 練習を始めたときにスピーカーがすでにミュート | 切り替え前の状態（`previous`）を覚えて、終わるときにその状態に戻す |

## Testing

| ファイル | 対象 |
|---|---|
| `tests/test_skill_api.py` | watch が書き込み先の変化で前のファイルの残りを流しきり、notice を流して新しいファイルに移る（既存の日付ファイルに戻っても既存行は流さない）、recorder が切り替え時点の大きさを覚える、`file` 指定時は移らない、meeting-history の `tail` |
| `tests/test_meeting_api.py`（新規） | `/api/meeting` の start（analyze false で AI を起動しない、名前の検証、会議中は何もしない）と end、`/api/generated` の replace / append / 種類と字数の検証、localhost 以外の拒否 |
| `tests/test_say_js.py`（新規、node） | `🔊` で始まる項目に `.say` が付き、クリックで `speechSynthesis.speak` が言語つきで呼ばれる。`speechSynthesis` が無ければ付かない |
| `tests/test_meeting_api.py` | `/api/mute` の切り替えと `previous`、source と muted の検証 |
| `tests/test_talk_speech.py`（新規） | `lang` 付きの文だけブラウザへ・順番を保つ、done まで次に進まない・タイムアウト、制止で cancel を送る、ready が無ければ VOICEVOX、届け先ありでは VOICEVOX、`lang` の検証 |
| `tests/test_talk_speech_js.py`（新規、node） | ready の送信（声がある言語だけ）、自分宛ての talk_speak だけ読む、onend で done を送る、cancel で止める |
| `tests/test_skill_install.py` | `clerk-practice` が同梱・インストールされる、`clerk-talk` の版 |

手動: talk mode で「英語の練習をしたい」と言い、会議「英語練習」ができること、Advice / Analysis が更新される
こと、`🔊` の例文をクリックして英語で聞こえること、まとめを話して会議が終わること。2回目に前回を踏まえた提案が
出ること。0時をまたいでも発言が届くこと。
