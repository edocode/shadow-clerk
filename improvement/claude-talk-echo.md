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

shadow-clerk は、いつ・何を読み上げたかを知っている。monitor の1行が、読み上げの時間帯（各文の終了後 `tail_sec` を含む）に重なれば、
Claude の声の文字起こしとみなして、本文に関わらず捨てる（時間だけで判定する）。

トレードオフ: Claude の読み上げ中に相手がかぶせて話すと、相手の言葉ごと捨てられる。かぶせて話す場面は少なく、かぶせるなら
制止の言葉のことが多い（制止は `[自分]` で届く）ので許容する。

理由: 当初は読み上げた文との類似も見ていたが、短い発言や相槌（「了解です」「うん」「フム」）や、かな漢字の揺れ
（「もうひとつ」と「もう一つ」）で Claude の声が `[相手]` として漏れた。文の類似では防ぎきれないので、読み上げ中は
monitor を無視する方針にした。

判定に使うのは VAD が測った区間の開始時刻。VAD は無音で区間を分けるので、反響の区間は読み上げ中に始まって捨てられ、
monitor が静かになった後に始まる区間は新しい発言として残る。tail は出力と録音の遅れだけを吸収すればよく、
旧既定の 1 秒は Claude が話し終えた直後の返事まで捨てていた。
既知の限界: Claude の直後に無音を挟まず相手が話し始めると、VAD が両方を1区間にまとめ、その区間は捨てられる。

## Components

### Domain: `domain/talk_echo.py`

- `SpokenSpan(start: float, end: float, text: str)`（frozen dataclass）— 実際に鳴った1文の区間（epoch 秒）と文
- `EchoFilter(tail_sec: float = 0.3, keep_sec: float = 60.0)`
  - `record(span: SpokenSpan) -> None` — 履歴に足す。`keep_sec` より古いものは捨てる
  - `overlaps(seg_start: float, seg_end: float) -> bool` — 区間 `[seg_start, seg_end]` が、どれかの `[span.start, span.end + tail_sec]` と重なれば真。本文は見ない
  - スレッドから使うので内部はロックで守る
- 純粋な値・ロジックなので、時刻は呼び出し側が渡す（テストで時刻を固定できる）

### TTS: 実際に鳴った区間を知らせる

- `TtsPlayer.set_on_played(fn: Callable[[str, float, float], None] | None)` — 1文を
  鳴らし始めた時点で、開始時刻から音声の長さぶんの区間 `fn(text, start, end)` を知らせる（`time.time()`）。
  再生に失敗した文も記録される（実害は小さい）
- コンストラクタや `make_player` の引数ではなく、`TalkDriver` がプレーヤーを作った後に設定する

### TalkDriver

- `EchoFilter` を1つ持つ（設定 `talk_echo_tail_sec` から作る。開始ごとに作り直す）
- プレーヤー作成後に `player.set_on_played(lambda text, s, e: echo.record(SpokenSpan(s, e, text)))` を呼ぶ
- `is_suppressed(source)`: talk mode 中の monitor は、**届け先が無いときだけ**真（届け先ありなら偽）
- `is_echo(source: str, seg_start: float, seg_end: float, text: str) -> bool` — monitor かつ talk mode 中かつ
  届け先ありのときだけ `EchoFilter.overlaps` を返す（`text` は使わない）。それ以外は False

### 文字起こし側（`_daemon_recorder_transcribe.py`）

- `_process_transcribe_item` で、本文が決まったあと（`word_replacer.apply` の後、ノイズ・応答フィルタの前）に
  `self.talk.is_echo(source, seg_start, seg_start + duration, text)` を尋ね、真なら書かずに debug ログを出して捨てる
  - `seg_start` は VAD スレッドが区間の確定時に `time.time() - len(segment) / SAMPLE_RATE` で測り、キューの要素に
    載せる（epoch 秒）。`duration` は `len(segment) / SAMPLE_RATE`。秒に丸めた `timestamp` からは作らない。
    丸めの誤差を `tail_sec` で吸収しようとすると、tail が長くなって Claude が話し終えた直後に始まる返事まで捨ててしまうため
    （既定の tail は出力と録音の遅れ分の 0.3 秒）
- 終了時にキューの残りを処理する経路にも同じ判定を入れる
- 捨てたときも `interim_clear` を送り、画面に Claude の声の中間テキストを残さない

### 中間文字起こし（`_daemon_recorder_capture.py`）

- monitor の中間文字起こし用の音声を取り出すとき、`TalkDriver.hides_interim(source, start, end)` が真なら作らない
  （文字起こしも翻訳も回さない）。真になるのは、届け先なしの talk mode 中の monitor と、届け先ありで区間が
  読み上げ（終了後 `tail_sec` まで）と重なる monitor。中間文字起こしは確定前の表示なので、文の判定はせず時間だけで
  止める（軽いモデルは誤認識が多く、文の一致では漏れやすい）。かぶせて話した相手の中間表示は出ないが、確定行は残る

### Config

| キー | 既定値 | 説明 |
|---|---|---|
| `talk_echo_tail_sec` | `0.3` | 読み上げ終了後この秒数までに始まった行を Claude の声とみなす（出力と録音の遅れの吸収。バッファ 0.2〜0.3 秒） |

## Error Handling

| 事象 | 挙動 |
|---|---|
| 再生の通知が来ない（合成失敗・古い文で再生しなかった） | 履歴に無いので捨てない（相手の発言として残る側に倒す） |
| しきい値の設定が不正（数値でない・範囲外） | 既定値を使う |
| 届け先ありの talk mode を終了した | monitor の扱いは通常（talk mode 外）に戻る |

## Testing

| ファイル | 対象 |
|---|---|
| `tests/test_talk_echo.py` | `EchoFilter`: 時間が重なる短い行 → 捨てる / 終了後 tail 内 → 捨てる / tail を過ぎたら残す / 文が違っても重なれば捨てる / 履歴なし → 残す / 古い履歴は消える |
| `tests/test_tts.py` | `TtsPlayer` が鳴らし始める文ごとに、再生より前に `on_played` を呼ぶ（end は start + 音声の長さ） |
| `tests/test_talk_driver.py` | 届け先ありで `is_suppressed("monitor")` が偽、`is_echo` が時間の重なりだけに従う（文が違っても捨てる） / 届け先なしでは従来どおり |
| `tests/test_talk_recorder_hook.py` | 届け先ありの talk mode で、monitor の Claude の声の行は書かれず、相手の行は `[相手]` で書かれる |

手動: 会議アプリで相手に話してもらう（または別の端末から音声を流す）。`[相手]` が transcript に入り、
Claude の読み上げは `[相手]` に入らないことを確かめる。かぶせて話したときの挙動も見る。
