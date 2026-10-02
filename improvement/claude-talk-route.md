# Claude Talk Mode Phase 2-1: Claude の声を会議アプリに届ける

Phase 2（オンライン会議に第三者が入る talk mode）の最初の部分。Claude の声を、会議アプリのマイク入力に
足し込んで相手に届ける。前提: `improvement/claude-talk-mode.md`、`improvement/claude-talk-skill.md`。

Phase 2 は次の順に分けて進める。本 spec は 1 だけを扱う。

1. **音の経路**（本 spec）: Claude の声を会議アプリの入力に届ける。手元のヘッドセットでも聞こえる
2. 相手の発言を読み、Claude の声を除く: talk mode 中も monitor を文字起こしし、`[相手]` を Claude に渡す
3. 発言の抑え方: 第三者がいるとき、Claude がいつ口を開くか

## Goal

- talk mode の開始時に「Claude の声を届ける先」（会議アプリの録音ストリーム）を選べる
- 選ぶと、Claude の声が自分のマイクの音と一緒に会議アプリへ届き、手元のヘッドセットからも聞こえる
- 会議アプリがマイクを開き直しても、自動でつなぎ直す
- 「届ける先なし」は従来どおり（ヘッドセットに鳴らすだけ）

Non-goals: Windows / macOS の実装（差し替えられる形だけ用意する）、`[相手]` の取り込み、発言の抑え方、
PulseAudio だけの環境。

## Approach

Linux（PipeWire）では、物理マイクには書き込めないが、ひとつの入力ポートに複数のリンクがつながると
PipeWire が足し合わせる。TTS の再生ストリームを会議アプリの録音ストリームにも `pw-link` でつなげば、
仮想デバイスも会議アプリの設定変更も要らない（2026-10-03 にスパイクで確認: autoconnect=false の再生
ストリームを `pw-record` の入力にリンクすると、マイクとテスト音が足し合わされて録れた）。

TTS は名前で見つけられるストリームから鳴らす必要がある。sounddevice（PortAudio）のストリームには名前を
付けられないので、talk mode の間は `pw-cat --playback` を1本常駐させ、そこへ PCM を書き込む。

Windows / macOS（後続）は、仮想デバイス（VB-CABLE / BlackHole）に shadow-clerk が「実マイク＋TTS」を
混ぜて出す方式にする。そのため経路の部分は OS ごとの実装に差し替えられる形にする。

## Components

### Domain

- `domain/talk_route.py`: `RouteTarget(app: str, node_id: int, label: str)`（frozen dataclass）
  - `app` はストリームの `application.name`。同一性の判定は `app` で行う（`node_id` はつなぎ直すたびに変わる）
  - `label` は一覧に出す名前（`application.name` と `media.name`）

### 経路（`_daemon_talk_route.py`）

- `TalkRoute` Protocol:
  - `available() -> bool` — この環境で使えるか
  - `targets() -> list[RouteTarget]` — いま開いている録音ストリーム（自分自身は除く）
  - `connect(app: str, source_port: str) -> None` — そのアプリの録音ストリームにつなぎ、監視を始める
  - `disconnect() -> None` — 張ったリンクを外し、監視を止める。冪等
  - `status() -> dict` — `{"app": str, "connected": bool}`
- `PipeWireRoute`
  - `available()`: `pw-dump`・`pw-link`・`pw-cat` がすべて PATH にある
  - `targets()`: `pw-dump` の JSON から `media.class == "Stream/Input/Audio"` のノードを集める。
    **daemon 自身のストリームは除く**: ノードの `application.process.id`、またはノードの `client.id` が指す
    client オブジェクトの `application.process.id` が `os.getpid()` と同じなら除く（ALSA 経由のストリームは
    プロセス ID がノードではなく client 側に付く。実機で確認済み）
  - `connect()`: そのアプリのすべての録音ストリームの入力ポート（FL・FR など）に `source_port` をつなぐ。
    1秒ごとの監視スレッドで、まだつないでいない同じアプリのストリームが現れたらつなぐ（開き直し・新しいタブ）
  - コマンドの実行は差し替えられる関数（既定は `subprocess.run`）にして、テストで偽物を入れる
- `NullRoute`: `available()` は False、ほかは何もしない
- `make_route() -> TalkRoute`: Linux で `PipeWireRoute().available()` なら `PipeWireRoute`、それ以外は `NullRoute`

### 再生（`_daemon_tts_pipewire.py`）

