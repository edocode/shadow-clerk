# Google Calendar Integration Setup

shadow-clerk can automatically start and end meeting sessions based on your Google Calendar schedule. When a calendar event begins, it sends a `start_meeting` command and creates a transcript file named `transcript-YYYYMMDDHHMM@EventTitle.txt`.

## Prerequisites

- A Google account with Google Calendar
- `uv sync --extra gcal` (or `uv tool install -e ".[gcal]"`)

## Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project selector at the top → **New Project**
3. Enter a project name (e.g. `shadow-clerk`) and click **Create**

## Step 2: Enable the Google Calendar API

1. In the left menu, go to **APIs & Services** → **Library**
2. Search for `Google Calendar API`
3. Click **Enable**

## Step 3: Configure the OAuth Consent Screen

1. Go to **APIs & Services** → **OAuth consent screen**
2. Choose **User Type**:
   - **Internal** — if your account belongs to a Google Workspace organization
   - **External** — for personal Google accounts (Gmail)
3. Fill in **App name** and **User support email**, then click **Save and Continue**
4. On the **Scopes** page, click **Save and Continue** (no scopes needed here — shadow-clerk requests them automatically)
5. If you chose **External**, add your Gmail address under **Test users** on the next page

## Step 4: Create OAuth 2.0 Client Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. Set **Application type** to **Desktop app**
4. Enter a name (e.g. `shadow-clerk`) and click **Create**
5. In the dialog that appears, click **Download JSON**
6. Save the downloaded file as `credentials.json` (e.g. `~/credentials.json`)

## Step 5: Run the Authentication Flow

```bash
# Install gcal dependencies
uv sync --extra gcal

# Run OAuth flow (opens browser for account authorization)
clerk-util gcal-auth ~/credentials.json
```

A browser window opens asking you to sign in to your Google account and grant read-only calendar access. After authorization, the token is saved to `~/.local/share/shadow-clerk/gcal_token.json`.

## Step 6: Configure shadow-clerk

```bash
clerk-util write-config-value gcal_integration true
clerk-util write-config-value gcal_credentials_file ~/credentials.json
```

Optional settings:

```yaml
# config.yaml
gcal_integration: true
gcal_credentials_file: ~/credentials.json
gcal_calendar_id: primary          # Calendar ID (primary = default calendar)
gcal_buffer_minutes: 2             # Send start_meeting N minutes before event starts
gcal_end_buffer_minutes: 1         # Send end_meeting N minutes after event ends
gcal_token_file: null              # Token save path (null = data directory)
```

## How It Works

Once enabled, clerk-daemon polls Google Calendar every 60 seconds. When an event is about to start (within `gcal_buffer_minutes`), it automatically:

1. Sends a `start_meeting <EventTitle>` command
2. Creates `transcript-YYYYMMDDHHMM@EventTitle.txt`
3. Inserts a meeting start marker into the transcript

When the event ends (plus `gcal_end_buffer_minutes`), it sends `end_meeting` and (if `auto_summary: true`) generates meeting minutes as `summary-YYYYMMDDHHMM@EventTitle.md`.

All-day events are skipped.

## Troubleshooting

### "google-auth-oauthlib が見つかりません"

Run `uv sync --extra gcal` to install the required packages.

### "gcal_credentials_file が設定されていません"

Set the path in config.yaml:
```bash
clerk-util write-config-value gcal_credentials_file ~/credentials.json
```

### Token expired

Delete the token file and re-authenticate:
```bash
rm ~/.local/share/shadow-clerk/gcal_token.json
clerk-util gcal-auth ~/credentials.json
```

### External user type — "Access blocked"

If you see "This app is blocked" during authorization, your OAuth consent screen is set to **External** and you need to add your account as a test user:

1. Go to **APIs & Services** → **OAuth consent screen**
2. Click **Add users** under **Test users**
3. Add your Gmail address and save
