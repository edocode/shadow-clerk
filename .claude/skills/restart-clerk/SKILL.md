---
name: restart-clerk
description: shadow-clerk を uv tool にインストールし直して、デーモンを再起動する。「インストールして」「再起動して」「main で再起動して」「このブランチを入れて試したい」と頼まれたときに使う。
---

# インストールと再起動

頼まれた範囲だけ行う。「インストールして」だけなら 1〜2 で止め、「再起動して」だけならコードを入れ替えず 3〜4 を行う。

## 1. インストール元を決める

`uv tool install` は指定したフォルダの作業ツリーをそのまま固める。未コミットの変更も入るので、狙いのコミットにある、きれいな作業ツリーから入れる。

- **ブランチを指定されたとき、作業中のとき:** そのブランチの worktree から入れる。
- **「main で」と言われたとき:** `git fetch origin` のあと、main のチェックアウトが `origin/main` と同じで、変更も無いときだけ、そこから入れる。そうでなければ、main のチェックアウトには触らず、作業用の worktree を `git checkout --detach origin/main` にして、そこから入れる。先に `git status --short` で、その worktree に未コミットの変更が無いことを確かめる。

## 2. インストールする

インストール元のフォルダで実行する。

```bash
uv tool install --force --refresh-package shadow-clerk --reinstall-package shadow-clerk \
  ".[spell-check,gcal,reazonspeech,moonshine,pronounce]" \
  --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"
```

- 出力に `Built shadow-clerk @ file:///<インストール元>` があることを確かめる。無ければキャッシュから戻っただけで、コードは入れ替わっていない。
- extras を省かない。省くと、デーモンは起動するのに gcal 連携や ReazonSpeech が無言で止まる。
- `--refresh-package` と `--reinstall-package` も省かない。省くと古いコードのまま残る。

## 3. 使用中でないことを確かめる

```bash
curl -s http://localhost:8765/api/status
```

`session` が `null`、かつ `talk.active` が `false` のときだけ進む。どちらかが使用中なら止めず、ユーザーに伝えて終わるのを待つ。会議中に止めると transcript が分かれる。

## 4. 再起動する

```bash
clerk-util restart -d
```

止まるのを待ってから、デーモンとして起動する。20秒で止まらなければ強制終了する。`-d` を忘れると、前面で動き続けてツール呼び出しが返らない。

repo の `.venv` の `clerk-util` は使わない（ASR が Whisper に落ちる）。

同梱スキルは配らない。スキルの版が上がっていれば、再起動後にダッシュボードの配布モーダルが出るので、ユーザーがそこで確認して配る。動いているコンソールは古いスキルのままなので、新しいスキルは配布後に「Claude と会話」を開き直すと効く。

## 5. 確かめて報告する

`clerk-util restart` とは別のツール呼び出しで確かめる（呼び出しの終了後もデーモンが生きていることを見るため）。

```bash
ps -eo pid,lstart,args | grep "[b]in/python3 .*bin/clerk-daemon"
curl -s http://localhost:8765/api/status
grep -aE "sherpa_onnx|Google Calendar 認証失敗" ~/.local/share/shadow-clerk/daemon.log | tail -3
```

- プロセスが1つだけで、起動時刻が新しく、API が応答することを確かめる。
- ログの該当行が起動後の時刻なら、extras が欠けている。
- 入れたコミット、インストール元のフォルダ、新しい PID と起動時刻を報告する。
- インストール元が worktree なら、その worktree を消す前に別の場所から入れ直すよう伝える。
- デーモンが動いていなければ、下の手順で起動する。

## `restart -d` で起動しなかったとき

ツール呼び出しの終了とともにデーモンが落ちた、ポート競合で起動しなかった、などのときは、手で止めて起動する。

止めて、プロセスが消えるまで待つ。ポートは先に閉じ、プロセスは30秒以上残ることがある。ポートだけ見て起動すると、新しいプロセスがポート競合で無言で死ぬ。時間で打ち切らない。

```bash
clerk-util stop
while ps -eo args | grep -q "[b]in/python3 .*bin/clerk-daemon"; do sleep 1; done
```

`pgrep -f` は使わない。この確認を実行している自分のシェルにも一致して、消えないように見える。

消えたら、別のツール呼び出しで起動する。`setsid` で切り離す。

```bash
setsid nohup ~/.local/share/uv/tools/shadow-clerk/bin/clerk-daemon -d </dev/null >/dev/null 2>&1 & disown
```

そのあと、5 の確認をやり直す。
