# Shadow-clerk

A tool that records web meeting audio in real-time, transcribes it, and generates meeting minutes using a Claude Code Skill.

Runs on Ubuntu + PipeWire / PulseAudio environments.

## Setup

### 1. System packages

```bash
sudo apt install libportaudio2 portaudio19-dev
```

### 2. Install

```bash
uv tool install shadow-clerk
```

For development:

```bash
cd shadow-clerk
uv venv
uv pip install -e .
```

### 3. Register as Claude Code Skill

```bash
clerk-util claude-setup
```

This generates `~/.claude/skills/shadow-clerk/SKILL.md` and adds permissions to `~/.claude/settings.local.json`.

## Usage

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

Hold down the Menu key (next to Right Alt) while speaking a command — no prefix ("clerk") needed. This avoids Whisper's unreliable recognition of the "clerk" keyword:

```
[Hold Menu key] "start translation" → Translation starts
[Hold Menu key] "start meeting"     → Meeting session starts
```

The trigger key can be changed via `voice_command_key` in `config.yaml` (`ctrl_r`, `ctrl_l`, `alt_r`, `alt_l`, `shift_r`, `shift_l`). Set to `null` to disable.

#### Prefix mode (fallback)

During recording, say "clerk" followed by a command for hands-free control:

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

### Meeting minutes (Claude Code Skill)

You can start/stop clerk-daemon and generate meeting minutes from Claude Code:

```
/shadow-clerk start                    # Start clerk-daemon in the background
/shadow-clerk start --language ja      # Start with options
/shadow-clerk stop                     # Stop clerk-daemon
/shadow-clerk          # Update minutes from transcript diff
/shadow-clerk full     # Regenerate minutes from full transcript
/shadow-clerk status   # Check current status
```

Generated meeting minutes are saved to `~/.local/share/shadow-clerk/summary-YYYYMMDD.md`.

### Configuration file

Customize defaults and auto-features in `~/.local/share/shadow-clerk/config.yaml`:

```yaml
# shadow-clerk config
translate_language: ja        # Translation target language (ja/en/etc)
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
summary_source: transcript    # Summary source ("transcript" or "translate")
libretranslate_endpoint: null     # LibreTranslate API URL (e.g. http://localhost:5000)
libretranslate_api_key: null      # LibreTranslate API key (null if not required)
libretranslate_spell_check: false # Spell check before LibreTranslate translation
spell_check_model: mbyhphat/t5-japanese-typo-correction  # Spell check model
custom_commands: []               # Custom voice commands (list of pattern + action)
initial_prompt: null              # Whisper initial_prompt (vocabulary hints for recognition)
voice_command_key: menu        # Push-to-Talk key (null=disabled)
whisper_beam_size: 5           # Whisper beam size (1=fast, 5=accurate)
whisper_compute_type: int8     # Compute precision (int8/float16/float32)
whisper_device: cpu            # Device (cpu/cuda)
interim_transcription: false   # Interim transcription (real-time display while speaking)
interim_model: tiny            # Model for interim transcription
use_kotoba_whisper: true       # Use Kotoba-Whisper when language=ja
kotoba_whisper_model: kotoba-tech/kotoba-whisper-v2.0-faster  # Kotoba-Whisper model
interim_use_kotoba_whisper: false  # Use Kotoba-Whisper for interim transcription too
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

Set `llm_provider: api` to run summary generation via an OpenAI Compatible API. Use this when you want to process with LLMs other than Claude Code (OpenAI, Ollama, etc.).

```
# OpenAI
/shadow-clerk config set llm_provider api
/shadow-clerk config set api_endpoint https://api.openai.com/v1
/shadow-clerk config set api_model gpt-4o
# Put API key in ~/.local/share/shadow-clerk/.env:
#   SHADOW_CLERK_API_KEY=sk-...

# Ollama (local)
/shadow-clerk config set llm_provider api
/shadow-clerk config set api_endpoint http://localhost:11434/v1
/shadow-clerk config set api_model llama3
/shadow-clerk config set api_key_env null
```

### LibreTranslate mode

Set `translation_provider: libretranslate` to use a self-hosted [LibreTranslate](https://libretranslate.com/) instance for translation instead of an LLM.

```
/shadow-clerk config set translation_provider libretranslate
/shadow-clerk config set libretranslate_endpoint http://localhost:5000
# Optional: enable spell check before translation (useful for speech recognition errors)
/shadow-clerk config set libretranslate_spell_check true
```

### Summary from translation

By default, summaries are generated from the transcript. Set `summary_source: translate` to generate summaries from the translation file instead:

```
/shadow-clerk config set summary_source translate
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
    data/
      SKILL.md.template                # Claude Code Skill template
  skills/
    SKILL.md                           # Claude Code Skill definition (development)

