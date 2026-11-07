# 語学練習の聞き直し通知 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI分析ペインの「🔊 英語」を押すたびに、その英文の聞き直し回数を数え、talk mode の PTY（Claude Code）へ一行を送って Claude に伝える。

**Architecture:** 数えるのと送るのはダッシュボードの JS（`_daemon_dashboard_js_speech.py`）で行う。送信は既存の `POST /api/console/input` に `role: "talk"` を付けて使い、daemon 側のコードは変えない。clerk-practice スキルに、その通知の扱いを足す。

**Tech Stack:** Python 3.11+（JS テンプレート文字列を返すモジュール）、ブラウザ JS（node で検証）、Markdown（スキル）

**Spec:** `docs/superpowers/specs/2026-11-06-practice-replay-design.md`

## Global Constraints

- 通知の文面は設計書どおり: `[練習] 聞き直し: 「<英文>」（この文は N 回目）`。
- 英文の上限は 200 文字（`slice(0, 200)`）。
- 送り先の role は `talk` 固定。
- 通知を送るのは talk mode が動いているときだけ（`talkActive === true`）。数えるのは talk の状態に関係なく行う。
- 英文の前後の空白は除く。空文字なら数えず、送らない。
- 本文と Enter（`\r`）は別々に送り、その間は 200 ms 空ける（`_daemon_console.py` の `_send_after_ready_blocking` と同じ理由: Enter が本文と同時に届くと送信として認識されない）。
- skill を変えるので `metadata.version` を `1.17.1` から `1.18.0` にする（CLAUDE.md）。
- 文字列の扱いは、リポジトリ全体で proper noun を書かない。

## Review Focus

1. 英文に改行・タブ・ESC などの制御文字が入る → 送る前に空白へ置換し、端末の制御シーケンスとして解釈されないようにする。Task 1 のテストで確認する。
2. 🔊 を連打する → 押した回数だけ数え、押すたびに送る（送信の順番は既存の直列キューで守る）。Task 2 のテストで確認する。
3. 200 文字を超える英文 → 切って送る。途中で止まった文は、切れ目の後に続けない。Task 1 で確認する。
4. talk が動いていないのに 🔊 を押す → 数えるが送らない。Task 3 で確認する。
5. 英文のハッシュが衝突する → 53 ビットの cyrb53 を使うので、練習の中で衝突する確率は無視できる。衝突は表示上の回数に影響するだけで、データは壊れない。テストは固定の 2 文で違う値になることを確かめる。

---

### Task 1: 通知の文面とキーを作る純粋関数

**Files:**
- Modify: `src/shadow_clerk/_daemon_dashboard_js_speech.py`（`_JS_TEMPLATE_SPEECH` に関数を足す。`SAY_TAG` の近く）
- Test: `tests/test_talk_speech_js.py`（既存の node 検証に項目を足す）

