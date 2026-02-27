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
uv run python recorder.py

# List available devices
uv run python recorder.py --list-devices

# With options
uv run python recorder.py \
  --language ja \
  --model small \
  --output ~/my-transcript.txt \
  --verbose
```

Press `Ctrl+C` to stop recording.

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

### Meeting minutes (Claude Code Skill)

You can start/stop recorder.py and generate meeting minutes from Claude Code:

```
/shadow-clerk start                    # Start recorder.py in the background
/shadow-clerk start --language ja      # Start with options
/shadow-clerk stop                     # Stop recorder.py
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
default_language: null        # Default language for recorder.py (null=auto-detect)
default_model: small          # Default Whisper model for recorder.py
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

## File structure

```
shadow-clerk/                          # Repository
  pyproject.toml                       # Project definition & dependencies
  recorder.py                          # Recording, VAD & transcription
  skills/
    SKILL.md                           # Claude Code Skill definition
    clerk-data                         # Data directory wrapper script
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
    config.yaml                        # Configuration file
    .clerk_session                     # Active session info
    .transcript_offset                 # Minutes generation offset
    .translate_offset                  # Translation offset
```

## Troubleshooting

### Device not found

```bash
# List available devices
uv run python recorder.py --list-devices

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
uv run python recorder.py --monitor 5
```

### PortAudio error

Make sure `libportaudio2` is installed:

```bash
dpkg -l | grep portaudio
```

### Slow transcription

Use a lighter model with `--model tiny`:

```bash
uv run python recorder.py --model tiny
```
