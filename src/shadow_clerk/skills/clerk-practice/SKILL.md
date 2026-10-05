---
description: shadow-clerk の「Claude と会議」（talk mode）で、語学の練習相手になる。練習用の会議を作り、前回までの練習を踏まえて今日の練習を提案し、会話・発音・作文を声で練習して、直しと例文をダッシュボードの AI分析 タブに書く。talk mode 中にユーザーが「英語の練習をしたい」のように語学の練習を頼んだとき、clerk-talk から切り替えて使う。「/clerk-practice」と打たれたときにも使う。
allowed-tools: Bash(curl -s "http://localhost:*) Bash(curl -s -X POST "http://localhost:*) Bash(curl -sN "http://localhost:*) Monitor Agent
metadata:
  version: "1.2.0"
---

# clerk-practice — 声で語学を練習する

あなたは talk mode の中で、ユーザーの語学の練習相手になる。話し方（1回の `/api/say` は1〜2文、Markdown や記号を
使わない、遮られたときの扱い）・聞き方・用語集と聞き間違いの扱いは `/clerk-talk` と同じ。ここに書いていないことは
`clerk-talk` に従う。このスキルには練習の進め方だけを書く。

## 前提

shadow-clerk の場所は環境変数 `SHADOW_CLERK_URL`（`http://localhost:<port>` の形。無ければ `http://localhost:8765`）。
**URL は実際の値を埋め込んで**シェルコマンドで叩く。以下の例の `8765` は実際のポートに置き換える。

**コマンドは例の形のまま使う**: フラグの直後に、二重引用符で囲んだ `http://localhost:…` の URL を置く。
この skill はその形のコマンドだけを事前に許可しているので、変数展開・別のフラグ順・パイプにすると許可の確認で止まる。
`-d` の JSON は単引用符で囲むので、英文の `'` はシェルの書き方で `'\''` と書く（例: `It'\''s raining.`）。

- 聞く Monitor（`/api/watch?interval=1`）は `clerk-talk` で張ったものをそのまま使う（まだ張っていなければ
  `clerk-talk` の「聞く」のとおり張る）。会議を始めても終えても、`<notice>書き込み先が … に変わりました</notice>` の
  あとに新しいファイルの行が届くので、貼り直さなくてよい
- ユーザーの母語は `/api/talk-mode` の `language`（ふつうは `ja`）。説明はこの言語で話す
- 以下、練習する言語のコードを `<lang>`（例: `en`）、言語名を `<言語名>`（例: 英語）と書く。例はすべて英語の練習

## 1. 始める

1. 練習する言語を確かめる（例:「英語ですね」）
2. いまの状態を覚える。応答の `language`（いま聞き取っている言語。`auto` もありうる）を覚えておく。**ここではまだ `/api/language` を呼ばない**
  （何を練習するかを決めるあいだは母語で話すので、聞き取りは元の言語のままにする）

```
curl -s "http://localhost:8765/api/status"
```

3. 別の会議が進行中でないか確かめる

```
curl -s "http://localhost:8765/api/session"
```

- `in_meeting` が true で `meeting` が `<言語名>練習` でなければ、別の会議の記録中。その会議は終わらせない。
  「いまは別の会議を記録しているので、練習の記録はそちらに入ります」と伝え、手順 4 を飛ばして続ける。
  終えるときもその会議は終えない
- `meeting` が `<言語名>練習` なら、前の練習の会議が続いている。手順 4 を飛ばしてそのまま使う

4. 「練習用の会議を作りますね」と言ってから、`<言語名>練習` の会議を始める。`analyze` は false
   （会議アシスタントを起動しない。Advice と Analysis はあなたが書く）

```
curl -s -X POST "http://localhost:8765/api/meeting" -H 'Content-Type: application/json' -d '{"action":"start","name":"英語練習","analyze":false}'
```

5. スピーカー（monitor）をミュートし、応答の `previous`（切り替え前の状態）を覚えておく。練習は一人で行うので
   monitor は要らない。ダッシュボードで例文を読み上げても `[相手]` として書かれなくなる

```
curl -s -X POST "http://localhost:8765/api/mute" -H 'Content-Type: application/json' -d '{"source":"monitor","muted":true}'
```

## 2. 前回を踏まえて提案する

```
curl -s "http://localhost:8765/api/meeting-history?meeting=英語練習&count=3&tail=15"
```

- 各回の `tail` が transcript の末尾 15 行。前回の最後に話した「今日の練習のまとめ: …」の行に、
  やったこと・できたこと・次の課題がある
- 前回の課題から今日の練習を1〜2個提案し、選んでもらう（例:「前回は L と R の発音が課題でした。
  今日は発音から始めますか、それとも会話にしますか？」）
- `meetings` が空なら初回。練習の形を3つ（会話・発音・作文）短く紹介して選んでもらう

## 3. 練習する

- **練習が実際に始まるとき**、「では、始めましょう」のように一言かけてから、聞き取る言語を練習する言語に切り替える。
  切り替えには数秒かかるので、黙らずに短く知らせる（例:「聞き取りを英語にしますね。数秒かかります」）

```
curl -s -X POST "http://localhost:8765/api/language" -H 'Content-Type: application/json' -d '{"language":"en"}'
```

- ユーザーが練習の途中で母語で話したがったとき（「ちょっと日本語で聞きたい」など。`[自分]` の行が母語をカタカナにしたような
  文字列になっているのも合図）は、聞き取る言語を覚えておいた元の言語に戻す（`{"language":"ja"}`。元が `auto` なら `auto`）。
  これも数秒かかるので一言添える。練習に戻るときは、上のとおり練習する言語に切り替え直す

### 話し方

- **説明はユーザーの母語、練習する文は練習する言語**で話す。1回の発話は短く
- 練習する言語の文は `/api/say` に `lang` を付けて送る。ダッシュボードのブラウザの声（その言語の発音）で読まれる。
  説明の文は `lang` を付けない（VOICEVOX で読まれる）

```
curl -s -X POST "http://localhost:8765/api/say" -H 'Content-Type: application/json' -d '{"text":"They are there.","lang":"en"}'
```

- **1回の `/api/say` には1つの言語の文だけを入れる。** 説明と例文が混ざるときは分けて、話す順に送る。
  「ゼイ アー ゼア、と言ってみましょう」なら、「次の文を言ってみましょう。」を `lang` なしで送り、
  続けて `They are there.` を `lang` 付きで送る。練習する言語の文をカタカナにして送らない
- `display` を付けると、声は `text` を読み、transcript の `[Claude]` 行には `display` を書く（`text` と同じく空でない文字列）。
  答えの綴りを見せたくないとき（発音の練習）に使う
- 送った順に読まれる（VOICEVOX の文とブラウザの文が交互でも順番は保たれる）
- ダッシュボードが開いていない・ブラウザにその言語の声が無いときは VOICEVOX で読まれ、なまりが出る。
  お手本が聞き取りにくいと言われたら、ダッシュボードを開いて一度クリックしておくよう伝える

### 会話

- やさしく短い文で話す。相手の様子を見て少しずつ難しくする
- **会話の途中では直さない。** 間違いがあっても、正しい言い方で言い直して見せる程度にする（例: ユーザーが
  「I go to there yesterday.」と言ったら「Oh, you went there yesterday? What did you do?」と返す）
- 直しは Advice にためて、話の切れ目でまとめて伝える
- **やりとりを Analysis に書く。** 2〜3往復ごとに、あなたの文とユーザーの文（届いた `[自分]` の行）を会話の形で、
  直したほうがよい文には自然な言い方を添えて追記する（形は「4. 書く」の会話の例）。transcript には直しが残らないので、
  あとで読み返せるのはここだけ

### `[画面]` 行が来たら

`[画面]` は、ユーザーがブラウザ拡張で撮った画面のキャプチャ（例: 練習用に読む文章を映したもの）。**無視しない。練習の発言としても扱わない。**
手順は `clerk-talk` の「`[画面]` 行が来たら」と同じ。

- 声で一言だけ知らせ（例:「画面、見てみますね」）、10 秒待ってから、画像は**自分で Read しない**。Agent ツールで
  **バックグラウンドのサブエージェント**に読ませる。画像のパスは `/api/session` の `dir` + `/` + 行の `shot-….png`
- サブエージェントには、画像のパスと撮影行の前後 10 行ほどの発言を渡し、画面の構造を数行で説明させる。
  **練習に関わる部分**（読む文章、問題文、直してほしい文など）がどこかが分かる形で。個人情報は必要な分以外そのまま写さない
- 説明が返ったら練習に使う（映した文章を音読してもらう、文を直す、など）。説明をそのまま読み上げない
- 同時に動かすのは1件まで。タブのタイトルと URL は声に出さない

### 発音

- 判定は音声認識に通るかどうかで行う。届いた `[自分]` の行が言ってもらった文どおりなら通った
- 音声認識は文脈で補うので、文の中の単語は通りやすい。単語単体や紛らわしい組（light と right、sheep と ship など）で試す
- 通らなければ、どう聞こえたか（認識結果）と、口の形・舌の位置のコツを母語で短く伝え、もう一度言ってもらう
- お手本は `lang` 付きの `/api/say` で聞かせる
- **お題の単語は綴りを見せない。** 綴りが `[Claude]` 行に出ると、ユーザーは読んでから言えてしまい、認識結果も綴りと並んで
  判定がゆがむ。`text` に本物の単語、`lang` に言語、`display` にカタカナと意味だけを入れて送る。
  ブラウザの声は正しい発音で読み、transcript には「ライト（右）」としか残らない

```
curl -s -X POST "http://localhost:8765/api/say" -H 'Content-Type: application/json' -d '{"text":"right","lang":"en","display":"ライト（右）"}'
```

- 同じ組の次の単語も同様に送る（例: `{"text":"light","lang":"en","display":"ライト（光）"}`）
- ユーザーが言った後、判定してから初めて、綴りと 🔊 の例文を `/api/generated` で Analysis に書く（綴りはそこで見せる）。
  **試した単語は、通ったものも含めて全部書く。** transcript にはカタカナしか残らないので、綴りが残るのはここだけ。
  単語ごとに 綴り・意味・どう聞こえたか（認識結果）・結果 と、通らなかった単語には口の形・舌の位置のアドバイスも書く
  （形は「4. 書く」の発音の例）。1組（right と light など）を判定し終えるたびに追記する

### 作文

- 母語でお題を出す（例:「昨日は雨だったので家にいました、と英語で言ってみてください」）
- 言えたら、自然な言い方を `lang` 付きで返す。言えなかったところだけ母語で短く説明する
- お題ごとに、お題・言えた文・自然な言い方・説明を Analysis に追記する

## 4. 書く — Advice と Analysis

ダッシュボードの AI分析 タブの Advice と Analysis に出る。どちらも Markdown（見出し・箇条書き・表・引用が効く）。

- **頼まれなくても書く。** ユーザーはあとで AI分析 タブを読み返して復習する。声で伝えた直しや綴りは transcript には
  残らないので、書かなければ消えてしまう
- **書くのは話の切れ目**（発音は1組を判定し終えたとき、会話は2〜3往復ごと、作文はお題ごと）。
  書かずに次の組・次のお題へ進まない。書くときは、ユーザーの返事を待つ間（次のお題を出した直後など）に書けば会話が止まらない
- 直しを伝えたら Advice も書き直す
- **お手本・例文の行は `🔊 ` で始める。** ダッシュボードでその行（段落・箇条書き・引用）をクリックすると、
  いま聞き取っている言語の発音で読み上げられる。表の中の 🔊 はクリックできないので、表の外に置く
- `text` は 20,000 字まで。JSON の文字列なので、改行は `\n`、`"` は `\"` と書く

### Advice — いまの直し（毎回まとめ直して上書き）

```
curl -s -X POST "http://localhost:8765/api/generated" -H 'Content-Type: application/json' -d '{"kind":"advice","mode":"replace","text":"# いまの直し\n\n## 今日の重点\n- 過去のことは過去形で言う\n\n## 直近の直し\n| 言ったこと | 自然な言い方 | ポイント |\n|---|---|---|\n| I go to there yesterday. | I went there yesterday. | 過去は went。there に to は付けない |\n\n## お手本\n- 🔊 I went there yesterday.\n\n## 発音のコツ\n- R は舌先をどこにも付けずに奥へ丸める\n"}'
```

- 見出しは「いまの直し」
- **今日の重点** — 1つだけ
- **直近の直し** — 言ったこと / 自然な言い方 / ポイント の表。新しい順に最大5件。古いものは消す
- **お手本** — 直した言い方を `🔊 ` で始まる箇条書きで
- **発音のコツ** — いま課題になっている音だけ

### Analysis — 練習の記録と例文（時刻見出しで追記）

```
curl -s -X POST "http://localhost:8765/api/generated" -H 'Content-Type: application/json' -d '{"kind":"analysis","mode":"append","text":"\n## 10:15 作文\n\n| お題 | 言えた文 | 結果 |\n|---|---|---|\n| 昨日は雨だったので家にいました | I stayed home because it rained yesterday. | ○ |\n\n次に言ってみる例文:\n\n- 🔊 It was raining, so I stayed home.\n"}'
```

- 時刻と練習の形の見出し（`## HH:MM 作文` など）の下に積む。消さない・まとめ直さない
- 出題・言えた文・結果（○ / △ / ×）の表
- 次に言ってみる例文を `🔊 ` で始まる箇条書きで

発音は、試した単語を全部、表とアドバイスで書く。

```
curl -s -X POST "http://localhost:8765/api/generated" -H 'Content-Type: application/json' -d '{"kind":"analysis","mode":"append","text":"\n## 10:20 発音 R と L\n\n| 単語 | 意味 | 聞こえ方 | 結果 |\n|---|---|---|---|\n| right | 右 | light | × |\n| right | 右 | right | ○ |\n| light | 光 | light | ○ |\n\nアドバイス:\n- right の R は舌先をどこにも付けず、唇を少しすぼめてから言う\n\n- 🔊 right\n- 🔊 light\n- 🔊 Turn right at the light.\n"}'
```

会話は、やりとりを会話の形で書き、直したい文に自然な言い方を添える。

```
curl -s -X POST "http://localhost:8765/api/generated" -H 'Content-Type: application/json' -d '{"kind":"analysis","mode":"append","text":"\n## 10:30 会話 週末の話\n\n- **Claude**: What did you do last weekend?\n- **自分**: I go to there yesterday.\n  - 自然な言い方: I went there yesterday.（過去は went。there に to は付けない）\n- **Claude**: Oh, you went there yesterday? What did you do?\n- **自分**: I watched a movie.\n\n- 🔊 I went there yesterday.\n"}'
```

## 5. 終える

- 終えるかを確かめる**前に**、聞き取る言語を元の言語に戻す（下の `/api/language`。数秒かかるので一言添える）。
  終えるかの確認もまとめも母語なので、練習する言語のままだと聞き取りが崩れる
- 終えるかは**ユーザーに確かめてから**（例:「今日の練習はここまでにしますか？」）。はっきり終えてよいと返事があるまで続ける
  （練習を続けることになったら、練習する言語に切り替え直す）
- 終えるときは、「今日の練習のまとめ: 」で始まる発話を `lang` なしの `/api/say` で話す。やったこと・できたこと・
  次の課題を1〜3文で入れる。この行が transcript の末尾に残り、次回の提案の手がかりになる

```
curl -s -X POST "http://localhost:8765/api/say" -H 'Content-Type: application/json' -d '{"text":"今日の練習のまとめ: 過去形の会話と L と R の発音をやりました。went は自然に言えるようになりました。次は right と light の言い分けです。"}'
```

- 聞き取る言語を、覚えておいた元の言語に戻す（上で戻していなければ。元が `auto` なら `{"language":"auto"}`）

```
curl -s -X POST "http://localhost:8765/api/language" -H 'Content-Type: application/json' -d '{"language":"ja"}'
```

- スピーカーのミュートを、覚えておいた `previous` に戻す。`previous` が `false`（練習前はミュートしていなかった）
  ときだけ、次のように `"muted":false` を送る。`previous` が `true`（練習前からミュートしていた）なら何も送らず、
  ミュートのままにする

```
curl -s -X POST "http://localhost:8765/api/mute" -H 'Content-Type: application/json' -d '{"source":"monitor","muted":false}'
```

- 自分で始めた練習用の会議を終える（別の会議の最中に始めたときは終えない）

```
curl -s -X POST "http://localhost:8765/api/meeting" -H 'Content-Type: application/json' -d '{"action":"end"}'
```

- talk mode 自体を終えるかを尋ねる。終えるなら `clerk-talk` の「終わり」のとおり `/api/talk-end` を呼ぶ。
  続けるなら `clerk-talk` の進め方で会話に戻る

```
curl -s -X POST "http://localhost:8765/api/talk-end"
```
