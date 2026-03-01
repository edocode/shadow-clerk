# Shadow-clerk

A tool that records web meeting audio in real-time, transcribes it, and generates meeting minutes using a Claude Code Skill.

Runs on Ubuntu + PipeWire / PulseAudio environments.

## Setup

### 1. System packages

```bash
sudo apt install libportaudio2 portaudio19-dev
```

### 2. Python environment

```bash
cd shadow-clerk
uv venv
uv pip install -e .
```

### 3. Skill symlink (first time only)

```bash
ln -s "$(pwd)/skills" ~/.claude/skills/shadow-clerk
```

## Usage

### Recording & transcription

```bash
# Basic (record mic + system audio, auto-transcribe)
uv run python clerk_daemon.py

# List available devices
uv run python clerk_daemon.py --list-devices

# With options
uv run python clerk_daemon.py \
  --language ja \
  --model small \
  --output ~/my-transcript.txt \
  --verbose
```

Press `Ctrl+C` to stop recording.

### Voice commands

#### Push-to-Talk (recommended)

Hold down the Menu key (next to Right Alt) while speaking a command — no prefix ("clerk") needed. This avoids Whisper's unreliable recognition of the "clerk" keyword:

```
[Hold Menu key] "start translation" → Translation starts
[Hold Menu key] "start meeting"     → Meeting session starts
```

The trigger key can be changed via `voice_command_key` in `config.yaml` (`ctrl_r`, `ctrl_l`, `alt_r`, `alt_l`, `shift_r`, `shift_l`). Set to `null` to disable.

#### Prefix mode (fallback)

During recording, say "clerk" (or "クラーク") followed by a command for hands-free control:

| Voice command | Action |
|---|---|
| "clerk, start meeting" | Start a new meeting session |
| "clerk, end meeting" | End the meeting session |
| "clerk, language ja" | Switch transcription language to Japanese |
| "clerk, language en" | Switch transcription language to English |
| "clerk, unset language" | Reset to auto-detect |
| "clerk, start translation" | Start the translation loop |
| "clerk, stop translation" | Stop the translation loop |

The separator (comma, space) between the prefix and command is optional.

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
"clerk, what is 1+1?" → LLM returns the answer
```

### CLI options

| Option | Description | Default |
|---|---|---|
| `--output`, `-o` | Output file path | `~/.claude/skills/shadow-clerk/data/transcript-YYYYMMDD.txt` |
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

### Meeting minutes (Claude Code Skill)

You can start/stop clerk_daemon.py and generate meeting minutes from Claude Code:

```
/shadow-clerk start                    # Start clerk_daemon.py in the background
/shadow-clerk start --language ja      # Start with options
/shadow-clerk stop                     # Stop clerk_daemon.py
/shadow-clerk          # Update minutes from transcript diff
/shadow-clerk full     # Regenerate minutes from full transcript
/shadow-clerk status   # Check current status
```

Generated meeting minutes are saved to `~/.claude/skills/shadow-clerk/data/summary-YYYYMMDD.md`.

### Configuration file

Customize defaults and auto-features in `~/.claude/skills/shadow-clerk/data/config.yaml`:

```yaml
# shadow-clerk config
translate_language: ja        # Translation target language (ja/en/etc)
auto_translate: false         # Auto-start translation on start meeting
auto_summary: false           # Auto-generate summary on end meeting
default_language: null        # Default language for clerk_daemon.py (null=auto-detect)
default_model: small          # Default Whisper model for clerk_daemon.py
output_directory: null        # Transcript output directory (null=data directory)
llm_provider: claude          # LLM for translation & summary ("claude" or "api")
api_endpoint: null            # OpenAI Compatible API base URL
api_model: null               # API model name (gpt-4o, etc.)
api_key_env: SHADOW_CLERK_API_KEY  # Environment variable name for API key
custom_commands: []               # Custom voice commands (list of pattern + action)
initial_prompt: null              # Whisper initial_prompt (vocabulary hints for recognition)
voice_command_key: menu        # Push-to-Talk key (null=disabled)
whisper_beam_size: 5           # Whisper beam size (1=fast, 5=accurate)
whisper_compute_type: int8     # Compute precision (int8/float16/float32)
whisper_device: cpu            # Device (cpu/cuda)
interim_transcription: false   # Interim transcription (real-time display while speaking)
interim_model: tiny            # Model for interim transcription
ui_language: ja                # UI language (ja/en) — dashboard, terminal output, LLM prompts
```

Manage configuration from Claude Code:

```
/shadow-clerk config show                     # Show current config
/shadow-clerk config set default_model tiny   # Change a setting
/shadow-clerk config set auto_translate true  # Enable auto-translation
/shadow-clerk config init                     # Generate default config file
```

With `auto_translate: true`, translation starts automatically on `/shadow-clerk start meeting`.
With `auto_summary: true`, meeting minutes are generated automatically on `/shadow-clerk end meeting`.

### External API mode

Set `llm_provider: api` to run translation and summary generation via an OpenAI Compatible API. Use this when you want to process with LLMs other than Claude Code (OpenAI, Ollama, etc.).

```
# OpenAI
/shadow-clerk config set llm_provider api
/shadow-clerk config set api_endpoint https://api.openai.com/v1
/shadow-clerk config set api_model gpt-4o
# Put API key in ~/.claude/skills/shadow-clerk/data/.env:
#   SHADOW_CLERK_API_KEY=sk-...

# Ollama (local)
/shadow-clerk config set llm_provider api
/shadow-clerk config set api_endpoint http://localhost:11434/v1
/shadow-clerk config set api_model llama3
/shadow-clerk config set api_key_env null
```

## File structure

```
shadow-clerk/                          # Repository
  pyproject.toml                       # Project definition & dependencies
  clerk_daemon.py                      # Recording, VAD, transcription & dashboard
  llm_client.py                        # External API translation & summary
  i18n.py                              # Internationalization (ja/en)
  skills/
    SKILL.md                           # Claude Code Skill definition
    clerk-util                         # Data directory wrapper script
  SPEC.md                              # Design specification
  README.md                            # Japanese README
  README.en.md                         # This file

~/.claude/skills/shadow-clerk/         # Symlink target
  data/                                # Runtime data (created at runtime)
    transcript-YYYYMMDD.txt            # Transcription output (date-based)
    transcript-YYYYMMDDHHMM.txt        # Meeting session transcript
    transcript-YYYYMMDD-<lang>.txt     # Translation output
    summary-YYYYMMDD.md                # Meeting minutes (corresponds to transcript)
    words.txt                          # Word replacement list (TSV)
    glossary.txt                       # Translation glossary (TSV)
    config.yaml                        # Configuration file
    .clerk_session                     # Active session info
    .transcript_offset                 # Minutes generation offset
    .translate_offset                  # Translation offset
```

## Troubleshooting

### Device not found

```bash
# List available devices
uv run python clerk_daemon.py --list-devices

# Check if PipeWire is running
pw-cli info

# List PulseAudio sources
pactl list short sources
```

### Monitor source (system audio) not detected

On PipeWire, check monitor devices with `pw-record --list-targets`.
On PulseAudio, look for sources containing `.monitor` with `pactl list short sources`.

You can also specify the device number manually:

```bash
uv run python clerk_daemon.py --monitor 5
```

### PortAudio error

Make sure `libportaudio2` is installed:

```bash
dpkg -l | grep portaudio
```

### Slow transcription

Use a lighter model with `--model tiny`:

```bash
uv run python clerk_daemon.py --model tiny
```
