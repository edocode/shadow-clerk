# Shadow-Clerk Feature Tour

Shadow-Clerk is a resident daemon that transcribes and translates meeting and desktop audio in real time. All features can be controlled from a browser-based dashboard. It runs on Ubuntu + PipeWire / PulseAudio environments.

**Minimal setup without LLM:** Transcription + LibreTranslate translation requires no external API or Claude Code. Everything runs locally.

## Starting Up

Start the daemon with `clerk-util start`. Add the `-d` option to run in the background (daemon mode).

![Daemon startup in terminal](images/00_terminal_startup.png)

Once started, access the dashboard at `http://127.0.0.1:8765`.

![Dashboard - right after transcription starts](images/01_dashboard_transcript.png)

The dashboard consists of a toolbar, two panes (Transcript / Translation), and a Logs panel at the bottom. The toolbar includes language selection, ASR model selection, recording controls, and various action buttons.

## Real-time Transcription

While the daemon is running, speech is recorded in real time in the **Transcript** pane on the left. Each line includes a speaker label (`[Self]`, `[Mx]`, etc.) and timestamp.

Available speech recognition engines:

- **Whisper** (default) - Multi-language support
- **ReazonSpeech k2** - Japanese-specialized, accurate and lightweight (recommended for Japanese)
- **Kotoba-Whisper** - Japanese-specialized, large-v3 equivalent accuracy

The recognition language can be switched from the language selector at the top left of the dashboard. Setting it to Auto enables Whisper's automatic language detection.

### Interim Transcription

When `interim_transcription: true` is set, partial transcription results are displayed in real time as speech is in progress. The pre-finalized text updates incrementally, making it easy to see "what is being said right now" during meetings. A lightweight model (tiny / base) can be specified separately for interim transcription.

## Real-time Translation

Press the **Start Translation** button to output translated text in the **Translation** pane on the right.

![Transcript and translation side by side](images/02_transcript_and_translation.png)

Three translation providers are available:

| Provider           | Features                                                                                  |
| ------------------ | ----------------------------------------------------------------------------------------- |
| **LibreTranslate** | Runs locally. Transcription and translation can be done entirely on-device                |
| **Claude**         | Translates via Claude Code subagent. No API key needed, high quality                      |
| **API**            | Specify an OpenAI-compatible API endpoint for translation (supports local LLMs and cloud) |

When using LibreTranslate, start the local server in a separate terminal.

![LibreTranslate terminal output](images/15_libretranslate_terminal.png)

### Spell Correction (Pre-translation)

When `libretranslate_spell_check: true` is set, speech recognition typos are corrected using a T5 model before being sent to LibreTranslate. Requires installing the `spell-check` extra.

## Mic / Speaker Mute

Use the **Mic Mute** / **Speaker Mute** buttons on the toolbar to temporarily stop transcription. Audio detection continues in the background, but writing to the transcript is paused.

