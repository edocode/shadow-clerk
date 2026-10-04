# Shadow-clerk

[![PyPI version](https://img.shields.io/pypi/v/shadow-clerk.svg)](https://pypi.org/project/shadow-clerk/)
[![Python versions](https://img.shields.io/pypi/pyversions/shadow-clerk.svg)](https://pypi.org/project/shadow-clerk/)

A tool that records web meeting audio (your microphone and the speaker output) in real time and transcribes it, with live translation and meeting minutes. On top of that it can:

- run an AI assistant (Claude Code or Codex) beside the meeting in the **AI Console**, which points out open questions as the meeting goes and can write the minutes;
- let you **talk a topic through with Claude** by voice (VOICEVOX speech), and on Linux with PipeWire send Claude's voice into a meeting app;
- start and end meeting sessions from **Google Calendar**;
- put **browser screenshots** on the transcript timeline with a Chrome extension.

It runs on Linux and Windows. Transcription and LibreTranslate translation work fully offline; the rest is optional.

Available on PyPI: <https://pypi.org/project/shadow-clerk/>

## Contents

- [Platform support](#platform-support)
- [Features and requirements](#features-and-requirements)
- [Setup](#setup)
- [Usage](#usage)
  - [Starting the daemon](#starting-the-daemon) · [Recording & transcription](#recording--transcription) · [Audio device selection](#audio-device-selection) · [Audio level meters](#audio-level-meters)
  - [Dashboard](#dashboard) · [Voice commands](#voice-commands) · [CLI options](#cli-options) · [clerk-util subcommands](#clerk-util-subcommands)
  - [Translation & Summary Providers](#translation--summary-providers) · [Talk with Claude](#talk-with-claude) · [Meeting minutes](#meeting-minutes) · [AI Console](#ai-console) · [Browser screenshots](#browser-screenshots)
- [Configuration](#configuration)
- [File structure](#file-structure)
- [Troubleshooting](#troubleshooting)
- [Building standalone binaries](#building-standalone-binaries)

## Platform support

| OS | Status | Notes |
|----|--------|-------|
| Linux (PipeWire/PulseAudio) | Supported | Primary development target |
| Windows 10/11 | Supported | Monitor capture via WASAPI loopback (default playback device) |
| macOS | Not supported yet | Requires a virtual audio driver (e.g. BlackHole) — not implemented |

### Windows-specific notes

Recommended install (explicit Windows deps):

```powershell
uv python install 3.13
uv tool install --python 3.13 --with PyAudioWPatch "shadow-clerk[spell-check,gcal]"
# +ReazonSpeech k2 (Japanese ASR, optional):
uv tool install --python 3.13 --with PyAudioWPatch --with sherpa-onnx --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr" "shadow-clerk[spell-check,gcal,reazonspeech]"
```

Why explicit `--python` and `--with`:

- **`--python 3.13` (uv-managed Python)**: Microsoft Store Python runs in an AppContainer sandbox that redirects `%APPDATA%\shadow-clerk` to `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.X.YY_<id>\LocalCache\Roaming\shadow-clerk\`. The package id changes when the Python minor version is upgraded, silently moving the data directory and orphaning existing transcripts/config. uv-managed Python avoids the sandbox. Daemon startup also logs a WARNING when Store Python is detected.
- **`--with PyAudioWPatch`**: WASAPI loopback monitor capture uses [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch). It's declared as a Windows-only dep in `pyproject.toml` but some uv versions don't reliably resolve PEP 508 markers from local-editable installs, so passing it explicitly is safer.
- **`--with sherpa-onnx`** (ReazonSpeech only): Same reason — ensures uv picks the Windows wheel (with `onnxruntime.dll`) rather than a stale resolution to the Linux wheel.

Other notes:

- **Microphone permission**: Allow mic access for the terminal you launch from (Windows Settings → Privacy → Microphone).
- **Monitor capture**: Uses WASAPI loopback on the system default playback device. Switching the default device in Windows sound settings switches what gets captured.
- **Data directory**: `%APPDATA%\shadow-clerk` (the `~/.local/share/shadow-clerk` paths in the rest of this README map to that on Windows). Override with `SHADOW_CLERK_DATA_DIR` if needed.
- **Remote Desktop (RDP)**: When running inside an RDP session, the host's "Remote Audio" virtual device is auto-skipped (it would either segfault or capture nothing useful). The daemon falls back to a non-RDP loopback device if available; otherwise monitor capture is disabled and only the mic is recorded.
- **`voice_command_key`**: The default `f23` is a Linux/xremap convention. On Windows set it to `null` (disable PTT) or to one of `menu`/`ctrl_r`/`ctrl_l`/`alt_r`/`alt_l`/`shift_r`/`shift_l` in `config.yaml`.
- **Stopping the daemon**: `clerk-util stop` works (Windows path uses `taskkill`). `clerk-util start` runs the daemon in the foreground with Ctrl+C handling, mirroring Linux. `clerk-daemon --daemon` detaches instead: there is no `fork()`, so it relaunches itself with `DETACHED_PROCESS` and the parent exits.
- **AI Console**: uses ConPTY through [pywinpty](https://github.com/andfoy/pywinpty), declared as a Windows-only dependency. Without it the daemon still runs; only the console reports the missing package and refuses to start.
- **Talk with Claude**: sending Claude's voice into a meeting app needs PipeWire, so that option is disabled on Windows.
- **Standalone binary**: `clerk-daemon.exe` and `clerk-util.exe` can be built with PyInstaller. See [Building standalone binaries](#building-standalone-binaries).

## Features and requirements

| Feature | Requires | Quality | Speed | Related settings |
|---|---|:---:|:---:|---|
| Transcription (default) | faster-whisper (included) | 3 | 4 | `default_model`, `default_language` |
| Transcription (Kotoba-Whisper) | Same (auto-downloaded on first use) | 5 | 3 | `japanese_asr_model: kotoba-whisper` |
| Transcription (ReazonSpeech) | `uv sync --extra reazonspeech` | 5 | 4 | `japanese_asr_model: reazonspeech-k2` |
| Interim transcription | Same | 2 | 5 | `interim_transcription: true`, `interim_model` |
| Translation (LibreTranslate) | LibreTranslate server | 2 | 4 | `translation_provider: libretranslate` |
| Translation (OpenAI compatible API) | OpenAI compatible API | 3-5 | 2-5 | `translation_provider: api`, `api_endpoint`, `api_model` |
| Translation (Claude) | Claude Code CLI (`claude -p`) | 5 | 2 | `translation_provider: claude` |
| Language detection (pre-translation) | langdetect (included) | — | — | Automatically detects source language to select correct prompt |
| Summary (Claude) | Claude Code CLI (`claude -p`) | 5 | 3 | `llm_provider: claude` |
| Summary (OpenAI compatible API) | OpenAI compatible API | 3-5 | 2-5 | `llm_provider: api`, `api_endpoint`, `api_model` |
| Voice commands (PTT) | None (built-in) | — | — | `voice_command_key` |
| Voice commands (LLM matching) | OpenAI compatible API | — | — | `llm_provider: api`, `api_endpoint`, `api_model` |
| Spell check (pre-translation) | transformers (auto-downloaded on first use) | — | — | `libretranslate_spell_check: true` |
| [AI Console](#ai-console) (meeting assistant) | Claude Code or Codex CLI, skill from `clerk-util install-skill` | — | — | `auto_analyze`, `ai_assistant_command` |
| [Talk with Claude](#talk-with-claude) | Claude Code CLI, a running VOICEVOX engine | — | — | `talk_*` |
| Send Claude's voice into a meeting app | Linux with PipeWire (`pw-dump`, `pw-link`, `pw-cat`) | — | — | `talk_route_app` |
| [Google Calendar](#optional-google-calendar-integration) (auto start/end, expected attendees) | `gcal` extra, OAuth credentials | — | — | `gcal_integration`, `gcal_credentials_file` |
| [Browser screenshots](#browser-screenshots) in the transcript | Chrome extension in `extension/` | — | — | — |

**Minimal setup without LLM:** Transcription + LibreTranslate translation requires no external API or Claude Code. Everything runs locally.

See the [Feature Tour](docs/feature-tour.en.md) for a visual walkthrough with screenshots.

## Setup

### 1. System packages (Linux only)

```bash
sudo apt install libportaudio2 portaudio19-dev
```

On Windows no system package is needed — the `sounddevice` wheel ships PortAudio. Use the install command in [Windows-specific notes](#windows-specific-notes) instead of step 2.

### 2. Install

Install from PyPI:

|  | Command |
|---|---|
| Basic | `uv tool install shadow-clerk` |
| + ReazonSpeech | `uv tool install "shadow-clerk[reazonspeech]" --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"` |
| + Spell check | `uv tool install "shadow-clerk[spell-check]"` |
| + Both (ReazonSpeech + Spell check) | `uv tool install "shadow-clerk[spell-check,reazonspeech]" --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"` |
| + Google Calendar | `uv tool install "shadow-clerk[gcal]"` |
| All | `uv tool install "shadow-clerk[spell-check,gcal,reazonspeech]" --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"` |

> **Note:** `uv tool install` maintains a single environment per tool. When reinstalling with different extras, use `--force` — without it, `uv tool install` reports "already installed" and does not add the extra. Only the extras specified in the command are included; previously installed extras are removed.

> **Why `reazonspeech-k2-asr` is `--with`'d separately:** The `reazonspeech-k2-asr` package is only distributed via Git (not on PyPI), and PyPI rejects direct URL references in package metadata, so it cannot be declared inside the `reazonspeech` extra. Pass it via `--with` whenever you need ReazonSpeech k2.

Alternative: `pipx install shadow-clerk` (or `pip install shadow-clerk` inside a venv) also works.

### 2a. For development

```bash
git clone https://github.com/edocode/shadow-clerk.git
cd shadow-clerk
```

|  | Command |
|---|---|
| Basic | `uv sync` |
| + ReazonSpeech | `uv sync --extra reazonspeech` |
| + Spell check | `uv sync --extra spell-check` |
| + Both (ReazonSpeech + Spell check) | `uv sync --extra spell-check --extra reazonspeech` |
| + Google Calendar | `uv sync --extra gcal` |
| All | `uv sync --extra spell-check --extra gcal --extra reazonspeech` |

**Each `uv sync` defines the whole environment, and extras do not accumulate.**
`uv sync --extra gcal` after `uv sync --extra reazonspeech` removes ReazonSpeech
again — name every extra you want in the same command, as in the last row above.
For the same reason, anything installed with `uv pip install` is undeclared and
is removed by the next `uv sync`, so run it last.

This is all you need for transcription. The following optional extras are available:

### Optional: Japanese ASR models

**Kotoba-Whisper** — No extra install required. The model is auto-downloaded on first use. Just set:

```yaml
# config.yaml
japanese_asr_model: kotoba-whisper
```

**ReazonSpeech k2** — Requires the `reazonspeech` extra plus the `reazonspeech-k2-asr` package, which is only distributed via Git (not on PyPI), so it must be installed separately:

```bash
uv tool install "shadow-clerk[reazonspeech]" \
  --with "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"
# or for development — in this order, and do not run uv sync afterwards:
uv sync --extra reazonspeech
uv pip install "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"
```

`reazonspeech-k2-asr` cannot be declared in `pyproject.toml` (PyPI rejects direct
URL references in metadata), so `uv sync` does not know about it and removes it.
Check what you have with:

```bash
uv run python -c "import sherpa_onnx, reazonspeech.k2.asr; print('ok')"
```

```yaml
# config.yaml
japanese_asr_model: reazonspeech-k2
```

### Optional: Spell check (pre-translation correction)

Requires the `spell-check` extra (installs `transformers`, `torch`, `sentencepiece`):

```bash
uv tool install "shadow-clerk[spell-check]"
# or for development:
uv sync --extra spell-check
```

```yaml
# config.yaml
libretranslate_spell_check: true
spell_check_model: mbyhphat/t5-japanese-typo-correction  # default
```

The spell check model is auto-downloaded on first use. It corrects Japanese speech recognition typos before sending text to LibreTranslate.

### Optional: Google Calendar integration

Automatically starts and ends meeting sessions based on your Google Calendar schedule. Requires the `gcal` extra:

```bash
uv tool install "shadow-clerk[gcal]"
# or for development:
uv sync --extra gcal
```

Then authenticate and configure:

```bash
# One-time OAuth setup (opens browser)
clerk-util gcal-auth ~/credentials.json

# Enable in config (gcal-auth already does this when it succeeds)
clerk-util write-config-value gcal_integration true
clerk-util write-config-value gcal_credentials_file ~/credentials.json
```

When enabled, clerk-daemon polls Google Calendar every 60 seconds. Events automatically trigger `start_meeting` / `end_meeting`, creating transcript files named `transcript-YYYYMMDDHHMM@EventTitle.txt`. The event's invitees are saved as the meeting's expected attendees and shown above its summary, and the 📅 button in the dashboard header lists today's events.

See [docs/google-calendar-setup.md](docs/google-calendar-setup.md) for full setup instructions including how to obtain `credentials.json` from Google Cloud Console.

Add the following options if you need translation or summarization.

### 3. (Optional) LibreTranslate setup

Local translation without LLM. Install via Docker or pip:

```bash
# Docker (recommended)
docker run -d -p 5000:5000 libretranslate/libretranslate

# Or pip
pip install libretranslate
libretranslate --host 0.0.0.0 --port 5000
```

Configuration:

```yaml
# config.yaml
translation_provider: libretranslate
libretranslate_endpoint: http://localhost:5000
```

### 4. (Optional) OpenAI compatible API setup

Used for translation, summarization, and LLM voice command matching:

```yaml
# config.yaml — OpenAI
llm_provider: api
api_endpoint: https://api.openai.com/v1
api_model: gpt-4o
# Add SHADOW_CLERK_API_KEY=sk-... to ~/.local/share/shadow-clerk/.env
```

```yaml
# config.yaml — Ollama (local)
llm_provider: api
api_endpoint: http://localhost:11434/v1
api_model: llama3
```

### 5. (Optional) Use Claude CLI as the LLM provider

If you have Claude Code installed (`claude` on your `$PATH`), shadow-clerk can shell out to `claude -p` for translation and summarization. Set in `config.yaml`:

```yaml
llm_provider: claude
claude_cli_model: haiku   # or sonnet / opus / a full model id
# claude_cli_path: claude  # full path if not on $PATH
```

This uses your existing Claude Code OAuth login. No extra setup needed — translation and summarization run inside the daemon as background threads, no Claude Code session required.

## Usage

### Starting the daemon

If you installed via `uv tool install`:

```bash
clerk-daemon
```

For development (`uv sync`):

```bash
uv run clerk-daemon
```

> **Note:** `uv run` uses the project `.venv`, while `uv tool install` uses its own isolated environment. Make sure extras (e.g. `spell-check`, `reazonspeech`) are installed in the matching environment.

The dashboard is served at <http://localhost:8765>.

### Recording & transcription

```bash
# Basic (record mic + system audio, auto-transcribe)
clerk-daemon

# List available devices
clerk-daemon --list-devices

# With options
clerk-daemon \
  --language ja \
  --model small \
  --output ~/my-transcript.txt \
  --verbose

# In the background (logs go to daemon.log in the data directory)
clerk-daemon -d
```

Press `Ctrl+C` to stop recording (or `clerk-util stop` for a background daemon).

### Audio device selection

`mic_device` / `monitor_device` pin capture to a device by **name**, not device number — device numbers shift between daemon runs and can even change while the daemon is running. `null` (the default) follows the OS default device. Pick a device from the dashboard settings panel.

If the configured device disappears (unplugged, sink removed), the daemon falls back to the automatic device and keeps recording, then switches back on its own once the device reappears. The configured value is never overwritten by the fallback. If the device never actually disappeared — another application just grabbed it exclusively — the daemon won't retry on its own; use "Refresh list" to force a retry once it's free.

The `--mic` / `--monitor` CLI flags (device numbers, see [CLI options](#cli-options)) take priority over `mic_device` / `monitor_device`. While a flag is in effect, the corresponding dropdown is disabled on the dashboard.

A device connected after the daemon started won't appear in the dropdown until the list is refreshed ("Refresh list" in the settings panel); refreshing briefly interrupts both capture streams.

### Audio level meters

The dashboard header shows a level bar for each capture path (mic/speaker), next to the mute buttons. The bars use the crest factor — peak level divided by RMS — to tell real speech from noise: speech runs 3–10 or higher, while steady electrical noise (a dead built-in mic emitting only hum, say) sits at 1–2.

A bar highlights yellow after 10 seconds of loud-but-flat audio (steady noise, no speech dynamics) — this applies to both mic and monitor. The mic bar additionally turns red after 30 seconds of exact silence: a live microphone always has some noise floor, so true zero means nothing is reaching it at all (e.g. a powered-off headset whose dongle still shows up as a device). The monitor skips this check — a sink monitor reads back exactly zero whenever nothing is playing, which is its normal idle state, not a fault. Both bars also get a fallback outline when the configured device for that path is unavailable and the automatic one is in use, matching the fallback described above.

### Dashboard

The dashboard (<http://localhost:8765>, `--dashboard-port` to change) shows the transcript and translation live and is where most features are driven from.

| Area | What it holds |
|---|---|
| Header | Meeting and translation toggles, **Summary** (generate minutes), **Talk with Claude**, font size, transcript/translation layout, **Glossary**, PTT, custom **Commands**, 📅 today's Google Calendar events (only when the integration is on), ⚙ settings, ❓ help |
| Left pane: **Dates** / **Meetings** / **Search** | Daily transcripts by date; meeting files grouped by name (sort by name or newest, rename a meeting group, ⚙ per-meeting working directory); search by year/month/day/hour and text across transcripts, translations and summaries |
| Transcript / Translation | Live text with mute buttons and [level meters](#audio-level-meters). ⏱ turns part of a daily transcript into meetings: split it all (or a selection) at silences of a chosen length, or extract the selected lines. 📂 assigns a meeting file to an existing or new meeting name, 🗑 deletes the file or merges a meeting back into the daily transcript |
| Right pane: **Summary** / **AI Analysis** | The minutes (copy, reload, regenerate; expected attendees from the calendar on top). **AI Analysis** shows the AI Console's Advice and Analysis documents and its **Start analysis** button |
| Bottom pane: **AI Console** / **Talk with Claude** / **Logs** | The two [AI Console](#ai-console) terminals (meeting assistant and [talk](#talk-with-claude)) with the transcript beside them, and the daemon log |

A **Welcome** dialog appears on first run: it offers to install the skill for an AI agent and points to the settings worth checking first ("Do not show this again" hides it). When the bundled skill is newer than the installed copy, a dialog offers to update it.

### Voice commands

#### Push-to-Talk (recommended)

Hold down the push-to-talk key while speaking a command — no wake word needed:

```
[Hold PTT key] "start translation" → Translation starts
[Hold PTT key] "start meeting"     → Meeting session starts
```

The key is `voice_command_key` in `config.yaml`. The default `f23` suits a keyboard remapper (e.g. xremap mapping the Menu key to F23); other values are `menu` (the Menu key next to Right Alt), `ctrl_r`, `ctrl_l`, `alt_r`, `alt_l`, `shift_r`, `shift_l`. Set to `null` to disable. On Windows, see [Windows-specific notes](#windows-specific-notes).

#### Prefix mode (fallback)

During recording, say the wake word (default: "sheruku" / "シェルク") followed by a command for hands-free control:

| Voice command | Action |
|---|---|
| "sheruku, start meeting" | Start a new meeting session |
| "sheruku, end meeting" | End the meeting session |
| "sheruku, language ja" | Switch transcription language to Japanese |
| "sheruku, language en" | Switch transcription language to English |
| "sheruku, unset language" | Reset to auto-detect |
| "sheruku, start translation" | Start the translation loop |
| "sheruku, stop translation" | Stop the translation loop |

The separator (comma, space) between the wake word and command is optional. The wake word can be changed via `wake_word` in `config.yaml`.

#### Custom voice commands

You can register custom voice commands in `config.yaml` under `custom_commands` (or with the **Commands** button on the dashboard). They are evaluated after built-in commands:

```yaml
custom_commands:
  - pattern: "youtube"
    action: "xdg-open https://www.youtube.com"
  - pattern: "gmail|mail"
    action: "xdg-open https://mail.google.com"
```

- `pattern`: Regular expression (case-insensitive)
- `action`: Shell command to execute

Start the meeting analysis by voice. This pattern fires when you say it while
holding the PTT key, with or without a leading `クラーク`:

```yaml
custom_commands:
  - pattern: (クラーク|クラーク、)?分析(開始|して)
    action: curl -sX POST localhost:8765/api/console/start
```

#### LLM fallback

If a voice command doesn't match any built-in or custom command and an LLM is configured (`api_endpoint`, or `llm_provider: claude`), the utterance is sent to the LLM as a query. The response is printed to stdout and saved to `.clerk_response`.

```
"sheruku, what is 1+1?" → LLM returns the answer
```

### CLI options

`clerk-daemon` options:

| Option | Description | Default |
|---|---|---|
| `--output`, `-o` | Output file path | `~/.local/share/shadow-clerk/transcript-YYYYMMDD.txt` |
| `--model`, `-m` | Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`) | `small` |
| `--language`, `-l` | Language code (`ja`, `en`, etc.). Auto-detect if omitted | Auto |
| `--mic` | Microphone device number | Auto-detect (or `mic_device` config) |
| `--monitor` | Monitor device number (sounddevice) | Auto-detect (or `monitor_device` config) |
| `--backend` | Audio backend (`auto`, `pipewire`, `pulseaudio`, `sounddevice`, `wasapi`) | `auto` |
| `--list-devices` | List devices and exit | - |
| `--verbose`, `-v` | Verbose logging | - |
| `--dashboard` / `--no-dashboard` | Enable/disable dashboard | Enabled |
| `--dashboard-port` | Dashboard port number | `8765` |
| `--beam-size` | Whisper beam size (`1`=fast, `5`=accurate) | `5` |
| `--compute-type` | Whisper compute precision (`int8`, `float16`, `float32`) | `int8` |
| `--device` | Whisper device (`cpu`, `cuda`) | `cpu` |
| `--daemon`, `-d` | Run in the background; logs go to `daemon.log` in the data directory | - |

### clerk-util subcommands

`clerk-util` manages the daemon and the data directory. Run `clerk-util help` for the same list.

| Subcommand | Description |
|---|---|
| `start [opts]` | Run clerk-daemon with these options, in the foreground (add `-d` to run it in the background) |
| `stop` | Stop clerk-daemon (SIGTERM on Linux, `taskkill` on Windows) |
| `restart [opts]` | Stop clerk-daemon, wait for it to exit, then start it with these options |
| `recorder-status` | Print `running` or `stopped` |
| `command <cmd>` | Send a command to the running daemon: `start_meeting`, `end_meeting`, `translate_start`, `translate_stop`, ... |
| `summarize [DATE\|FILE] [--mode full\|update]` | Generate minutes (`full` by default). DATE is `YYYYMMDD` or `YYYYMMDDHHMM[@name]`, FILE a `transcript-*.txt`; without either, the current meeting or today |
| `ls` | List the data directory (and the output directory if it differs) |
| `read-config` | Print `config.yaml` (writes one with the defaults if missing) |
| `write-config-value <key> <value>` | Change one key in `config.yaml` |
| `gcal-auth <credentials.json> [token_file]` | Google Calendar OAuth; on success it also enables `gcal_integration` |
| `install-skill [--target claude\|agents\|<path>] [--link] [--force]` | Install the bundled skills for an AI agent (see [AI Console](#ai-console)) |
| `run-llm <args...>` | Run the LLM client directly (`translate`, `query`, `match-command`, `summarize`, `spell-check`) |
| `help` | Show usage |

### Translation & Summary Providers

Translation and summary each support multiple providers with different operation modes:

#### Claude mode (`translation_provider: claude` / `llm_provider: claude`)

clerk-daemon shells out to `claude -p` per request, reusing your existing Claude Code OAuth login.

- **Highest quality** — especially for Japanese homophone correction (ja→ja)
- **Requires `claude` on PATH** — found automatically if Claude Code is installed
- **No Claude Code session required** — the daemon spawns `claude -p` per job, so you don't need to keep a Claude Code terminal open
- **Translation and summary both run inside daemon threads** — same plumbing as api / libretranslate
- **Cost tracking**: `claude -p --output-format json` returns `total_cost_usd`, which is logged by the daemon

```yaml
# config.yaml
translation_provider: claude   # Translation by Claude
llm_provider: claude           # Summary by Claude (default)
claude_cli_path: claude        # full path if not on PATH
claude_cli_model: haiku        # haiku / sonnet / opus or a full model id
```

#### API mode (`translation_provider: api` / `llm_provider: api`)

clerk-daemon calls an external API (OpenAI-compatible) internally. Claude Code is not required.

- **Works without Claude Code** — clerk-daemon handles translation and summary on its own
- **Quality depends on model** — high-end models (GPT-4o) produce good results; smaller models may struggle with Japanese correction
- **How translation works**: An internal thread in clerk-daemon processes translation. Started/stopped via voice commands or dashboard
- **Summary works similarly**: `clerk-util summarize` generates minutes via the external API

```yaml
# config.yaml
translation_provider: api     # Translation via external API
llm_provider: api             # Summary via external API
api_endpoint: https://api.openai.com/v1
api_model: gpt-4o
```

#### LibreTranslate mode (`translation_provider: libretranslate`)

Translation only. Runs locally without any external API or Claude Code (summary still needs `llm_provider`).

#### Recommended configurations

| Use case | Translation | Summary | Notes |
|---|---|---|---|
| Best quality (Claude CLI) | `translation_provider: claude` | `llm_provider: claude` | Highest quality, needs `claude` CLI |
| Autonomous (external API) | `translation_provider: api` | `llm_provider: api` | OpenAI-compatible, quality varies by model |
| Fully local | `translation_provider: libretranslate` | — | No LLM needed, lower quality |
| Hybrid | `translation_provider: api` | `llm_provider: claude` | Auto translation + high-quality summary |

### Talk with Claude

Talk mode lets you discuss a topic with Claude by voice. Claude asks questions and replies
through text-to-speech; your answers are transcribed as usual. Both sides are written to the
transcript (`[Claude]` lines are Claude's), so you can read the discussion back later.

Requirements:

- [Claude Code](https://claude.com/claude-code) CLI (`claude_cli_path`)
- A running [VOICEVOX](https://voicevox.hiroshiba.jp/) engine (default `http://localhost:50021`).
  The engine runs as a separate process and is not bundled. Follow the terms of the voice you
  use; the dashboard shows the required credit (`VOICEVOX:<name>`) while talk mode is on.
- Headphones. While talk mode is on, the monitor channel is not transcribed, so Claude's own
  voice does not come back as `[Others]` lines.

Click **Talk with Claude** in the dashboard header, enter a topic (or leave it empty), pick a
persona, and start. **Voice settings** in the same dialog picks the VOICEVOX speaker and adjusts speed, pitch, intonation and volume, with a preview button; changes apply from the next sentence. By default Claude runs in a second AI Console (**Talk with Claude** tab) with the `clerk-talk` skill,
so it can edit files and run commands with the usual permission prompts, and the meeting helper keeps
running in the **AI Console** tab. Set `talk_engine: headless` to use a background `claude -p` process
instead: it answers a little faster but cannot ask for permission, so it only gets the tools in
`talk_allowed_tools`. Install the skills with `clerk-util install-skill` (all of them are installed together).
The `clerk-talk` skill pre-approves only its own `curl` calls to `http://localhost` (and `Monitor` and `Agent`); if
Claude Code still asks, allow them once, or add the same rules to your Claude Code settings.
Screen captures taken with the [browser extension](#browser-screenshots) during talk mode are looked at by a background subagent, so Claude can follow "this box here".

**Sending Claude's voice to a meeting (Linux, PipeWire).** In the start dialog, pick the meeting app under
**Send Claude's voice to**. shadow-clerk plays the speech through a named PipeWire stream and links it into that
app's microphone input with `pw-link`, so the other participants hear Claude mixed with your microphone, and you
still hear it in your headset. If the app reopens its microphone, the link is restored automatically. Muting
yourself in the meeting app mutes Claude too, because the voice goes into the same input. Needs `pw-dump`,
`pw-link` and `pw-cat`; on other platforms the option is disabled. With a route set, speech plays to PipeWire's
default output and `talk_output_devices` is not used.

While a meeting app is chosen, the other participants are transcribed as `[Others]` again, so Claude can follow
them. Claude's own voice also reaches your headset and therefore the monitor channel; monitor lines that overlap
Claude's speech in time (or start within `talk_echo_tail_sec` after it) are dropped, whatever they say, because short
replies and fillers can't be told apart from Claude's voice by text. If someone talks over Claude, their words in
that overlap are dropped too. Without a meeting app chosen, the monitor stays muted during talk mode as before.
Interim (live) monitor text is not shown while Claude is speaking.

You can also make Claude speak any text:

```bash
curl -s -X POST localhost:8765/api/say -d '{"text":"Hello"}'
```

Claude never stops listening on its own: when the conversation seems to be over, it asks first, and only on a
clear yes does it end talk mode with `POST /api/talk-end`. That call lets the sentence being spoken finish first.

If you want to speak another language (for example to practise English while the recognition language is `ja`,
which would turn English into katakana), just tell Claude: it switches the recognition language with
`POST /api/language` (`{"language": "en"}`, or `"auto"`) and switches back before the conversation ends.

**Language practice.** In talk mode, say that you want to practise a language ("I want to practise English").
Claude switches to the bundled `clerk-practice` skill: it starts a practice meeting (`英語練習` for English) without
the meeting assistant, reads the end of the last few practice sessions to suggest what to do today, and runs
conversation, pronunciation or composition practice. Corrections go to **Advice** and the practice log with example
sentences to **Analysis** in the AI analysis tab; lines starting with 🔊 are read aloud in the current recognition
language when you click them. Claude speaks practice-language sentences with the browser's voice (Web Speech API)
instead of VOICEVOX, so keep the dashboard open and click it once (browsers only allow speech after a user action);
without such a tab those sentences fall back to VOICEVOX. The speaker (monitor) is muted while practising, and
Claude ends with a "今日の練習のまとめ: …" line that the next session builds on.

The skill uses these localhost-only endpoints, which you can also call yourself:

| Endpoint | Body / query | Effect |
|---|---|---|
| `POST /api/meeting` | `{"action": "start", "name": "…", "analyze": false}` or `{"action": "end"}` | Start or end a meeting; `analyze: false` skips the AI assistant even with `auto_analyze` |
| `POST /api/mute` | `{"source": "mic" or "monitor", "muted": true}` | Same as the mute buttons; returns `previous` |
| `POST /api/generated` | `{"kind": "advice" or "analysis", "mode": "replace" or "append", "text": "…"}` | Write the current transcript's advice/analysis (up to 20,000 characters) |
| `GET /api/meeting-history` | `?meeting=…&count=3&tail=15` | `tail` (0–50) adds the last lines of each past transcript |
| `POST /api/say` | `{"text": "…", "lang": "en"}` | A `lang` other than the VOICEVOX language is read by the dashboard's browser voice (ignored when Claude's voice is sent to a meeting app) |

`GET /api/watch` without `file` follows the current transcript: when the day changes or a meeting starts or ends it
sends `<notice>…</notice>` and continues with the new file, so Claude keeps hearing you past midnight.

| Key | Default | Description |
|---|---|---|
| `talk_voicevox_url` | `http://localhost:50021` | VOICEVOX engine |
| `talk_speaker_id` | `3` | VOICEVOX style ID |
| `talk_speed` / `talk_pitch` / `talk_intonation` / `talk_volume` | `1.0` / `0.0` / `1.0` / `1.0` | Speed (0.5–2.0), pitch (-0.15–0.15), intonation (0–2), volume (0–2) |
| `talk_output_devices` | `[]` | Output device names (empty = default output). Not used when a route is set; pw-cat plays to the default output |
| `talk_engine` | `console` | `console` (AI Console + clerk-talk skill) or `headless` (`claude -p`) |
| `talk_route_app` | `""` | Last app chosen under "Send Claude's voice to" (start-dialog default) |
| `talk_echo_tail_sec` | `0.3` | A monitor line that starts within this many seconds after Claude stops speaking is treated as Claude's own voice (covers output and capture latency). Lines that start later are kept. If the other side starts talking right after Claude with no silence gap, the VAD merges the two into one segment and it is dropped |
| `talk_workdir` | `""` | Working directory for the talk session (empty = `ai_assistant_workdir`, then home). The start dialog can override it per session |
| `talk_model` | `""` | Model for the talk session (empty = claude default); applies to both engines, picked in the start dialog |
| `talk_allowed_tools` | `WebSearch,WebFetch,Read,Grep,Glob` | Tools Claude may use while talking (`""` = none) (headless only) |
| `talk_language` | `""` | Conversation language (empty = `translate_language`). Falls back to the TTS default when unsupported (VOICEVOX: Japanese only) |
| `talk_personas` | `{}` | Name → personality / how to respond. Edit from the start dialog |
| `talk_default_persona` | `""` | Persona selected by default |
| `talk_filler_sec` | `8` | If Claude has said nothing for this many seconds after you spoke, say a short "hmm" (not written to the transcript). At most once while waiting for a reply, and at least 30 s apart. `0` disables it. Also in Settings |
| `talk_stop_words` | `["待って", "ストップ", "止めて", "やめて", "stop", "wait", "hold on"]` | Saying one of these stops Claude mid-sentence. Substring match, so avoid short kana that appear inside other words; ASCII words match whole words |

Claude speaks each part of a reply as soon as it is written, in short sentences, so you can cut in
between them. Say a stop word ("wait", "ちょっと待って") and playback stops, the rest of that turn
is dropped, and Claude is told where it was cut off.

### Meeting minutes

Three ways to generate minutes: automatically at meeting end, on demand from the dashboard, or via `clerk-util` from the command line:

```
clerk-util start -d                                # Start daemon (background)
clerk-util stop                                    # Stop daemon
clerk-util recorder-status                         # Show running state
clerk-util summarize                               # Generate minutes for the current meeting (or today)
clerk-util summarize --mode update                 # Update minutes from the transcript diff
clerk-util summarize 20260425 --mode full          # Specify date
clerk-util command start_meeting                   # Start meeting session
clerk-util command end_meeting                     # End meeting session (auto_summary linked)
clerk-util command translate_start                 # Start translation loop
clerk-util command translate_stop                  # Stop translation loop
```

Meeting start/end is also available via **voice commands** ("sheruku, start meeting" / "sheruku, end meeting") or **dashboard buttons**. The dashboard's **Summary** button can trigger minutes generation at any time.

When `auto_summary` is on and the [AI Console](#ai-console) is running at meeting end, the minutes are written by the assistant in the console instead (`auto_summary_via_console`, on by default); otherwise the configured LLM writes them.

Generated meeting minutes are saved to `~/.local/share/shadow-clerk/summary-YYYYMMDD.md` (`summary-YYYYMMDDHHMM@Title.md` for a meeting). Put a `summary_template.md` in the data directory to use your own minutes format.

### AI Console

An AI assistant (`claude` or `codex`) can run inside a PTY under the dashboard's **AI Console** tab (next to **Logs**), watching the meeting transcript and writing generated documents back for the dashboard to display.

- **Installing the skill**: the assistant runs a bundled skill (`clerk-meeting-helper`; `clerk-talk` and `clerk-practice` for [talk mode](#talk-with-claude) are installed with it) that has to be copied into the agent's own skills directory. The Welcome dialog offers this on a first run, and the command does the same:

  ```bash
  clerk-util install-skill                        # ~/.claude/skills/   (Claude Code)
  clerk-util install-skill --target agents        # ~/.agents/skills/   (Codex and others)
  clerk-util install-skill --target /path/to/dir  # anywhere else; remembered for updates
  clerk-util install-skill --link                 # symlink instead of copy (POSIX only)
  ```

  A destination holding a skill shadow-clerk did not write is left alone unless you pass `--force`.
- **Starting**: automatically when a meeting starts (`auto_analyze: true`), or manually with the **Start analysis** button (AI Analysis tab) or the console's **Launch** button. Either way, `ai_assistant_init_prompt` (default `/clerk-meeting-helper {transcript} {lang}`) is sent to the PTY once the assistant's TUI is ready — `{transcript}` and `{meeting}` are substituted with the active file paths, and `{lang}` with `translate_language`, so the skill writes in the language you read.
- **Reaching the dashboard**: the assistant calls the dashboard's HTTP API at `$SHADOW_CLERK_URL`, which the console puts in its environment, so it never has to guess the port.
- **Generated documents**: shown in the right pane's **AI Analysis** tab:
  - `advice-<stem>.md` — open questions and suggestions (overwritten each time)
  - `analysis-<stem>.md` — confirmed facts (appended)

  Both are Markdown and are rendered to HTML server-side. Raw HTML inside them
  is escaped, never rendered.
- **Minutes**: with `auto_summary: true` and `auto_summary_via_console: true` (the default), the minutes at meeting end are written by the assistant while it is running.
- **Session lifecycle**: one PTY session is reused for the whole run; it is **not** stopped when the meeting ends, so it stays available for writing up minutes afterward. Stop it from the Console tab's stop button.
- **Working directory**: `ai_assistant_workdir` sets the default launch directory. Per-meeting overrides live in `DATA_DIR/meeting.yaml` (`meetings[].workdir`), editable from the gear icon (⚙) on each meeting's row in the meeting list. The first time shadow-clerk writes to a `config.yaml` it didn't create itself, it saves a one-time `<path>.bak` copy alongside it, since the YAML writer preserves keys but not your hand-written comments.
- **Permissions**: the assistant runs shell scripts from the meeting skill, so allow them in that working directory's `.claude/settings.json` — otherwise it stops mid-meeting at a permission prompt.
- **Orphaned process on SIGKILL**: the daemon stops the assistant on normal shutdown, but if the daemon itself is killed with SIGKILL (`kill -9`), the assistant process can be left running (it is detached from any terminal). Find and kill it manually with `pgrep -af claude` (or `codex`).
- **Security note if you expose the dashboard**: the AI Console's terminal content (including whatever the assistant reads or prints from your files) is streamed over the same `/api/events` SSE used by the rest of the dashboard, and that SSE fan-out has no per-client filtering. If you bind the dashboard beyond localhost, anyone who can reach it can watch the assistant's terminal live. Console input (`/api/console/input` etc.) itself stays localhost-only and additionally checks the `Origin` header to reject cross-origin requests from your own browser.

### Browser screenshots

A small Chrome extension in [`extension/`](extension/) captures the visible tab — a shared screen in a browser meeting, say — saves the image in the data directory, and adds a `[画面]` line to the transcript being recorded, so the image sits on the same timeline as the speech. Load it unpacked from `chrome://extensions`; see [extension/README.md](extension/README.md) for installation, settings and what gets written.

## Configuration

### Configuration file

Customize defaults and auto-features in `~/.local/share/shadow-clerk/config.yaml`. The main keys, with their defaults:

```yaml
# --- Meeting automation ---
translate_language: en        # Translation target language (ja/en/etc)
auto_translate: false         # Auto-start translation on start meeting
auto_summary: false           # Auto-generate summary on end meeting
auto_summary_via_console: true  # With auto_summary: let the AI Console write the minutes when it is running
auto_analyze: false           # Launch the AI assistant and run the meeting skill when a meeting starts

# --- AI Console ---
ai_assistant_command: claude  # Command to run in the AI Console (claude, codex, ...)
ai_assistant_args: ''         # Arguments for that command, split with shlex
ai_assistant_init_prompt: /clerk-meeting-helper {transcript} {lang}  # Sent to the PTY once the TUI is ready. {transcript}, {meeting} and {lang} are substituted ({lang} = translate_language)
ai_assistant_workdir: ''      # Default working directory. Per-meeting overrides live in meetings[].workdir of DATA_DIR/meeting.yaml

# --- Transcription ---
default_language: null        # Default language for clerk-daemon (null=auto-detect)
default_model: small          # Default Whisper model for clerk-daemon
output_directory: null        # Transcript output directory (null=data directory)
initial_prompt: null          # Whisper initial_prompt (vocabulary hints for recognition)
whisper_beam_size: 5          # Whisper beam size (1=fast, 5=accurate)
whisper_compute_type: int8    # Compute precision (int8/float16/float32)
whisper_device: cpu           # Device (cpu/cuda)
interim_transcription: false  # Interim transcription (real-time display while speaking)
interim_model: base           # Model for interim transcription
japanese_asr_model: default   # Japanese ASR model (default/kotoba-whisper/reazonspeech-k2)
kotoba_whisper_model: kotoba-tech/kotoba-whisper-v2.0-faster  # Kotoba-Whisper model
interim_japanese_asr_model: default  # Japanese ASR for interim transcription
reazonspeech_precision: fp32  # ReazonSpeech k2: fp32 / int8 / int8-fp32 (fp16 is invalid)

# --- Audio devices ---
mic_device: null              # Microphone device name (null=OS default; not an index — indices shift between runs)
monitor_device: null          # Monitor/speaker device name (null=OS default). Selectable from the dashboard settings panel

# --- LLM, translation and summary ---
llm_provider: claude          # LLM for summary ("claude" or "api")
translation_provider: null    # Translation provider (null=use llm_provider, "claude", "api", "libretranslate")
claude_cli_path: claude       # claude command (full path if not on PATH)
claude_cli_model: haiku       # Model for claude -p (haiku / sonnet / opus / full model id)
api_endpoint: null            # OpenAI Compatible API base URL
api_model: null               # API model name (gpt-4o, etc.)
api_key_env: SHADOW_CLERK_API_KEY  # Environment variable name for API key
api_disable_thinking: false   # Disable reasoning-model thinking for translation/interim (Qwen3 etc.; sends enable_thinking=false). Summary always keeps thinking.
interim_translation: true     # Translate interim transcription to dashboard's interim panel
interim_translation_provider: null  # null=auto, "api", "libretranslate", or "claude"
translation_hiragana_step: true  # Have the LLM reread Japanese as kana before translating, to catch misrecognized homophones
libretranslate_endpoint: null     # LibreTranslate API URL (e.g. http://localhost:5000)
libretranslate_api_key: null      # LibreTranslate API key (null if not required)
libretranslate_spell_check: false # Spell check before LibreTranslate translation
spell_check_model: mbyhphat/t5-japanese-typo-correction  # Spell check model
summary_source: null          # Summary source (null=auto: prefer translation if exists / "transcript" / "translate")
summary_language: null        # Summary output language (null=fallback to ui_language / ja, en, zh, ...)
summary_length: half          # Minimum length of the minutes (half / 1page / 2pages ... 5pages, in A4 pages)
summary_hiragana_step: true   # Same kana rereading step before summarizing

# --- Voice commands ---
voice_command_key: f23        # Push-to-Talk key (null=disabled)
wake_word: シェルク             # Wake word (trigger word for voice commands)
custom_commands: []           # Custom voice commands (list of pattern + action)

# --- Google Calendar ---
gcal_integration: false       # Start/end meetings from calendar events
gcal_credentials_file: null   # OAuth credentials.json
gcal_token_file: null         # Saved token (null=DATA_DIR/gcal_token.json)
gcal_calendar_id: primary     # Calendar to watch
gcal_buffer_minutes: 2        # Send start_meeting this many minutes before an event starts
gcal_end_buffer_minutes: 1    # Send end_meeting this many minutes after it ends

# --- UI ---
ui_language: ja               # UI language (ja/en) — dashboard, terminal output, LLM prompts
```

Talk mode keys (`talk_*`) are listed under [Talk with Claude](#talk-with-claude). The dashboard also keeps a few keys of its own in this file (`welcome_dismissed`, `skill_update_dismissed_version`, `skill_install_targets`); you don't need to edit them.

Manage configuration from the command line (or from ⚙ on the dashboard):

```
clerk-util read-config                                # Show current config
clerk-util write-config-value default_model tiny      # Change a setting
clerk-util write-config-value auto_translate true     # Enable auto-translation
```

With `auto_translate: true`, translation starts automatically when a meeting session begins.
With `auto_summary: true`, meeting minutes are generated automatically when a meeting session ends.
With `auto_analyze: true`, the AI assistant is launched in the AI Console when a meeting session begins.

### Summary source selection

When `summary_source` is unset (null/auto), the summary is generated from the translation file if one exists (falling back to the transcript if not). To pin the behavior explicitly:

```
clerk-util write-config-value summary_source transcript   # always use transcript
clerk-util write-config-value summary_source translate    # always use translation (fallback to transcript if missing)
```

### Summary language

`summary_language` controls the output language of the summary. When unset (null), it falls back to `ui_language`:

```
clerk-util write-config-value summary_language en   # summarize in English
clerk-util write-config-value summary_language ja   # summarize in Japanese
```

## File structure

```
shadow-clerk/                          # Repository
  pyproject.toml                       # Project definition & dependencies
  src/shadow_clerk/                    # Main package
    clerk_daemon.py                    # clerk-daemon entry point (recording, transcription, dashboard: _daemon_*.py)
    clerk_util.py                      # clerk-util: data directory operations & process management
    llm_client.py                      # Translation, summary & LLM queries (_llm_*.py)
    gcal_monitor.py                    # Google Calendar polling
    skill_install.py                   # install-skill
    i18n.py                            # Internationalization (ja/en)
    domain/                            # Domain value objects
    skills/                            # Bundled skills: clerk-meeting-helper, clerk-talk, clerk-practice
    talk_prompts/                      # Talk mode system prompts
  extension/                           # Chrome screenshot extension
  packaging/                           # PyInstaller spec and hooks
  docs/                                # Feature tour, Google Calendar setup
  tests/                               # Tests
  SPEC.md                              # Architecture and module design (Japanese)

~/.local/share/shadow-clerk/           # Runtime data
  transcript-YYYYMMDD.txt              # Transcription output (date-based)
  transcript-YYYYMMDDHHMM.txt          # Meeting session transcript
  transcript-YYYYMMDDHHMM@Title.txt    # Meeting session transcript (with event title)
  transcript-YYYYMMDD-<lang>.txt       # Translation output
  transcript-YYYYMMDDHHMM@Title.attendees.json  # Expected attendees from the calendar event
  summary-YYYYMMDD.md                  # Meeting minutes (corresponds to transcript)
  summary-YYYYMMDDHHMM@Title.md        # Meeting minutes (named session)
  advice-YYYYMMDDHHMM@Title.md         # AI Console: open questions and suggestions
  analysis-YYYYMMDDHHMM@Title.md       # AI Console: confirmed facts
  shot-YYYYMMDDHHMM@Title-HHMMSS.png   # Browser screenshots
  meeting.yaml                         # Per-meeting working directories
  glossary.txt                         # Glossary (TSV: translation terms & reading-based text replacement)
  misheard.tsv                         # Misheard word pairs collected by the skills
  config.yaml                          # Configuration file
  .env                                 # API key (SHADOW_CLERK_API_KEY)
  daemon.log / daemon.pid              # Daemon log and PID
  gcal_token.json                      # Google Calendar OAuth token (created by gcal-auth)
```

## Troubleshooting

### Device not found

```bash
# List available devices
clerk-daemon --list-devices

# PipeWire: check status
wpctl status

# PulseAudio: list sources
pactl list short sources
```

### Monitor source (system audio) not detected

On PipeWire, check sink (output) devices with `wpctl status`.
On PulseAudio, look for sources containing `.monitor` with `pactl list short sources`.

You can also specify the device number manually:

```bash
clerk-daemon --monitor 5
```

### PortAudio error

Make sure `libportaudio2` is installed:

```bash
dpkg -l | grep portaudio
```

If you see `PortAudioError: Error initializing PortAudio: ... PulseAudio_Initialize: Can't connect to server`, the PulseAudio-compatible service may have crashed. On PipeWire systems, restart `pipewire-pulse`:

```bash
systemctl --user restart pipewire-pulse
```

### Slow transcription

Use a lighter model with `--model tiny`:

```bash
clerk-daemon --model tiny
```

### Japanese ASR models

The `japanese_asr_model` setting selects the ASR backend used when `language=ja`. When the language changes to something other than `ja`, it automatically reverts to standard Whisper.

| Value | Model | Requires | Japanese accuracy | CPU speed |
|---|---|---|---|---|
| `default` | Standard Whisper | — | Depends on model size | Depends on model size |
| `kotoba-whisper` | [Kotoba-Whisper](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0) | Auto-downloaded on first use | High (rivals large-v3) | ~medium |
| `reazonspeech-k2` | [ReazonSpeech k2](https://github.com/reazon-research/ReazonSpeech) | `uv sync --extra reazonspeech` | High | Fast |

**Kotoba-Whisper** retains the full large-v3 encoder (32 layers) while distilling the decoder down to just 2 layers. Since it has only 2 decoder layers, **beam=5 has almost no speed penalty**.

**ReazonSpeech k2** uses sherpa-onnx for inference. When selected, Whisper-specific settings (`default_model`, `whisper_beam_size`, `whisper_compute_type`, `initial_prompt`) are not used.

**Selection guide:**

| Use case | Settings |
|---|---|
| Japanese-focused, accuracy priority | `japanese_asr_model: kotoba-whisper`, `whisper_beam_size: 5` |
| Japanese-focused, fast & accurate | `japanese_asr_model: reazonspeech-k2` |
| Japanese-focused, speed priority (CPU) | `japanese_asr_model: default`, `default_model: small`, `whisper_beam_size: 3` |
| Multilingual | `japanese_asr_model: kotoba-whisper`, `default_model: small` (Kotoba for ja, small for others) |

**Interim transcription:**

`interim_japanese_asr_model` controls which Japanese ASR model is used for interim transcription (real-time display while speaking). On CPU, keeping the default (`default` with a lightweight model like tiny/base) is recommended.

```yaml
# Japanese accuracy priority (GPU recommended)
japanese_asr_model: kotoba-whisper
interim_japanese_asr_model: kotoba-whisper
whisper_beam_size: 5

# Japanese accuracy + fast interim (CPU recommended)
japanese_asr_model: kotoba-whisper
interim_japanese_asr_model: default
interim_model: base
whisper_beam_size: 5        # Kotoba has only 2 decoder layers, beam=5 is fine

# ReazonSpeech (fast & accurate, CPU friendly)
japanese_asr_model: reazonspeech-k2
interim_japanese_asr_model: default
interim_model: base

# Maximum speed (CPU)
japanese_asr_model: default
default_model: small
interim_model: base
whisper_beam_size: 1
```

**Interim translation:**

When `interim_transcription` is on, the daemon also emits a translation of each pre-confirmed line to the dashboard's interim panel. Two knobs control this:

- `interim_translation: true` — toggle the translation panel without disabling interim ASR.
- `interim_translation_provider: null | "api" | "libretranslate" | "claude"` — pick the backend explicitly. `null` falls back to `translation_provider`; if that is `claude` it is auto-routed to `api` then `libretranslate` (claude is too slow for interim, ~5-10s per call). Set to `claude` only if you accept the latency.

The interim panel needs sub-second responses to be useful, so `libretranslate` (local) is recommended; `api` is OK with a fast model. Confirmed-transcript translation is unaffected — it always uses `translation_provider`.

## Building standalone binaries

`packaging/shadow-clerk.spec` produces a one-directory PyInstaller bundle containing both `clerk-daemon` and `clerk-util`.

**Without a Windows machine**, `.github/workflows/build-binary.yml` builds the bundle on `windows-latest` and `ubuntu-latest` with ReazonSpeech and Google Calendar included. Push a `v*` tag and both
binaries are attached to the release, or start it by hand from the Actions tab and
download them as artifacts.

**PyInstaller does not cross-compile.** It only builds for the OS it runs on: the bootloader is a native binary, and the analysis step imports every module to trace dependencies. A Windows `.exe` therefore has to be built on Windows — a machine, a VM, or a `windows-latest` GitHub Actions runner. Wine with a Windows Python is the usual workaround, but analysis imports `pywinpty` (ConPTY), `PyAudioWPatch` (WASAPI) and `ctranslate2`, which are exactly the pieces Wine emulates poorly.

To build locally:

```powershell
# Windows (PowerShell)
uv sync
uv run --with pyinstaller pyinstaller packaging/shadow-clerk.spec
dist\shadow-clerk\clerk-daemon.exe --list-devices   # smoke test
```

```bash
# Linux / macOS
uv sync
uv run --with pyinstaller pyinstaller packaging/shadow-clerk.spec
./dist/shadow-clerk/clerk-daemon --list-devices      # smoke test
```

`--list-devices` is a good smoke test: it exercises the bundled PortAudio and the native extensions without recording anything.

To bundle ReazonSpeech and Google Calendar as well, replace the `uv sync` line — in
this order, because `reazonspeech-k2-asr` is not declared anywhere and a later sync
would remove it:

```powershell
uv sync --extra reazonspeech --extra gcal
uv pip install "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"
uv run python -c "import sherpa_onnx, reazonspeech.k2.asr; print('ok')"   # check before building
uv run --with pyinstaller pyinstaller packaging/shadow-clerk.spec
```

The `spell-check` extra is **not** bundled even if you install it: the spec drops
`torch`, `transformers` and `sentencepiece` in `_EXCLUDES`. Remove them from that
list to include it, and expect the bundle to grow by several GB.

**Do not `uv pip install pyinstaller`.** `uv sync` makes the environment match what the project declares and removes everything else, so the next `uv sync --extra ...` would drop it again. `--with` puts PyInstaller in a temporary layer over the project environment instead: it can still see the project's packages, and nothing is left behind to be removed.

Notes:

- **Output**: `dist/shadow-clerk/`, roughly 460 MB with the default dependencies and no extras.
- **Extras are collected only if installed** in the environment you build from, so install them before building — every extra you want named in one `uv sync`, and any `uv pip install` last. See [Setup](#2-install) for why the order matters. The spec collects `sherpa_onnx` (which carries its own `onnxruntime` DLL in `lib/`) and `reazonspeech.k2.asr` when they are there; the ASR weights themselves are fetched on first use, like the Whisper models.
- **Whisper models are not bundled.** `small` is around 500 MB and is fetched from Hugging Face on first run, then cached (`%USERPROFILE%\.cache\huggingface` on Windows, `~/.cache/huggingface` elsewhere). For an offline bundle, add that cache to `datas` in the spec, or ship a converted CT2 model and point `--model` at it.
- **`packaging/hooks/` overrides PyInstaller's bundled hooks.** There is one today: the bundled `hook-webrtcvad.py` calls `copy_metadata('webrtcvad')`, but this project depends on `webrtcvad-wheels`, so without the override the build aborts with `ImportErrorWhenRunningHook`.
- Add a dependency that ships DLLs or data files? Add it to `_PACKAGES` in the spec. PyInstaller only follows `import` statements, so anything else is silently left out and fails at runtime rather than at build time.
