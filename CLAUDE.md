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

### Proper Nouns

**This repository is public on GitHub.** Never write a proper noun in source,
tests, comments, or documentation.

- **Not allowed**: company names, client names, people's names, internal product,
  team or meeting names, internal hostnames, internal repository or file paths
- **Allowed**: this project and its modules, its authors and co-authors, licenses,
  and third-party software it depends on or interoperates with

Fixtures and examples use invented names (`acme`, `alice`, `週次定例`). Real names
met while developing belong in the data directory, not in the repository — the
glossary and `misheard.tsv` exist for exactly that.

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
- **AI Console: don't report VIRTUAL_ROWS as the real PTY height (Windows/ConPTY)**: `_daemon_console.py`'s `pyte.Screen` is `VIRTUAL_ROWS` (10000) tall so a TUI's redraws never scroll content out of the grid — see the comment above `VIRTUAL_ROWS` in `_daemon_constants.py`. It used to also report that same 10000 as the *real* PTY window size (`TIOCSWINSZ` / ConPTY `dimensions`). On Windows only (reproduced with pywinpty; not seen over a POSIX pty on Linux), Claude Code's fullscreen (alt-screen) renderer anchors its status/input bar at a fixed absolute row instead of scaling it to the real window height, so with a 10000-row window the bar landed around row ~2045 while real content stayed near row 0 — a permanent multi-thousand-row gap, not just a startup glitch, and it also appeared to swallow the initial-prompt's Enter keystroke while in that state. Confirmed harmless to shrink the *real* PTY size on its own: pyte's scroll margins are keyed off `screen.lines` (still `VIRTUAL_ROWS`), not the real window size, so a small real PTY (tested with `cmd.exe` printing 80 lines into a 24-row PTY) still accumulates the full growing history with no scrolling/loss. Fixed by decoupling the two on Windows only: there `CONSOLE_PTY_ROWS` (50) is what's told to ConPTY (`open_console_pty`'s `rows` arg, `ConsoleSession.resize()`'s `set_winsize`); `VIRTUAL_ROWS` stays reserved for `pyte.Screen` sizing. On POSIX, `CONSOLE_PTY_ROWS` must stay equal to `VIRTUAL_ROWS`: telling the child it has 50 rows made Claude Code's absolute cursor moves and full redraws land in grid rows 0–49 while the old screen stayed below, so the dashboard (which shows up to `max_row`) kept showing a stale input box and typed text appeared nowhere visible — it looked like input was dead and neither reload nor resize recovered it. `_daemon_dashboard_js_console.py`'s `_consoleFirstRow` (hides any blank rows above the first real content) is kept as a client-side backstop for any other stray cursor jump, but it doesn't cover a gap *between* two blocks of real content the way this row-count fix does.

## Git Workflow

- Never commit on `main`. Every change goes on a branch (`feat/<topic>`,
  `fix/<topic>`, `docs/<topic>`) and reaches `main` through a GitHub PR
- Work in a git worktree next to the main checkout, branched from `origin/main`:
  ```bash
  git fetch origin
  git worktree add -b feat/<topic> ../shadow-clerk-<topic> origin/main
  ```
  Leave the main checkout alone — other sessions and the installed daemon use it.
  Each worktree needs its own `uv sync` (with the extras you need). Remove it with
  `git worktree remove ../shadow-clerk-<topic>` after the PR is merged
- To try a branch in the real daemon, `uv tool install` from the worktree path
  (with the full extras list); the tool then runs that worktree's code until it is
  reinstalled from elsewhere
- Commit messages: English, concise, descriptive
- No CI on push. The only workflow is `.github/workflows/build-binary.yml`,
  which builds the standalone binaries and runs on a `v*` tag or by hand

## Bundled Skills (`src/shadow_clerk/skills/`)

`clerk-meeting-helper`, `clerk-talk`, `clerk-practice` の3スキルを同梱し、
`clerk-util install-skill` またはダッシュボードのモーダルでユーザーの
`~/.claude/skills/` へ配布する（`skill_install.py` が一元管理）。

### バージョン管理と更新通知

- 各スキルの `SKILL.md` frontmatter に `metadata.version` を持つ（`"1.3.1"` など）
- `skill_install.read_skill_version()` でバージョンを読み、`_state()` で
  同梱版 vs インストール済みを比較する
- インストール済みが古ければ `state: "outdated"` となり、ダッシュボードが
  更新モーダルを表示してユーザーに配布を促す
- **スキルを変更したら必ずバージョンをバンプする**。バンプしないとモーダルが
  出ず、既存ユーザーに変更が届かない

## Documentation

- `README.md` (English, primary) / `README.ja.md` (Japanese)
- `SPEC.md` — Detailed Japanese technical spec with Mermaid diagrams

## User Preferences

- Primary communication language: Japanese
- Commit messages / README: English
- Diagrams: Mermaid (not PlantUML)
- Prefers quick iteration: change → syntax check → restart → verify on dashboard
- Prefers toggle buttons over separate start/stop buttons
