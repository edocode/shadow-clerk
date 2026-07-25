# Shadow-clerk

[![PyPI version](https://img.shields.io/pypi/v/shadow-clerk.svg)](https://pypi.org/project/shadow-clerk/)
[![Python versions](https://img.shields.io/pypi/pyversions/shadow-clerk.svg)](https://pypi.org/project/shadow-clerk/)

A tool that records web meeting audio in real-time and transcribes it. Also supports translation and meeting minutes generation.

Available on PyPI: <https://pypi.org/project/shadow-clerk/>

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
- **Stopping the daemon**: `clerk-util stop` works (Windows path uses `taskkill`). `clerk-util start` runs the daemon in the foreground with Ctrl+C handling, mirroring Linux.

## Features and requirements

| Feature | Requires | Quality | Speed | Related settings |
|---|---|:---:|:---:|---|
| Transcription (default) | faster-whisper (included) | 3 | 4 | `default_model`, `default_language` |
| Transcription (Kotoba-Whisper) | Same (auto-downloaded on first use) | 5 | 3 | `japanese_asr_model: kotoba-whisper` |
| Transcription (ReazonSpeech) | `uv sync --extra reazonspeech` | 5 | 4 | `japanese_asr_model: reazonspeech-k2` |
| Interim transcription | Same | 2 | 5 | `interim_transcription: true`, `interim_model` |
| Translation (LibreTranslate) | LibreTranslate server | 2 | 4 | `translation_provider: libretranslate` |
| Translation (OpenAI compatible API) | OpenAI compatible API | 3-5 | 2-5 | `translation_provider: api`, `api_endpoint`, `api_model` |
| Translation (Claude) | Claude Code | 5 | 2 | `translation_provider: claude` |
| Language detection (pre-translation) | langdetect (included) | — | — | Automatically detects source language to select correct prompt |
| Summary (Claude) | Claude Code | 5 | 3 | `llm_provider: claude` |
| Summary (OpenAI compatible API) | OpenAI compatible API | 3-5 | 2-5 | `llm_provider: api`, `api_endpoint`, `api_model` |
| Voice commands (PTT) | None (built-in) | — | — | `voice_command_key` |
| Voice commands (LLM matching) | OpenAI compatible API | — | — | `api_endpoint`, `api_model` |
| Spell check (pre-translation) | transformers (auto-downloaded on first use) | — | — | `libretranslate_spell_check: true` |

**Minimal setup without LLM:** Transcription + LibreTranslate translation requires no external API or Claude Code. Everything runs locally.

See the [Feature Tour](docs/feature-tour.en.md) for a visual walkthrough with screenshots.

## Setup

### 1. System packages

```bash
sudo apt install libportaudio2 portaudio19-dev
```

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
# or for development:
uv sync --extra reazonspeech
uv pip install "reazonspeech-k2-asr @ git+https://github.com/reazon-research/ReazonSpeech.git#subdirectory=pkg/k2-asr"
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

# Enable in config
clerk-util write-config-value gcal_integration true
clerk-util write-config-value gcal_credentials_file ~/credentials.json
```

When enabled, clerk-daemon polls Google Calendar every 60 seconds. Events automatically trigger `start_meeting` / `end_meeting`, creating transcript files named `transcript-YYYYMMDDHHMM@EventTitle.txt`.

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
```

Press `Ctrl+C` to stop recording.

### Voice commands

#### Push-to-Talk (recommended)

Hold down the Menu key (next to Right Alt) while speaking a command — no wake word needed:

```
[Hold Menu key] "start translation" → Translation starts
[Hold Menu key] "start meeting"     → Meeting session starts
```

The trigger key can be changed via `voice_command_key` in `config.yaml` (`ctrl_r`, `ctrl_l`, `alt_r`, `alt_l`, `shift_r`, `shift_l`). Set to `null` to disable.

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

You can register custom voice commands in `config.yaml` under `custom_commands`. They are evaluated after built-in commands:

```yaml
custom_commands:
  - pattern: "youtube"
    action: "xdg-open https://www.youtube.com"
  - pattern: "gmail|mail"
    action: "xdg-open https://mail.google.com"
```

- `pattern`: Regular expression (case-insensitive)
- `action`: Shell command to execute

#### LLM fallback

If a voice command doesn't match any built-in or custom command and `api_endpoint` is configured, the utterance is sent to the LLM as a query. The response is printed to stdout and saved to `.clerk_response`.

```
"sheruku, what is 1+1?" → LLM returns the answer
```

### CLI options

| Option | Description | Default |
|---|---|---|
| `--output`, `-o` | Output file path | `~/.local/share/shadow-clerk/transcript-YYYYMMDD.txt` |
| `--model`, `-m` | Whisper model size (`tiny`, `base`, `small`, `medium`, `large-v3`) | `small` |
| `--language`, `-l` | Language code (`ja`, `en`, etc.). Auto-detect if omitted | Auto |
| `--mic` | Microphone device number | Auto-detect |
| `--monitor` | Monitor device number (sounddevice) | Auto-detect |
| `--backend` | Audio backend (`auto`, `pipewire`, `pulseaudio`, `sounddevice`) | `auto` |
| `--list-devices` | List devices and exit | - |
| `--verbose`, `-v` | Verbose logging | - |
| `--dashboard` / `--no-dashboard` | Enable/disable dashboard | Enabled |
| `--dashboard-port` | Dashboard port number | `8765` |
| `--beam-size` | Whisper beam size (`1`=fast, `5`=accurate) | `5` |
| `--compute-type` | Whisper compute precision (`int8`, `float16`, `float32`) | `int8` |
| `--device` | Whisper device (`cpu`, `cuda`) | `cpu` |

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

### Meeting minutes

Three ways to generate minutes: automatically at meeting end, on demand from the dashboard, or via `clerk-util` from the command line:

```
clerk-util start                                   # Start daemon (background)
clerk-util stop                                    # Stop daemon
clerk-util recorder-status                         # Show running state
clerk-util summarize                               # Update minutes from transcript diff
clerk-util summarize --mode full                   # Regenerate from full transcript
clerk-util summarize 20260425 --mode full          # Specify date
clerk-util command start_meeting                   # Start meeting session
clerk-util command end_meeting                     # End meeting session (auto_summary linked)
clerk-util command translate_start                 # Start translation loop
clerk-util command translate_stop                  # Stop translation loop
```

Meeting start/end is also available via **voice commands** ("clerk, start meeting" / "clerk, end meeting") or **dashboard buttons**. The dashboard's "Generate Summary" button can trigger minutes generation at any time.

Generated meeting minutes are saved to `~/.local/share/shadow-clerk/summary-YYYYMMDD.md`.

### Configuration file

Customize defaults and auto-features in `~/.local/share/shadow-clerk/config.yaml`:

```yaml
# shadow-clerk config
translate_language: en        # Translation target language (ja/en/etc)
auto_translate: false         # Auto-start translation on start meeting
auto_summary: false           # Auto-generate summary on end meeting
default_language: null        # Default language for clerk-daemon (null=auto-detect)
default_model: small          # Default Whisper model for clerk-daemon
output_directory: null        # Transcript output directory (null=data directory)
llm_provider: claude          # LLM for summary ("claude" or "api")
translation_provider: null    # Translation provider (null=use llm_provider, "claude", "api", "libretranslate")
api_endpoint: null            # OpenAI Compatible API base URL
api_model: null               # API model name (gpt-4o, etc.)
api_key_env: SHADOW_CLERK_API_KEY  # Environment variable name for API key
api_disable_thinking: false   # Disable reasoning-model thinking for translation/interim (Qwen3 etc.; sends enable_thinking=false). Summary always keeps thinking.
summary_source: null          # Summary source (null=auto: prefer translation if exists / "transcript" / "translate")
summary_language: null        # Summary output language (null=fallback to ui_language / ja, en, zh, ...)
libretranslate_endpoint: null     # LibreTranslate API URL (e.g. http://localhost:5000)
libretranslate_api_key: null      # LibreTranslate API key (null if not required)
libretranslate_spell_check: false # Spell check before LibreTranslate translation
spell_check_model: mbyhphat/t5-japanese-typo-correction  # Spell check model
custom_commands: []               # Custom voice commands (list of pattern + action)
initial_prompt: null              # Whisper initial_prompt (vocabulary hints for recognition)
voice_command_key: f23         # Push-to-Talk key (null=disabled)
wake_word: シェルク              # Wake word (trigger word for voice commands)
whisper_beam_size: 5           # Whisper beam size (1=fast, 5=accurate)
whisper_compute_type: int8     # Compute precision (int8/float16/float32)
whisper_device: cpu            # Device (cpu/cuda)
interim_transcription: false   # Interim transcription (real-time display while speaking)
interim_model: base            # Model for interim transcription
interim_translation: true      # Translate interim transcription to dashboard's interim panel
interim_translation_provider: null  # null=auto, "api", "libretranslate", or "claude"
japanese_asr_model: default    # Japanese ASR model (default/kotoba-whisper/reazonspeech-k2)
kotoba_whisper_model: kotoba-tech/kotoba-whisper-v2.0-faster  # Kotoba-Whisper model
interim_japanese_asr_model: default  # Japanese ASR for interim transcription
reazonspeech_precision: fp32   # ReazonSpeech k2: fp32 / int8 / int8-fp32 (fp16 is invalid)
ui_language: ja                # UI language (ja/en) — dashboard, terminal output, LLM prompts
```

Manage configuration from Claude Code:

```
clerk-util read-config                                # Show current config
clerk-util write-config-value default_model tiny      # Change a setting
clerk-util write-config-value auto_translate true     # Enable auto-translation
```

With `auto_translate: true`, translation starts automatically when a meeting session begins.
With `auto_summary: true`, meeting minutes are generated automatically when a meeting session ends.

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
    __init__.py                        # Data directory configuration
    clerk_daemon.py                    # Recording, VAD, transcription & dashboard
    llm_client.py                      # External API translation & summary
    i18n.py                            # Internationalization (ja/en)
    clerk_util.py                      # Data directory operations & process management

~/.local/share/shadow-clerk/           # Runtime data
  transcript-YYYYMMDD.txt              # Transcription output (date-based)
  transcript-YYYYMMDDHHMM.txt          # Meeting session transcript
  transcript-YYYYMMDDHHMM@Title.txt    # Meeting session transcript (with event title)
  transcript-YYYYMMDD-<lang>.txt       # Translation output
  summary-YYYYMMDD.md                  # Meeting minutes (corresponds to transcript)
  summary-YYYYMMDDHHMM@Title.md        # Meeting minutes (named session)
  glossary.txt                         # Glossary (TSV: translation terms & reading-based text replacement)
  config.yaml                          # Configuration file
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