**Interfaces:**
- Produces: `replayKey(text) -> string`（cyrb53 のハッシュを base36 にした文字列）、`replayNote(text, count) -> string | null`（送る一行。`text` が空白だけなら `null`）。Task 2 が使う。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_talk_speech_js.py` の既存の検証の並びに、次の項目を足す（`check(...)` の形式は既存に合わせる）。

```javascript
check("通知の文面", replayNote("Hello", 2) === "[練習] 聞き直し: 「Hello」（この文は2回目）")
check("制御文字は空白にする", replayNote("a\u001b[31mb\n", 1) === "[練習] 聞き直し: 「a [31mb」（この文は1回目）")
check("空白だけは通知しない", replayNote("   ", 1) === null)
check("200文字で切る", replayNote("x".repeat(300), 1).includes("x".repeat(200)) && !replayNote("x".repeat(300), 1).includes("x".repeat(201)))
check("キーは同じ文で同じ・違う文で違う", replayKey("I see a cheap ship.") === replayKey("I see a cheap ship.") && replayKey("a") !== replayKey("b"))
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run python tests/test_talk_speech_js.py`
Expected: 新しい項目が FAIL（`replayNote is not defined` など）。既存の項目は PASS のまま。

- [ ] **Step 3: 実装する**

`replayKey` は cyrb53（seed 0）を実装し、`toString(36)` を返す。`replayNote` は、先に `text` の制御文字（`/[\u0000-\u001f\u007f]/g`）を空白に置換して連続空白を 1 つにし、前後を trim する。空なら `null`。200 文字で切ってから文面に入れる。

- [ ] **Step 4: 通るまで確かめる**

Run: `uv run python tests/test_talk_speech_js.py`
Expected: 新しい項目もすべて PASS。

- [ ] **Step 5: Commit**

```bash
git add src/shadow_clerk/_daemon_dashboard_js_speech.py tests/test_talk_speech_js.py
git commit -m "Add replay note helpers for practice sentences"
```

---

### Task 2: talk の PTY へ本文と Enter を送る関数

**Files:**
- Modify: `src/shadow_clerk/_daemon_dashboard_js_console.py`（`sendConsole` と `_postConsole` の近く）
- Test: `tests/test_talk_speech_js.py`（送り先と順序を、`fetch` の代役で確かめる）

**Interfaces:**
- Consumes: なし（既存の `fetch('/api/console/input', …)` を使う）
- Produces: `sendTalkConsole(text) -> Promise<void>`。`{role:'talk', data:text}` を送り、200 ms 後に `{role:'talk', data:'\r'}` を送る。前の送信が終わってから次を送る直列キューを使う（既存の `_consoleSendQ` と同じ考え方）。Task 3 が使う。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_talk_speech_js.py` の harness に、`fetch` の代役で POST の順番を記録させ、次を確かめる。

```javascript
// 1 回の呼び出しで、role:'talk' の本文 → 200 ms 後に role:'talk' の "\r" の順に 2 回 POST される
await sendTalkConsole("hi");
check("本文と Enter は role talk で、本文が先", posts.map(p => [p.role, p.data]) ==
      [["talk", "hi"], ["talk", "\r"]])
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run python tests/test_talk_speech_js.py`
Expected: `sendTalkConsole is not defined` で FAIL。

- [ ] **Step 3: 実装する**

`sendTalkConsole(text)` を `_daemon_dashboard_js_console.py` に足す。専用のキュー `_talkSendQ` を持ち、`_postTalk(data)`（`fetch('/api/console/input', {method:'POST', headers, body: JSON.stringify({role:'talk', data})})`、失敗は握りつぶす）を、本文 → `setTimeout` 200 ms → `"\r"` の順で直列に呼ぶ。`sendConsole`（キー入力用）とは別のキューにする。

- [ ] **Step 4: 通るまで確かめる**

