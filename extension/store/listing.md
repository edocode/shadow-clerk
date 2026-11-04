# Chrome Web Store listing

Text to paste into the Chrome Web Store developer dashboard. Keep it in sync with
the extension when its behaviour changes. This folder is left out of the upload zip
(`make extension-zip`).

## Publishing

1. Register a Chrome Web Store developer account (one-time fee) and verify the
   contact email.
2. `make extension-zip` → `dist/shadow-clerk-extension-<version>.zip`. The
   manifest's `key` is stripped because the store refuses it; the store assigns
   its own extension ID.
3. Upload the zip as a new item, then fill in the fields below.
4. Screenshots: at least one 1280×800 (or 640×400) PNG of the popup over a browser
   window. Small promo tile (440×280) is optional.
5. After the first upload, copy the store's extension ID and add
   `chrome-extension://<id>` to `EXTENSION_ORIGINS` in
   `src/shadow_clerk/_daemon_dashboard_ops_screenshot.py`. Without it the
   "Whole screen" button of the store build is refused by the daemon. The
   "This tab" button works either way.
6. For an update, bump `version` in `extension/manifest.json`, rebuild the zip
   and upload it to the same item.

## Store listing

**Name:** shadow-clerk screenshot

**Category:** Productivity

**Language:** English (Japanese is provided through `_locales/ja`)

**Summary** (from `_locales/*/messages.json`, ≤ 132 characters):

- en: Save the browser tab or the whole screen to shadow-clerk and add a line to the transcript being recorded.
- ja: ブラウザのタブか画面全体を shadow-clerk に保存し、記録中の transcript に1行残す

**Description (en):**

> Companion extension for shadow-clerk, an open-source meeting transcriber that
> runs on your own computer.
>
> Click the toolbar icon and pick one of two buttons:
>
> - **This tab** — captures the visible browser tab (a screen share in a browser
>   meeting, for example).
> - **Whole screen** — asks shadow-clerk on this computer to capture every monitor,
>   including desktop apps such as Teams or Zoom.
>
> The image is saved next to the transcript, and a `[画面]` line is added to the
> transcript being recorded, so the picture sits on the same timeline as the
> speech. Nothing is sent anywhere except the shadow-clerk daemon on
> `127.0.0.1`/`localhost`.
>
> Requires shadow-clerk (https://github.com/edocode/shadow-clerk) to be running.

**Description (ja):**

> 自分のパソコンで動く会議の文字起こしツール shadow-clerk の拡張です。
>
> ツールバーのアイコンを押して、2つのボタンから選びます。
>
> - **このタブ** — 表示中のタブを撮ります（ブラウザ会議の画面共有など）。
> - **画面全体** — このパソコンの shadow-clerk に全モニターを撮らせます。Teams や Zoom などのデスクトップアプリも写ります。
>
> 画像は transcript の横に保存され、記録中の transcript に `[画面]` 行が1行加わるので、画像が発言と同じ時系列に並びます。
> 送り先は `127.0.0.1` / `localhost` で動く shadow-clerk だけです。
>
> shadow-clerk（https://github.com/edocode/shadow-clerk）が動いている必要があります。

## Privacy practices

**Single purpose:** Save a screenshot of the current tab or the whole screen to the
shadow-clerk application running on the user's own computer.

**Permission justifications:**

| Permission | Why |
|---|---|
| `activeTab` | Capture the visible tab with `chrome.tabs.captureVisibleTab`, only after the user opens the popup and presses "This tab" |
| `storage` | Remember the shadow-clerk address (host and port) set on the options page |
| Host permission `http://127.0.0.1/*`, `http://localhost/*` | Send the screenshot to the shadow-clerk daemon on this computer. No other host is contacted |

**Remote code:** No. All scripts are in the package.

**Data usage:** The extension handles website content (the captured image, the
tab's title and URL) only to hand it to the shadow-clerk daemon on the same
computer. It does not collect, transmit to the developer, sell, or share any user
data, and it has no analytics.

**Privacy policy URL:**
https://github.com/edocode/shadow-clerk/blob/main/extension/store/privacy.md
