# CLAUDE.md - Shadow-Clerk

## Project Overview & Architecture

See `README.md` for project overview, setup, usage, CLI options, and configuration.
See `SPEC.md` for detailed architecture, module design, thread model, data flow diagrams, and data directory layout.

## Commands

```bash
# Development setup
uv sync                          # Install dependencies
uv sync --extra reazonspeech     # With ReazonSpeech support

# Run
uv run clerk-daemon              # Start daemon (dev)
uv run clerk-util                # Utility commands (dev)

# Syntax check (no test framework)
uv run python -m py_compile src/shadow_clerk/<file>.py

# Audio capture regression test (~90s, opens real PortAudio streams)
# Run after touching _daemon_recorder_capture.py / _daemon_audio*.py
uv run python tests/test_audio_capture_watchdog.py

# Post-implementation checks (run after any non-trivial change)
make dupcheck                    # Duplicate code detection (pylint R0801)
```

## Coding Conventions

### File Size
- **Max 700 lines per file**. Split into modules if exceeded.

### Code Quality
- **DRY Principle**: Extract and reuse common logic, but avoid over-abstraction
- **Check existing utilities**: Before creating new helpers, verify no equivalent exists in existing modules
- **Post-implementation verification**: Cross-check with original requirements after implementation
- **Duplicate check**: Run `make dupcheck` after implementation to detect copy-paste duplication
- **Dead code removal**: After implementation, scan for unused imports, unreachable branches, and dead variables — delete them
- **Keep code compact**: Avoid redundant comments, unnecessary intermediate variables, and speculative abstractions. If it fits in one expression, don't split it. Prefer removing code over leaving it disabled or commented out
- Do what was asked; nothing more, nothing less
- Minimize new file creation; prefer editing existing files

### Python Style
- Modern Python 3.11+ (type hints, match/case, walrus operators)
- **Type hints are mandatory**: All function signatures (arguments and return types) must have type annotations. Use `from __future__ import annotations` at the top of each file.
- snake_case for functions/variables, PascalCase for classes, UPPER_SNAKE_CASE for constants
- Logger-based logging (no print)
- Japanese comments in source code are acceptable
- Module files: underscore (`clerk_daemon.py`), CLI commands: hyphen (`clerk-daemon`)
- Module split pattern: public entry `clerk_daemon.py` / `llm_client.py` delegate to private `_daemon_*.py` / `_llm_*.py` submodules
- Entry points: `clerk-daemon` (recording/transcription daemon), `clerk-util` (data directory operations & process management)

### Domain Model (DDD)
- Design and implement domain concepts following DDD principles
- Value objects go in `domain/` subpackage (`src/shadow_clerk/domain/`)
- Use `@dataclass(frozen=True)` for value objects; `Enum` for constrained string types (Speaker, Language, etc.)
- Prefer value objects over raw strings/dicts for domain concepts: `TranscriptLine`, `MeetingSession`, `Summary`, `Translation`
- Do not pass raw `dict` or `str` across layer boundaries when a value object exists for that concept
- When casting (e.g. `int(x)`, `str(x)`) or regex extraction appears in business logic, treat it as a signal to introduce a value object or entity that encapsulates the parsing/validation

### i18n
- All user-facing strings go through `i18n.py` with `t()` function
- Dashboard uses `{{i18n:key}}` template placeholders replaced at serve time
- i18n JSON injected via `/*I18N_JSON*/` placeholder
- **Caution**: `t(key, **kwargs)` — avoid naming kwargs the same as Python builtins or the `key` parameter itself

## Environment

- **Python command**: Always use `uv run python` (not `python3` or `python` directly). This avoids environment differences.
- **Data directory**: `~/.local/share/shadow-clerk/` — config, transcripts, translations, summaries

## Known Pitfalls

- **Multibyte file offsets**: Use binary mode (`open("rb")`) with `decode("utf-8")` for `_read_diff()`. `os.path.getsize()` returns bytes, `f.seek()` in text mode uses character positions — these differ for Japanese text.
- **Translate offset exceeding file size**: Reset offset to 0 when it exceeds file size (happens on day rollover).
- **Import paths**: Always use `from shadow_clerk.X import ...` (not bare `import X`). Python cannot import modules with hyphens in filenames.
- **`_api_configured` caching**: Don't cache config-derived flags in `__init__` — read from `load_config()` each time (it has mtime caching).
- **PTT key stuck**: evdev may report keys as pressed at startup. Check `active_keys()` and set `initially_held` flag.
- **poll-command blocking**: Use `--timeout <sec>` option to avoid indefinite blocking.
- **PortAudio device list is cached**: `sd.query_devices()` returns the list enumerated at `Pa_Initialize` time. Nodes added/removed afterwards (suspend/resume, USB unplug) are invisible until `refresh_device_list()` (`sd._terminate()` + `sd._initialize()`). `Pa_Terminate` destroys every open stream, so all capture streams must be closed first — this is why mic and monitor are managed by a single `_audio_capture_thread`.
- **Audio device indices are unstable**: The same monitor device gets a different index on each daemon start (19/21/22/26…) and can move while running. Compare devices by `AudioDevice.name`, never by index.
- **Capture streams die silently**: A dead PortAudio stream raises no `PortAudioError` and reports no `status` — the callback just stops firing. A healthy stream fires ~33 callbacks/sec even when the sink is silent, so frame starvation is the only reliable liveness signal (`STREAM_STALL_SEC`).

## Git Workflow

- All development on `main` branch, direct push
- Commit messages: English, concise, descriptive
- No CI/CD pipeline

## Documentation

- `README.md` (English, primary) / `README.ja.md` (Japanese)
- `SPEC.md` — Detailed Japanese technical spec with Mermaid diagrams

## User Preferences

- Primary communication language: Japanese
- Commit messages / README: English
- Diagrams: Mermaid (not PlantUML)
- Prefers quick iteration: change → syntax check → restart → verify on dashboard
- Prefers toggle buttons over separate start/stop buttons