Speaker audio (e.g., the other party's voice in a meeting) can also be included in the transcript.

## Meeting Mode

Start meeting mode by pressing the **Start Meeting** button.

![Meeting start](images/05_meeting_start.png)

- A new transcript file (`YYYYMMDDHHMMSS.txt`) is created when a meeting starts
- `--- Meeting Start ---` / `--- Meeting End ---` markers are inserted into the transcript
- Regular transcripts are organized by date (`YYYYMMDD.txt`), while meetings are recorded in files that include the time

![Transcription during a meeting](images/06_meeting_transcript.png)

When a meeting ends, a summary is automatically generated (if Auto Summary is enabled in settings).

### Extracting Meetings After the Fact

If you forgot to press the meeting start button, you can select a time range by checking two rows in the daily transcript file and clicking the clock icon to extract it as a meeting file.

![Meeting extraction - range selection](images/12_meeting_extract_select.png)

The modal shows the selected time range, and you can choose to "Create new meeting" or "Append to existing meeting".

![Meeting extraction modal](images/13_meeting_extract_modal.png)

Press the create button to generate a new meeting transcript file.

![Meeting file created](images/14_meeting_extract_created.png)

## Transcript Editing

Select multiple rows using checkboxes and click the trash icon to show a deletion confirmation modal.

![Row selection](images/09_select_rows.png)

Selecting two rows allows you to bulk-delete all rows in between.

![Row deletion modal](images/10_delete_rows_modal.png)

The deletion modal shows a preview of the transcript and translation content to be deleted. Press "Delete" after confirming.

You can also press the clear button next to the transcript to show a file deletion confirmation modal.

![File deletion modal](images/11_delete_file_modal.png)

## Claude Code Integration

Run `clerk-util claude-setup` to register the skill with Claude Code.

![Starting from Claude Code](images/16_claude_code_setup.png)

After registration, the following commands are available within Claude Code:

| Command                              | Action                              |
| ------------------------------------ | ----------------------------------- |
| `/shadow-clerk start`                | Start daemon in background          |
| `/shadow-clerk stop`                 | Stop daemon                         |
| `/shadow-clerk`                      | Update minutes from transcript diff |
| `/shadow-clerk full`                 | Regenerate minutes from full text   |
| `/shadow-clerk status`               | Check current status                |
| `/shadow-clerk config show`          | Show current settings               |
| `/shadow-clerk config set KEY VALUE` | Change a setting                    |

When the translation provider is set to Claude, translation is performed via Claude Code subagent. Results are saved to `~/.local/share/shadow-clerk/transcript-YYYYMMDD-<lang>.txt`.

## Summary

Click the **Summary** button to generate a summary of the transcript using an LLM. You can choose transcript (original) or translation as the summary source.

In meeting mode, summaries can be automatically generated when a meeting ends.

## Voice Commands

Hold the PTT (Push-to-Talk) key while speaking to have your speech recognized as a command.

![Glossary and commands tab](images/08_glossary_commands.png)

### PTT Mode (Recommended)

Hold the PTT key (default: F23 = Menu key) while speaking a command. No prefix needed, less prone to misrecognition.

### Wake Word Mode

Even without the PTT key, you can speak a wake word (default: "sheruku" / "シェルク") followed by a command for hands-free control. However, recognition is often unreliable, so PTT is recommended. The wake word can be changed in settings.

### Custom Voice Commands

Register custom voice commands in `config.yaml` under `custom_commands`:

```yaml
custom_commands:
  - pattern: "youtube|ユーチューブ"
    action: "xdg-open https://www.youtube.com"
  - pattern: "gmail|メール"
    action: "xdg-open https://mail.google.com"
```

`pattern` is a regular expression, and `action` is a shell command to execute. Custom commands are evaluated in order when no built-in command (start meeting, start translation, etc.) matches. Editing from the dashboard's "Commands" tab is more convenient.

## LLM Response

When no built-in or custom command matches, the input falls back to the LLM. Hold the PTT key and speak — the content is sent to the LLM, and the response is displayed at the top of the dashboard.

![LLM response](images/07_llm_response.png)

Claude or OpenAI-compatible APIs (local LLMs or cloud services) can be configured as the LLM provider.

## Glossary

Manage terminology from the **Glossary** tab on the dashboard. Register technical terms in TSV format to improve translation accuracy and enable text replacement during speech recognition (reading-based). The glossary is saved at `~/.local/share/shadow-clerk/glossary.txt`.

## Data Directory

Transcripts and settings are stored in `~/.local/share/shadow-clerk/`:

| File                            | Contents                           |
| ------------------------------- | ---------------------------------- |
| `transcript-YYYYMMDD.txt`       | Daily transcript                   |
| `transcript-YYYYMMDDHHMMSS.txt` | Meeting session transcript         |
| `transcript-YYYYMMDD-en.txt`    | Translation (with language code)   |
| `summary-YYYYMMDD.md`           | Meeting minutes                    |
| `glossary.txt`                  | Glossary (TSV)                     |
| `config.yaml`                   | Configuration file                 |

## Settings

All settings can be changed from the dashboard via the gear icon in the toolbar. The UI language can also be switched between Japanese and English.

### Transcription Settings

![Settings - Transcription](images/03_settings_transcription.png)

| Setting               | Description                                                                    |
| --------------------- | ------------------------------------------------------------------------------ |
| Default Language      | Default recognition language (ja, en, etc.). Also changeable from the toolbar  |
| Whisper Model         | Whisper model size (tiny / base / small / medium / large)                      |
| Initial Prompt        | Whisper initial prompt                                                         |
| Beam Size             | Beam search width. Larger values improve accuracy                              |
| Device                | Inference device (cpu / cuda)                                                  |
| Japanese ASR Model    | Japanese-specialized model (reazonspeech-k2 / kotoba-whisper / default)        |
| Interim Transcription | Enable/disable interim transcription (real-time display during speech)         |
| PTT Key               | Key assignment for Push-to-Talk / commands (e.g., F23 as Menu key)             |

### Translation, Summary & LLM Settings

![Settings - Translation, Summary & LLM](images/04_settings_translation_summary_llm.png)

| Section         | Key Settings                                                                           |
| --------------- | -------------------------------------------------------------------------------------- |
| **Translation** | Target language, auto-translate, translation provider (Claude / LibreTranslate / API), spell check |
| **Summary**     | Auto-summary enable/disable, summary source (transcript / translation)                 |
| **LLM / API**   | LLM provider, API endpoint, model selection                                            |

## Overview

Key features of Shadow-Clerk:

| Feature                        | Description                                                                              |
| ------------------------------ | ---------------------------------------------------------------------------------------- |
| **Real-time Transcription**    | Whisper / ReazonSpeech / Kotoba-Whisper. Interim transcription available                 |
| **Real-time Translation**      | Claude / LibreTranslate / OpenAI-compatible API. LibreTranslate runs entirely locally     |
| **Meeting Mode**               | Start/end markers, auto-summary generation, after-the-fact extraction                    |
| **Summary & LLM Integration** | Summary generation and Q&A via Claude / OpenAI-compatible API                            |
| **Voice Commands**             | PTT / wake word mode. Custom command registration, LLM fallback                          |
| **Claude Code Integration**    | Start/stop, generate minutes, change settings from Claude Code via skill registration    |
| **Spell Correction**           | T5 model-based typo correction before translation                                        |
| **Glossary**                   | Manage technical terms in TSV format, improve translation accuracy                       |
| **Web Dashboard**              | Operate all features from a browser, settings changes reflected in real time              |
| **Transcript Management**      | Row deletion, meeting extraction, file management                                        |