Run: `uv run python tests/test_talk_speech_js.py`
Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add src/shadow_clerk/_daemon_dashboard_js_console.py tests/test_talk_speech_js.py
git commit -m "Send text to the talk console PTY with a separate Enter"
```

---

### Task 3: 🔊 のクリックで数えて送る

**Files:**
- Modify: `src/shadow_clerk/_daemon_dashboard_js_speech.py`（`decorateSay` の `onclick`、`replayCounts` の定義）
- Test: `tests/test_talk_speech_js.py`

**Interfaces:**
- Consumes: `replayKey`, `replayNote`（Task 1）、`sendTalkConsole`（Task 2）、既存の `talkActive`（`_daemon_dashboard_js_talk.py` の `let talkActive`）
- Produces: `noteReplay(text) -> number | null`（その文の回数を返す。空なら `null`）。`onclick` から呼ぶ。

- [ ] **Step 1: 失敗するテストを書く**

```javascript
// talk が動いている: 2 回押すと 2 回送る。2 回目の通知は「2回目」
// talk が動いていない: 数えるが送らない
check("押した回数を数え、talk が動いていれば送る", ...)
check("talk が動いていなければ数えるだけ送らない", ...)
check("空の英文は数えず送らない", noteReplay("  ") === null)
```

- [ ] **Step 2: 失敗を確かめる**

Run: `uv run python tests/test_talk_speech_js.py`
Expected: `noteReplay is not defined` などで FAIL。

- [ ] **Step 3: 実装する**

`replayCounts = new Map()` をページ読み込みごとに持つ。`noteReplay(text)`: `replayNote(text, n)` が `null` なら `null` を返す。そうでなければ `replayCounts` の値を 1 増やし、`talkActive === true` なら `sendTalkConsole(note)` を呼ぶ。`decorateSay` の `onclick` は、既存の `speakText(text, sayLang(text, tag))` の後で `noteReplay(text)` を呼ぶ。`text` は読み上げに使った文（表示用の `[en|…]` の中身を含む）を使う。

- [ ] **Step 4: 通るまで確かめる**

Run: `uv run python tests/test_talk_speech_js.py`
Expected: PASS（既存の読み上げの項目も含む）。

- [ ] **Step 5: Commit**

```bash
git add src/shadow_clerk/_daemon_dashboard_js_speech.py tests/test_talk_speech_js.py
git commit -m "Count 🔊 replays and tell the talk console"
```

---

### Task 4: clerk-practice スキルに通知の扱いを足す

**Files:**
- Modify: `src/shadow_clerk/skills/clerk-practice/SKILL.md`（`metadata.version` を `1.18.0` に、通知の扱いの節を足す）
- Test: `tests/test_skill_install.py`（既存のバージョン検査が通ること）

**Interfaces:**
- Consumes: Task 3 が PTY に送る文面（`[練習] 聞き直し: 「<英文>」（この文は N 回目）`）

- [ ] **Step 1: スキルの節を書く**

SKILL.md に次を足す。
- 「[練習] 聞き直し:」で始まるユーザーの入力は、ユーザーが同じ英文を聞き取れなかったという通知。返事として声を出さない（`/api/say` を呼ばない）。
- 回数が 2 以上の文は、次に似た音の問題を出すとき、ゆっくり発声させるか、その文を次の練習候補の先頭に置く。
- 回数はその練習の中だけの情報。練習をまたいで覚えない。

- [ ] **Step 2: バージョンを上げる**

`metadata.version: "1.17.1"` を `"1.18.0"` にする。

- [ ] **Step 3: 検査する**

Run: `uv run python tests/test_skill_install.py`
Expected: PASS。

- [ ] **Step 4: Commit**

```bash
git add src/shadow_clerk/skills/clerk-practice/SKILL.md
git commit -m "clerk-practice: handle replay notes from the AI analysis pane"
```

---

### Task 5: 全体の検証

**Files:** なし（検証のみ）

- [ ] **Step 1: 関連テストを通す**

Run: `uv run python tests/test_talk_speech_js.py && uv run python tests/test_talk_speech.py && uv run python tests/test_skill_install.py`
Expected: すべて終了コード 0。

- [ ] **Step 2: 重複検査と構文検査**

Run: `make dupcheck` と `uv run python -m py_compile src/shadow_clerk/_daemon_dashboard_js_speech.py src/shadow_clerk/_daemon_dashboard_js_console.py`
Expected: 新しい重複が出ないこと。

- [ ] **Step 3: 実機で確かめる（任意・ユーザーの確認が必要）**

talk mode（clerk-practice）を起動し、AI分析の 🔊 を 2 回押す。Claude の入力欄に通知が届き、Claude が声を出さずに次の出し方に反映することを見る。ここはブラウザと音声が要るので、結果をユーザーに報告して確認してもらう。

---

## Self-Review

- 設計書の「数える単位」「送るタイミング」「送り先（PTY）」「カウントの保持（メモリのみ）」「英文の上限 200 字」「[練習] の接頭辞」「skill のバージョン上げ」を、Task 1〜4 でそれぞれ扱った。
- 設計書の未決点は次のとおり決めた（計画の Global Constraints に記載）: role は `talk`、Enter は本文と分けて 200 ms 空けて送る、通知は talk が動いているときだけ送る。
- 型とシグネチャは Task 1〜3 で一致している（`replayKey`, `replayNote`, `sendTalkConsole`, `noteReplay`）。
- 設計書のハッシュは「SHA-256 などの短い形」とあったが、同期で動く cyrb53 にした。`crypto.subtle` は非同期で、押下の処理を複雑にするため。
