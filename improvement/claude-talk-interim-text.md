# Claude Talk Mode: 中間文字起こしの中身を Claude に届ける

前提: `improvement/claude-talk-echo.md`（中間文字起こしは届け先ありの talk mode 中も動く）。
状態: 段階1を実装（2026-10-30。clerk-talk 1.7.6）。段階2は段階1の効果を見て決める。

## Problem

Claude は相手の発言を、確定行（transcript の行）でしか受け取れない。確定行は VAD が区切った区間ごとに、数秒おきの
細切れで届く。そのため Claude は、話し終えた後で内容を理解し、返事を考え、`/api/say` に投げることになる。
聞く → 考える → 投げる → 返ってくる → 話す、の往復が、そのまま返事の遅れになる。

monitor の中間文字起こしの文字は、すでに作られている。しかし `TalkDriver.on_interim(source)` は発言元の名前しか受け取らず、
`_daemon_recorder_transcribe.py` の `_interim_transcribe_thread` が得た `text` は、そこで捨てられる。
`GET /api/speaking` が返すのは `{"speaking": bool, "sources": [...]}` だけで、文字を含まない。
文字が外に出るのは、設定 `interim_transcription` が有効なときの `interim_transcript` イベント（ダッシュボードへの配信）だけで、
Claude からは見えない。

mic には中間文字起こしが無い。`_daemon_recorder_capture.py` の `_vad_thread_for_queue` は、mic では VAD が声を検出している間
`on_voice("mic")` を呼ぶだけで、`interim_queue` に音声を積むのは monitor だけ（`interim_transcription` が有効でも同じ）。
届け先なしの talk mode（ユーザーと Claude の二人の会話。いちばんよく使う形）では、monitor は Claude 自身の声しか来ないので
`hides_interim` で止めており、mic には文字が無い。つまり今のままでは、この形で Claude に届けられる中間の文字は無い。

## Goal

- Claude が、確定前の発言の中身を読める
- Claude が、相手が話している最中に質問や答えを先に組み立て、区切りが来たらすぐ出せる
- 既存の確定行の流れ（`/api/watch`、transcript）は変えない

Non-goals: 中間文字起こしの精度向上、Claude の応答生成そのものの高速化。

## Approach

2段階で進める。

1. 最新の中間文字起こしを `TalkDriver` が覚え、`/api/speaking` の応答に載せる。talk mode 中は mic にも中間文字起こしを足す
   （これが無いと届け先なしの talk mode で効果が無い）。
2. 効果があれば、`/api/watch` に中間用の流れを足し、Monitor で確定前の文字を直接受け取れるようにする。

中間文字起こしは軽いモデル（既定 `tiny`）で作るので誤認識が多い。Claude は、確定行と食い違ったら確定行を優先する。
先回りで組み立てた質問は、出す直前に確定行で見直す（clerk-talk の SKILL.md「会話に入るタイミング」。1.7.5 で追加し、1.7.6 で `interim` の読み方を足した）。

## Components

### TalkDriver（`_daemon_talk.py`）

- `on_interim(source: str, text: str = "")` — 時刻（`_heard[source]`）に加えて、source ごとの最新の `text` を保持する。
  `on_voice(source)`（mic の VAD）は文字を持たないので、これまでどおり時刻だけを更新する
  - 現状は `on_interim = on_voice` の別名なので、別のメソッドに分ける
- `clear_interim(source)` — 時刻と文字の両方を消す（確定行の処理で呼ばれる）
- `speaking()` は従来どおり source のリストを返す（既存の呼び出しを壊さない）
- `interim_texts() -> dict[str, str]` — `SPEAKING_STALE_SEC` 内の source だけ、最新の文字を返す

### 文字起こし側（`_daemon_recorder_transcribe.py`）

- `_interim_transcribe_thread` の `self.talk.on_interim(source)` を `self.talk.on_interim(source, text.strip())` に変える
- モデルを動かす条件 `show or self.talk.routed` を `show or self.talk.active` に広げる（届け先なしでも mic の中間を作るため）
- `interim_transcript` の配信（ダッシュボードの途中表示と翻訳）は `show` のときの monitor だけ。mic の中間は出さない

### 音声の切り出し（`_daemon_recorder_capture.py`）

- `_vad_thread_for_queue` の mic の分岐で、talk mode 中は monitor と同じく `get_interim_segment()` を `interim_queue` に積む
  （`interim_queue` は mic と monitor で分け合うので maxsize を 2 から 4 にした）
  - 積まない条件は `mic_voice_due` と揃える（ミュート中、PTT / コマンドモード中）
  - `on_voice("mic")` はそのまま残す（文字が出る前から「話している」と分かるため）
- monitor の分岐の `hides_interim` は変えない。Claude 自身の声の区間は、これまでどおり中間文字起こしを作らない

### API（`_daemon_dashboard_ops_talk.py`）

- `GET /api/speaking` の応答に `interim` を足す
  - 例: `{"speaking": true, "sources": ["monitor"], "interim": {"monitor": "来週のリリースですが"}}`
  - 文字が無い source は `interim` に含めない（キーは常にある）。従来の使い方は変わらない

### Watch（段階2、`_daemon_dashboard_ops_skill.py`）

- `GET /api/watch?kind=interim[&interval=1]` — 中間文字起こしが更新されるたびに1行流す
  - `_serve_watch` の `kind` の分岐（`transcript` / `advice`）に足す
  - 行の形は transcript に合わせる: `[時刻] [自分|相手] 中間文字`。確定行と区別できる印（`[途中]` など）を付ける
  - 流量を抑える。同じ文字の連続は流さず、1 source あたり最短 1 秒おきにする

### clerk-talk の SKILL.md

- 段階1: `/api/speaking` の `interim` を読み、先回りで質問や答えを組み立てる手順を書く（1.7.6 で済み）
- 段階2: 中間用の Monitor を1本足す手順を書く。確定行の Monitor は残す

## Open questions

- mic の中間文字起こしを足すと、talk mode 中は常に中間のモデル（既定 `tiny`）が動き、CPU を使う。確定の文字起こしや
  TTS の遅れにつながらないか（要実機確認）
- `SPEAKING_STALE_SEC = 4.0` は、切り出しの判断には長めかもしれない
- 確定行の区切りの閾値を短くして、細切れをさらに早く届けられるか
- 中間文字起こしを Claude が読むことの、プライバシー上の扱い（確定行と同じ transcript の範囲で足りるか）
