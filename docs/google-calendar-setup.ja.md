# Google Calendar 連携の設定

[English](google-calendar-setup.md)

shadow-clerk は Google Calendar の予定に合わせて、会議セッションを自動で開始・終了できます。予定が始まると `start_meeting` コマンドを送り、`transcript-YYYYMMDDHHMM@予定名.txt` という transcript ファイルを作ります。

## 前提

- Google Calendar が使える Google アカウント
- `uv sync --extra gcal`（または `uv tool install -e ".[gcal]"`）

## 手順 1: Google Cloud プロジェクトを作る

1. [Google Cloud Console](https://console.cloud.google.com/) を開く
2. 上部のプロジェクト選択 → **新しいプロジェクト**
3. プロジェクト名（例: `shadow-clerk`）を入れて **作成**

## 手順 2: Google Calendar API を有効にする

1. 左メニューの **API とサービス** → **ライブラリ**
2. `Google Calendar API` を検索
3. **有効にする** を押す

## 手順 3: OAuth 同意画面を設定する

1. **API とサービス** → **OAuth 同意画面**
2. **User Type** を選ぶ:
   - **内部** — アカウントが Google Workspace 組織に属している場合
   - **外部** — 個人の Google アカウント（Gmail）の場合
3. **アプリ名** と **ユーザーサポートメール** を入れて **保存して次へ**
4. **スコープ** の画面はそのまま **保存して次へ**（ここでの指定は不要。shadow-clerk が必要なスコープを自分で要求する）
5. **外部** を選んだ場合は、次の画面の **テストユーザー** に自分の Gmail アドレスを追加する

## 手順 4: OAuth 2.0 クライアント認証情報を作る

1. **API とサービス** → **認証情報**
2. **認証情報を作成** → **OAuth クライアント ID**
3. **アプリケーションの種類** を **デスクトップアプリ** にする
4. 名前（例: `shadow-clerk`）を入れて **作成**
5. 出てきたダイアログで **JSON をダウンロード** を押す
6. ダウンロードしたファイルを `credentials.json` として保存する（例: `~/credentials.json`）

## 手順 5: 認証フローを実行する

```bash
# gcal の依存を入れる
uv sync --extra gcal

# OAuth フローを実行（ブラウザが開いてアカウントの承認を求められる）
clerk-util gcal-auth ~/credentials.json
```

ブラウザが開き、Google アカウントへのサインインと、カレンダーの読み取り専用アクセスの許可を求められます。承認するとトークンが `~/.local/share/shadow-clerk/gcal_token.json` に保存されます。

## 手順 6: shadow-clerk を設定する

```bash
clerk-util write-config-value gcal_integration true
clerk-util write-config-value gcal_credentials_file ~/credentials.json
```

任意の設定:

```yaml
# config.yaml
gcal_integration: true
gcal_credentials_file: ~/credentials.json
gcal_calendar_id: primary          # カレンダー ID (primary = 既定のカレンダー)
gcal_buffer_minutes: 2             # 予定の N 分前に start_meeting を送る
gcal_end_buffer_minutes: 1         # 予定の終了から N 分後に end_meeting を送る
gcal_token_file: null              # トークンの保存先 (null = データディレクトリ)
```

## 動作

有効にすると、clerk-daemon が 60 秒ごとに Google Calendar を確認します。予定の開始が近づくと（`gcal_buffer_minutes` 以内）、自動で次を行います。

1. `start_meeting <予定名>` コマンドを送る
2. `transcript-YYYYMMDDHHMM@予定名.txt` を作る
3. transcript に会議開始のマーカーを入れる

予定が終わると（`gcal_end_buffer_minutes` を足した時刻で）`end_meeting` を送り、`auto_summary: true` なら `summary-YYYYMMDDHHMM@予定名.md` として議事録を生成します。

終日の予定は対象外です。

## うまくいかないとき

### 「google-auth-oauthlib が見つかりません」

`uv sync --extra gcal` で必要なパッケージを入れてください。

**注意:** `uv tool install` で入れている場合、extras を付け忘れると gcal の依存が黙って外れます。必ず extras 付きで入れ直してください。

```bash
uv tool install --force --refresh-package shadow-clerk --reinstall-package shadow-clerk ".[gcal]"
```

### 「gcal_credentials_file が設定されていません」

config.yaml にパスを設定してください。

```bash
clerk-util write-config-value gcal_credentials_file ~/credentials.json
```

### トークンの期限が切れた

トークンファイルを消して、認証をやり直します。

```bash
rm ~/.local/share/shadow-clerk/gcal_token.json
clerk-util gcal-auth ~/credentials.json
```

### 外部ユーザータイプで「アクセスをブロックしました」と出る

承認中に「このアプリはブロックされています」と出る場合、OAuth 同意画面が **外部** になっていて、自分のアカウントをテストユーザーに追加する必要があります。

1. **API とサービス** → **OAuth 同意画面**
2. **テストユーザー** の **ユーザーを追加**
3. 自分の Gmail アドレスを追加して保存

## 連携が動いているかの確認

ダッシュボードの 📅 ボタンで、その日の予定と自動開始・終了の状態が見られます。

うまく動かないときは、まずログを見てください。

```bash
grep -aE "gcal" ~/.local/share/shadow-clerk/daemon.log | tail
```

「Google Calendar モニター起動」の直後に「認証失敗」が出ていれば、依存かトークンの問題です。
