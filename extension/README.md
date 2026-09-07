# shadow-clerk screenshot extension

Captures the visible browser tab, stores the image next to the transcript, and
appends one `[画面]` line to the transcript being recorded.

Screen shares are invisible to the transcript: a remark like "the orange slot here"
cannot be reconstructed from words alone. This puts the shot on the same timeline
as the speech.

## Usage

Click the toolbar icon. The badge reports the result.

| Badge | Meaning |
|---|---|
| `OK` (green) | Saved, and appended to the transcript |
| `－` (yellow) | Saved, but nothing was being recorded, so no transcript line |
| `!` (red) | Failed. See the extension's service worker console |

## Install

1. Open `chrome://extensions`
2. Enable Developer mode
3. "Load unpacked" and select `extension/`

No icon image is bundled, so Chrome shows its default placeholder.

## Settings

Open the extension's options page ("Details" -> "Extension options") to point it
at a different port. Defaults to `http://127.0.0.1:8765`.

Only `127.0.0.1` and `localhost` are accepted, because the save API refuses
anything else. "Test connection" hits `/api/status` and reports what the daemon
is currently recording, so the port can be verified before saving.

Chrome match patterns cannot carry a port number, so `host_permissions` lists
the hosts alone — changing the port needs no manifest edit.

## What gets written

Images land in the data directory (`~/.local/share/shadow-clerk/` by default,
overridable with `SHADOW_CLERK_DATA_DIR`):

```
shot-202609071358@MeetingName-142144.png
```

The naming matches `advice-<stem>.md` / `analysis-<stem>.md`, so a shot can be
traced back from the transcript. Outside a named meeting the name falls back to
`shot-20260907-142144.png`.

The transcript line:

```
[2026-09-07 14:21:44] [画面] 画面キャプチャ: shot-....png | tab title | tab URL
```

Speakers are only ever `[自分]` / `[相手]`, so captures use `[画面]` as a third
label and stay distinguishable from speech. The line is not excluded from
summarization or translation, hence the `画面キャプチャ:` prefix — it keeps the
line meaningful to an LLM reading the transcript.

## Requirements

- `clerk-daemon` running (the endpoint lives on the dashboard port)
- The target must be a browser tab. Teams and Zoom desktop apps are out of reach
- **Only the visible tab can be captured.** Background tabs cannot

## Endpoint

`POST http://127.0.0.1:8765/api/screenshot`

```json
{ "image": "data:image/png;base64,...", "title": "...", "url": "..." }
```

The write target is resolved in two steps: the transcript named by
`.clerk_session` while a meeting is being recorded, otherwise the recorder's
current output path (the daily transcript).

Because the endpoint writes files, **it only accepts requests from localhost**,
independently of how the dashboard itself is bound. A non-default port goes in
the options page, not the manifest.
