# Privacy policy — shadow-clerk screenshot

The shadow-clerk screenshot extension sends data only to the shadow-clerk
application on your own computer.

## What it handles

When you press one of the buttons in its popup:

- **This tab:** the extension captures the visible tab and sends the image, the
  tab's title and its URL to the shadow-clerk daemon at the address set on the
  options page.
- **Whole screen:** the extension asks the shadow-clerk daemon to capture the
  screen. The image is taken and saved by the daemon; the extension itself does
  not receive it.

The extension only accepts a `127.0.0.1` or `localhost` address, so the data
never leaves your computer through the extension. The daemon saves the image in
its data directory and adds one line to the transcript being recorded.

## What it stores

Only the shadow-clerk address you enter on the options page, in Chrome's extension
storage.

## What it does not do

- It does not capture anything unless you press a button.
- It does not send data to the developer or to any third party.
- It has no analytics, advertising or tracking.
- It does not load remote code.

## Contact

Questions and reports: https://github.com/edocode/shadow-clerk/issues
