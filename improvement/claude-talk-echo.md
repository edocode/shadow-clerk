# Claude Talk Mode Phase 2-2: 相手の発言を読み、Claude の声を除く

Phase 2 の2つ目。前提: `improvement/claude-talk-route.md`（Phase 2-1: Claude の声を会議アプリに届ける）。

## Problem

talk mode 中は、手元のヘッドセットで鳴らした Claude の声が monitor（相手の声を録るチャンネル）にも入るので、
monitor の文字起こしを丸ごと捨てている（`TalkDriver.is_suppressed("monitor")`）。そのため会議中に talk mode を
使っても、相手の発言（`[相手]`）が transcript に入らず、Claude が会話に加われない。

## Goal

- 届け先（会議アプリ）を選んだ talk mode では、monitor の文字起こしを再開し、相手の発言を `[相手]` として書く
- Claude 自身の声を文字起こしした行は `[相手]` として書かない
- Linux でも Windows でも同じ処理で動く（音声処理を使わず、文字の段階で判定する）
- 届け先なし（二人だけの会話）では従来どおり monitor を捨てる（動画や通知音を `[相手]` として拾わない）

Non-goals: 波形の差し引き、Linux で会議アプリの再生音だけを録る方式（精度が足りなければ後で上乗せする）、
talk skill の変更（`[相手]` の扱いは clerk-talk 1.3.0 で記述済み）。

## Approach

shadow-clerk は、いつ・何を読み上げたかを知っている。monitor の1行が、読み上げの時間帯に重なり、かつ読み上げた文と
似ていれば、Claude の声の文字起こしとみなして捨てる。

トレードオフ: Claude の読み上げ中に相手がかぶせて話すと、混ざった音声の文字起こしが Claude の文と似ていると判定され、
相手の言葉ごと捨てられることがある。かぶせて話す場面は少なく、かぶせるなら制止の言葉のことが多い（制止は `[自分]`
で届く）ので許容する。

## Components

### Domain: `domain/talk_echo.py`

- `SpokenSpan(start: float, end: float, text: str)`（frozen dataclass）— 実際に鳴った1文の区間（epoch 秒）と文
- `EchoFilter(tail_sec: float = 3.0, similarity: float = 0.6, keep_sec: float = 60.0)`
  - `record(span: SpokenSpan) -> None` — 履歴に足す。`keep_sec` より古いものは捨てる
  - `is_echo(seg_start: float, seg_end: float, text: str) -> bool`
    1. 時間: 区間 `[seg_start, seg_end]` が、どれかの `[span.start, span.end + tail_sec]` と重なる
    2. 文: 重なった span の文をつなげたものと `text` を、空白・句読点・記号を除いて比べ、3文字以上連続して一致した部分の割合が `similarity` 以上。正規化して6文字未満の行は常に相手の発言として残す。
       一致度は `difflib.SequenceMatcher` で、短いほう（`text`）が長いほうにどれだけ含まれるかを見る
       （`matching blocks の合計 / len(text の正規化後)`）。`text` が正規化後に空なら False
  - スレッドから使うので内部はロックで守る
- 純粋な値・ロジックなので、時刻は呼び出し側が渡す（テストで時刻を固定できる）

### TTS: 実際に鳴った区間を知らせる

- `TtsPlayer.__init__(..., on_played: Callable[[str, float, float], None] | None = None)` — 1文を
  鳴らし始めた時点で、開始時刻から音声の長さぶんの区間 `on_played(text, start, end)` を知らせる（`time.time()`）。
  再生に失敗した文も記録される（実害は小さい）
- `make_player` と、経路ありのとき driver が直接作る `TtsPlayer` の両方に渡す

### TalkDriver

- `EchoFilter` を1つ持つ（設定 `talk_echo_tail_sec`・`talk_echo_similarity` から作る。開始ごとに作り直す）
- `TtsPlayer` に `on_played=lambda text, s, e: echo.record(SpokenSpan(s, e, text))` を渡す
- `is_suppressed(source)`: talk mode 中の monitor は、**届け先が無いときだけ**真（届け先ありなら偽）
- `is_echo(source: str, seg_start: float, seg_end: float, text: str) -> bool` — monitor かつ talk mode 中かつ
  届け先ありのときだけ `EchoFilter.is_echo` を返す。それ以外は False

### 文字起こし側（`_daemon_recorder_transcribe.py`）

- `_process_transcribe_item` で、本文が決まったあと（`word_replacer.apply` の後、ノイズ・応答フィルタの前）に
  `self.talk.is_echo(source, seg_end - duration, seg_end, text)` を尋ね、真なら書かずに debug ログを出して捨てる
  - `seg_end` は `timestamp`（区間が確定した時刻、秒単位の文字列）を epoch に直したもの、`duration` は
    `len(segment) / SAMPLE_RATE`。`timestamp` は秒に丸められているので、`tail_sec` の余裕で吸収する
- 終了時にキューの残りを処理する経路にも同じ判定を入れる

### Config

| キー | 既定値 | 説明 |
|---|---|---|
| `talk_echo_tail_sec` | `3.0` | 読み上げ終了後、Claude の声とみなす余裕（秒） |
| `talk_echo_similarity` | `0.6` | 読み上げた文との一致度がこれ以上なら Claude の声とみなす（0〜1） |

## Error Handling

| 事象 | 挙動 |
|---|---|
| 再生の通知が来ない（合成失敗・古い文で再生しなかった） | 履歴に無いので捨てない（相手の発言として残る側に倒す） |
| しきい値の設定が不正（数値でない・範囲外） | 既定値を使う |
| 届け先ありの talk mode を終了した | monitor の扱いは通常（talk mode 外）に戻る |

## Testing

| ファイル | 対象 |
|---|---|
| `tests/test_talk_echo.py` | `EchoFilter`: 時間が重なり文も似ている → 捨てる / 時間は重なるが文が違う → 残す / 時間が外れていれば似ていても残す / 誤認識を少し含んでも似ていると判定 / 正規化後に空 → 残す / 古い履歴は消える |
| `tests/test_tts.py` | `TtsPlayer` が鳴らし始める文ごとに、再生より前に `on_played` を呼ぶ（end は start + 音声の長さ） |
| `tests/test_talk_driver.py` | 届け先ありで `is_suppressed("monitor")` が偽、`is_echo` が履歴に従う / 届け先なしでは従来どおり |
| `tests/test_talk_recorder_hook.py` | 届け先ありの talk mode で、monitor の Claude の声の行は書かれず、相手の行は `[相手]` で書かれる |

手動: 会議アプリで相手に話してもらう（または別の端末から音声を流す）。`[相手]` が transcript に入り、
Claude の読み上げは `[相手]` に入らないことを確かめる。かぶせて話したときの挙動も見る。