~/.local/share/shadow-clerk/           # Runtime data
  transcript-YYYYMMDD.txt              # Transcription output (date-based)
  transcript-YYYYMMDDHHMM.txt          # Meeting session transcript
  transcript-YYYYMMDD-<lang>.txt       # Translation output
  summary-YYYYMMDD.md                  # Meeting minutes (corresponds to transcript)
  words.txt                            # Word replacement list (TSV)
  glossary.txt                         # Translation glossary (TSV)
  config.yaml                          # Configuration file
```

## Troubleshooting

### Device not found

```bash
# List available devices
clerk-daemon --list-devices

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
clerk-daemon --monitor 5
```

### PortAudio error

Make sure `libportaudio2` is installed:

```bash
dpkg -l | grep portaudio
```

### Slow transcription

Use a lighter model with `--model tiny`:

```bash
clerk-daemon --model tiny
```

### Kotoba-Whisper (Japanese-specialized model)

When `use_kotoba_whisper: true` (default), [Kotoba-Whisper](https://huggingface.co/kotoba-tech/kotoba-whisper-v2.0) is automatically used when `language=ja`. When the language is changed to something other than `ja`, it reverts to the standard Whisper model.

**Model comparison:**

| Model | Parameters | Encoder | Decoder | Japanese accuracy | CPU speed |
|---|---|---|---|---|---|
| Whisper tiny | 39M | 4 layers | 4 layers | Low | Fastest |
| Whisper base | 74M | 6 layers | 6 layers | Low | Fast |
| Whisper small | 244M | 12 layers | 12 layers | Medium | Medium |
| Whisper medium | 769M | 24 layers | 24 layers | Medium-High | Slow |
| Whisper large-v3 | 1550M | 32 layers | 32 layers | High | Very slow |
| **Kotoba-Whisper** | **756M** | **32 layers** | **2 layers** | **High** | **~medium** |

Kotoba-Whisper retains the full large-v3 encoder (32 layers) while distilling the decoder down to just 2 layers. Japanese accuracy rivals large-v3 at roughly medium speed.

**beam_size interaction:**

`beam_size` controls the decoder search width. Models with more decoder layers are affected more:

| Model | Decoder layers | beam=1 vs beam=5 speed difference |
|---|---|---|
| Whisper tiny | 4 layers | Small |
| Whisper small | 12 layers | Medium |
| Whisper medium | 24 layers | **Large** |
| Whisper large-v3 | 32 layers | **Very large** |
| **Kotoba-Whisper** | **2 layers** | **Negligible** |

Since Kotoba-Whisper has only 2 decoder layers, **beam=5 has almost no speed penalty**. For standard Whisper (especially medium and above), setting `beam_size: 1` can noticeably improve speed.

**Selection guide:**

| Use case | Settings |
|---|---|
| Japanese-focused, accuracy priority | `use_kotoba_whisper: true`, `whisper_beam_size: 5` |
| Japanese-focused, speed priority (CPU) | `use_kotoba_whisper: false`, `default_model: small`, `whisper_beam_size: 1` |
| Multilingual | `use_kotoba_whisper: true`, `default_model: small` (Kotoba for ja, small for others) |
| GPU (CUDA) environment | `use_kotoba_whisper: true`, `whisper_beam_size: 5` (best accuracy & speed) |

**Interim transcription:**

`interim_use_kotoba_whisper` controls whether Kotoba-Whisper is used for interim transcription (real-time display while speaking). Since Kotoba-Whisper has 756M parameters, it may not meet the speed requirements for interim transcription. On CPU, the default `false` (using lightweight models like tiny/base) is recommended.

```yaml
# Japanese accuracy priority (GPU recommended)
use_kotoba_whisper: true
interim_use_kotoba_whisper: true
whisper_beam_size: 5

# Japanese accuracy + fast interim (CPU recommended)
use_kotoba_whisper: true
interim_use_kotoba_whisper: false
interim_model: tiny
whisper_beam_size: 5        # Kotoba has only 2 decoder layers, beam=5 is fine

# Maximum speed (CPU)
use_kotoba_whisper: false
default_model: small
interim_model: tiny
whisper_beam_size: 1
```