- `PwCatSink`: `pw-cat --playback --rate 48000 --channels 1 --format s16 -P '{ node.name = "shadow-clerk-talk" }' -`
  を1本起動し、標準入力に PCM を書く。ヘッドセットへは PipeWire の自動接続でつながる
  - `start() -> str` — 起動し、ノードが `pw-dump` に現れるまで待つ（最大2秒）。出力ポート名
    （例 `shadow-clerk-talk:output_MONO`）を返す。現れなければ `TtsError`
  - `play(pcm, sr, should_stop) -> None` — 既存の `PlayFn` と同じ形。48kHz にリサンプリングし、0.1秒ずつ書き込み、
    `should_stop()` が真ならやめる。`pw-cat` のバッファに残る数十ミリ秒ぶんは鳴る
  - `stop() -> None` — 標準入力を閉じて終了させる。冪等
  - `pw-cat` が落ちていたら、`play` は1回だけ起動し直してから書く（つなぎ直しは route の監視が拾う）
- `TtsPlayer` はそのまま使う（`PwCatSink.play` を `PlayFn` として渡す）

### TalkDriver

- `start(topic, persona, workdir=None, route=None)`
  - `route` はアプリ名。None なら従来どおり（sounddevice の再生器、経路なし）
  - 指定されていれば: `make_route()` が使えなければ `TalkStartError`。`PwCatSink` を起動し、その `play` で
    `TtsPlayer` を作り、`route.connect(route, source_port)`。途中で失敗したら起動した順に片付ける
  - `talk_route_app` に覚えておく値は、ダッシュボードが保存する（driver は config を書かない）
- `stop()`: `route.disconnect()` → 再生器を閉じる → `PwCatSink.stop()`
- `snapshot()` に `route: {app, connected}`（経路なしなら `{"app": "", "connected": false}`）

### API（`_daemon_dashboard_ops_talk.py`）

| Method | Path | 内容 |
|---|---|---|
| `GET` | `/api/talk-route-targets` | `{available: bool, targets: [{app, label}]}`（同じ app は1つにまとめる） |
| `POST` | `/api/talk-mode` | body に `route?: str \| null`（200 字以内）を足す |

### Config

| キー | 既定値 | 説明 |
|---|---|---|
| `talk_route_app` | `""` | 最後に選んだ届ける先のアプリ名。開始モーダルの初期値 |

### Dashboard

- 開始モーダルに「Claude の声を届ける先」: `(なし)` と候補の一覧、再読み込みボタン。使えない環境では無効にして
  「この環境では使えません（PipeWire が必要）」と出す
- 開始時に選んだアプリ名を `talk_route_app` に保存する
- ヘッダの talk 表示に `→ <app>（接続中 / 未接続）`

## Error Handling

| 事象 | 挙動 |
|---|---|
| 届ける先を選んだが PipeWire のツールが無い | 開始しない（`TalkStartError`） |
| `pw-cat` のノードが2秒以内に現れない | 開始しない |
| 開始時に会議アプリがまだマイクを開いていない | 開始する。status は「未接続」、現れたら監視がつなぐ |
| `pw-link` が失敗した | ログと status に出し、次の監視で再試行 |
| `pw-cat` が途中で落ちた | 次の `play` で1回だけ起動し直す。それでも駄目なら status にエラー（`[Claude]` 行の書き込みは続ける） |
| 候補に daemon 自身の録音が入る | 一覧からもリンクからも必ず除く（上記のプロセス ID 判定） |

README に書くこと: 会議アプリで自分をミュートしていると Claude の声も届かない（届ける先がマイク入力その
ものなので）。ミュートを外すと自分の声と Claude の声の両方が相手に届く。

## Testing

| ファイル | 対象 |
|---|---|
| `tests/test_talk_route.py` | 偽の `pw-dump` JSON と偽のコマンド実行で: 候補の一覧、daemon 自身の除外（ノードの PID・client の PID の両方）、つなぐ・外す、つなぎ直す、`available()` |
| `tests/test_tts_pipewire.py` | 偽のプロセスで: 起動とポート名、書き込みとリサンプリング、`should_stop` での途中停止、落ちたときの起動し直し、`stop` の冪等 |
| `tests/test_talk_driver.py` | `route` 指定時に経路と `pw-cat` の再生器を使う、失敗時の片付け、stop の順序、snapshot の `route` |
| `tests/test_talk_api.py` | `/api/talk-route-targets`、`route` の入力検証 |

手動: Chromium で WebRTC の会議アプリ（またはマイクを録るテストページ）を開き、届ける先に選んで、
Claude の声が録音に入ること、ブラウザのエコーキャンセルで消されないことを確かめる。
