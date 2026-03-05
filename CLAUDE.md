# CLAUDE.md - Shadow-Clerk

## Project Overview & Architecture

See `README.md` for project overview, setup, usage, CLI options, and configuration.
See `SPEC.md` for detailed architecture, module design, thread model, data flow diagrams, and data directory layout.

## Coding Conventions

### File Size
- **Max 700 lines per file**. Split into modules if exceeded.

### Code Quality
- **DRY Principle**: Extract and reuse common logic, but avoid over-abstraction
- **Check existing utilities**: Before creating new helpers, verify no equivalent exists in existing modules
- **Post-implementation verification**: Cross-check with original requirements after implementation
- Do what was asked; nothing more, nothing less
- Minimize new file creation; prefer editing existing files

### Python Style
- Modern Python 3.11+ (type hints, match/case, walrus operators)
- snake_case for functions/variables, PascalCase for classes, UPPER_SNAKE_CASE for constants
- Logger-based logging (no print)
- Japanese comments in source code are acceptable
- Module files: underscore (`clerk_daemon.py`), CLI commands: hyphen (`clerk-daemon`)

### i18n
- All user-facing strings go through `i18n.py` with `t()` function
- Dashboard uses `{{i18n:key}}` template placeholders replaced at serve time
- i18n JSON injected via `/*I18N_JSON*/` placeholder
- **Caution**: `t(key, **kwargs)` — avoid naming kwargs the same as Python builtins or the `key` parameter itself

## Known Pitfalls

- **Multibyte file offsets**: Use binary mode (`open("rb")`) with `decode("utf-8")` for `_read_diff()`. `os.path.getsize()` returns bytes, `f.seek()` in text mode uses character positions — these differ for Japanese text.
- **Translate offset exceeding file size**: Reset offset to 0 when it exceeds file size (happens on day rollover).
- **Import paths**: Always use `from shadow_clerk.X import ...` (not bare `import X`). Python cannot import modules with hyphens in filenames.
- **`_api_configured` caching**: Don't cache config-derived flags in `__init__` — read from `load_config()` each time (it has mtime caching).
- **PTT key stuck**: evdev may report keys as pressed at startup. Check `active_keys()` and set `initially_held` flag.
- **poll-command blocking**: Use `--timeout <sec>` option to avoid indefinite blocking.

## Git Workflow

- All development on `main` branch, direct push
- Commit messages: English, concise, descriptive
- No CI/CD pipeline

## Documentation

- `README.md` (English, primary) / `README.ja.md` (Japanese)
- `SPEC.md` — Detailed Japanese technical spec with Mermaid diagrams
- `SKILL.md` / `SKILL.ja.md` — Claude Code Skill API documentation
- `skills/data/SKILL.md.template` / `SKILL.ja.md.template` — Skill templates with `{clerk_util_path}` and `{data_dir}` placeholders

## User Preferences

- Primary communication language: Japanese
- Commit messages / README / SKILL.md: English
- Diagrams: Mermaid (not PlantUML)
- Prefers quick iteration: change → syntax check → restart → verify on dashboard
- Prefers toggle buttons over separate start/stop buttons
