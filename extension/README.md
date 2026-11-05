# shadow-clerk screenshot extension

Captures the visible browser tab or the whole screen, stores the image next to the
transcript, and appends one `[画面]` line to the transcript being recorded.

Screen shares are invisible to the transcript: a remark like "the orange slot here"
cannot be reconstructed from words alone. This puts the shot on the same timeline
as the speech.

## Usage

Click the toolbar icon. A popup offers two buttons; the shot is taken as soon as
one is pressed:

| Button | What is captured |
|---|---|
| **This tab** | The visible tab, captured by the extension (`chrome.tabs.captureVisibleTab`) |
| **Whole screen** | Every monitor, captured by `clerk-daemon` — desktop apps such as Teams or Zoom included |

The popup closes before the whole screen is taken, so it does not appear in the
image. The badge on the icon reports the result.

| Badge | Meaning |
|---|---|
| `OK` (green) | Saved, and appended to the transcript |
| `－` (yellow) | Saved, but nothing was being recorded, so no transcript line |
| `!` (red) | Failed. See the extension's service worker console |

## Install

1. Open `chrome://extensions`
2. Enable Developer mode
3. "Load unpacked" and select `extension/`

The manifest carries a public `key`, so the unpacked extension always gets the
same ID (`ajlfjhgcplpghgdeefmpijommkjielda`). The daemon only takes a whole-screen
shot for that ID (and for the Chrome Web Store build once its ID is added). If an
older copy without the key was loaded, remove it and load `extension/` again —
its options (the port) start from the default.

### Chrome Web Store

`make extension-zip` builds `dist/shadow-clerk-extension-<version>.zip` for upload
(the `key` is stripped, as the store requires). The listing text, permission
justifications and the publishing steps are in [store/listing.md](store/listing.md);
the privacy policy is [store/privacy.md](store/privacy.md).

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
- **This tab** captures only the visible tab. Background tabs cannot be captured
- **Whole screen** is taken by the daemon, so it works for any app, with these limits:

| Platform | How the daemon captures | Notes |
|---|---|---|
| Linux, Wayland | Desktop portal (`org.freedesktop.portal.Screenshot`, non-interactive) via `jeepney` | Checked on GNOME: no dialog, about 0.6 s, all monitors in one image at the logical (scaled) resolution. The portal writes the file to the Pictures folder; the daemon moves its content and deletes that file |
| Windows, macOS, Linux X11 | `mss` | Not tested yet. macOS asks for the Screen Recording permission once. On Windows, UAC prompts, the lock screen and DRM-protected windows come out black, and the daemon must run in the user's desktop session (not as a service) |

## Endpoint

`POST http://127.0.0.1:8765/api/screenshot`

```json
{ "image": "data:image/png;base64,...", "title": "...", "url": "..." }
```

For the whole screen the extension sends `{ "source": "screen", "title": "..." }`
and the daemon captures the image itself. That request is accepted only when its
`Origin` is one of `EXTENSION_ORIGINS` in
`src/shadow_clerk/_daemon_dashboard_ops_screenshot.py`, so another extension that can
reach localhost cannot make the daemon capture your screen.

The write target is resolved in two steps: the transcript named by
`.clerk_session` while a meeting is being recorded, otherwise the recorder's
current output path (the daily transcript).

Because the endpoint writes files, **it only accepts requests from localhost**,
independently of how the dashboard itself is bound. A non-default port goes in
the options page, not the manifest.
