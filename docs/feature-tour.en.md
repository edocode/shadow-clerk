# Shadow-Clerk Feature Tour

Shadow-Clerk is a background daemon that transcribes and translates your web meetings in real time: your own microphone and whatever comes out of your speakers. When the meeting ends it writes the minutes. While the meeting is still going, an AI assistant can flag open points for you, and you can even talk a topic through with Claude by voice. Nearly everything is driven from a browser dashboard. It runs on Linux (PipeWire / PulseAudio) and Windows.

Transcription plus LibreTranslate translation needs no external API and no Claude Code; it all runs locally. Everything else is optional.

The screenshots in this tour use a made-up dataset: a team called "acme" holding its weekly sync (「週次定例」) about 「おやつ便」 (Oyatsu-bin), a fictional snack subscription service. The UI is in Japanese and the translation target is English, so the English labels used below may differ from what you see in the images. Installation and the full list of config keys live in the [README](../README.md).

## Starting up

```bash
clerk-daemon -d          # run in the background (logs go to daemon.log in the data directory)
clerk-util stop          # stop it
```

Run `clerk-daemon` without `-d` to keep it in the foreground; `Ctrl+C` stops it. Once it's up, open <http://localhost:8765> in your browser.

The dashboard is laid out like this:

- **Header**: start/stop meeting and translation, **Summary**, **Talk with Claude**, Glossary, PTT, Commands, ⚙ settings
- **Left pane**: pick a file from the **Dates** / **Meetings** / **Search** tabs
- **Center**: Transcript and Translation. The `T|R` button switches between showing both or just one
- **Right pane**: **Summary** / **AI Analysis** tabs
- **Bottom panel**: **AI Console** / **Talk with Claude** / **Logs**

## Real-time transcription and translation

While the daemon runs, whatever is said shows up in the Transcript pane as it happens. Lines from your microphone are tagged `[自分]` (me), lines from the speaker side (the other participants) are tagged `[相手]` (them), and every line carries a timestamp. Start translation and the translated lines appear in the Translation pane next to it.

![A meeting in progress: the date list on the left, the live Japanese transcript in the middle, and the English translation beside it](images/01_meeting_live.jpg)

- **Speech recognition**: Whisper by default; for Japanese you can switch to ReazonSpeech k2 or Kotoba-Whisper
- **Translation provider**: LibreTranslate (local), any OpenAI-compatible API, or Claude (`claude -p`)
- **Interim transcription**: turn on `interim_transcription` to see partial text before an utterance is finalized. It can use its own lighter model, and the partial text can be translated too
- **Typo correction**: a T5 model can fix recognition errors before the text goes to LibreTranslate (`spell-check` extra). With an LLM provider, there's also a step that has the model re-read the Japanese in hiragana to catch homophone mix-ups
- **Glossary**: translation and summaries use the [glossary](#glossary-and-misheard-pairs). In the screenshot above, おやつ便 comes out as "Oyatsu-bin"
- **Mute**: the mic and speaker buttons above the Transcript pause transcription for either side. The bars next to them are input levels, and they change color when a device only carries steady noise or total silence

## Meeting mode

Click **Start Meeting** in the header to start a meeting session. Recording switches to a transcript file for that meeting, and the button turns into a red **End Meeting**; click it again to finish. You can do the same with a voice command ("会議開始" / "会議終了"), with `clerk-util command start_meeting`, or let Google Calendar integration start and end meetings to match your events.

- A meeting started from the button is unnamed (ad-hoc) and goes to `transcript-YYYYMMDDHHMM.txt`. A calendar event, or a name you give it later, makes it `transcript-YYYYMMDDHHMM@週次定例.txt`
- To name a meeting, use the **Assign to Meeting** button next to the Transcript title and pick an existing meeting name or type a new one
- With `auto_translate: true`, translation starts together with the meeting

**Jump back to the live file with ★.** In the file dropdown, the file currently being recorded is marked with ★. If you're reading an older file, the ★ button next to the dropdown takes you straight back to it. When a meeting starts, ★ moves to the meeting file, and when it ends, back to the daily file.

**Minutes.** After the meeting, click **Summary** in the header to generate minutes, or set `auto_summary: true` to have them written automatically when the meeting ends. They appear in the right pane's **Summary** tab, where you can copy, reload or regenerate them.

![The Summary tab after the meeting, with Japanese minutes: date and time, an overview, and the main topics with their decisions](images/04_summary.jpg)

`summary_language` sets the language of the minutes and `summary_length` how long they should be (from half a page to five A4 pages). Drop a `summary_template.md` into the data directory to make them follow your own format. If the AI Console (next section) is still running when the meeting ends, the assistant there writes the minutes instead (`auto_summary_via_console`, on by default).

## Real-time AI analysis

You can have an AI assistant sit in on the meeting and pick out the open points as the discussion unfolds. The assistant is a real Claude Code (or Codex) session running in the **AI Console** at the bottom of the dashboard, and it follows the transcript with the bundled `/clerk-meeting-helper` skill.

![The AI Analysis tab: open items under Advice at the top, a timestamped record under Analysis below](images/02_ai_analysis.jpg)

The right pane's **AI Analysis** tab shows two files:

- **Advice** (`advice-*.md`): what is still open. It is grouped under headings such as "Ask now", "Intervention", "Assumptions not yet confirmed" and missing owners or deadlines, and each item is phrased so you can say it out loud right away. The file is rewritten from scratch every time, so items disappear once they're settled
- **Analysis** (`analysis-*.md`): what has been established. Agenda items, findings and decisions pile up under time headings, ready to feed into the minutes

The skill writes in your translation language, which is why the analysis of this Japanese meeting comes out in English.

![The AI Console enlarged: Claude Code running /clerk-meeting-helper, reporting what it recorded each time new lines arrive](images/03_ai_console.jpg)

To use it:

1. **Install Claude Code or Codex.** `ai_assistant_command` (default `claude`) decides what the console launches
2. **Install the skills**, either from the Welcome dialog on first launch or from the command line. This installs `clerk-meeting-helper` together with `clerk-talk`, which the next section uses

   ```bash
   clerk-util install-skill                  # ~/.claude/skills/ (Claude Code)
   clerk-util install-skill --target agents  # ~/.agents/skills/ (Codex and others)
   ```

3. **Start it.** With `auto_analyze: true` the assistant starts along with the meeting. Otherwise, click **Start analysis** in the **AI Analysis** tab. Once the assistant is ready, `/clerk-meeting-helper` is sent to it automatically

Each time new lines come in, the assistant updates Advice and Analysis and posts a short note in the console about what it recorded. Topics that must never be analyzed can be listed in `forbid-ai-analyze.txt` in the data directory (also editable from the settings dialog).

The console keeps running after the meeting ends, so the same session, with the whole discussion still in context, can write the minutes. Stop it with the console's **Stop** button. Permission prompts for file edits and commands follow your usual Claude Code settings. To launch the assistant in a different directory for a particular meeting, use the ⚙ next to that meeting in the meeting list.

## Talk with Claude

Click **Talk with Claude** in the header to discuss a topic with Claude by voice. Claude's replies are spoken with VOICEVOX, and what you say is transcribed as usual and passed to Claude.

![The "Start a talk with Claude" dialog, with fields for the topic, working directory, where to send Claude's voice and persona, plus the Edit personas and Voice settings buttons](images/05_talk_start.png)

You need the Claude Code CLI, a VOICEVOX engine running as a separate process (`http://localhost:50021` by default), and headphones. The dialog asks for:

- **Topic**: optional. If you leave it blank, Claude opens by asking what you'd like to talk about
- **Working directory**: where Claude looks if it needs to read files during the conversation
- **Persona**: a named description of Claude's character and how it should respond. Add or change them with **Edit personas**
- **Voice settings**: pick the VOICEVOX speaker and tune speed, pitch, intonation and volume, with a preview

![Talk mode in progress: the transcript alternates between [自分] and [Claude] lines, and the Talk with Claude console at the bottom shows the clerk-talk skill speaking and then waiting for a reply](images/06_talk_mode.jpg)

While the talk is running, the header shows a red **End Claude talk** button along with the topic, language and VOICEVOX voice.

- **It all goes into the transcript.** Claude's lines are written as `[Claude]` and get translated too, so you can read the discussion back later
- **You can cut in.** Claude speaks in short sentences, so you can interrupt between them. Say a stop word such as "stop" or "wait" (`talk_stop_words`) and playback stops; Claude is told where it was cut off
- **Two engines.** By default Claude runs as the `clerk-talk` skill in the **Talk with Claude** console at the bottom, where it can also edit files or run commands for you, with the usual permission prompts. `talk_engine: headless` switches to a background `claude -p` instead: it answers a little faster, but since it can't ask for permission it is limited to the tools in `talk_allowed_tools`
- **Works alongside the meeting assistant.** If `/clerk-meeting-helper` is analyzing the same transcript, `clerk-talk` also reads its Advice and brings up a point when the conversation goes quiet
- **Ending.** When the conversation seems to be wrapping up, Claude asks out loud and only ends the session itself after a clear yes. You can always end it from the dashboard button

**Sending Claude's voice into a meeting app (Linux, PipeWire).** Pick your meeting app under **Send Claude's voice to** (hit **Reload** if it isn't listed). Claude's speech is then wired into that app's microphone input, so the other participants hear it alongside your own voice. In this mode the other side is transcribed as `[相手]` as well, so Claude can follow what they say. Claude's own voice also reaches the speaker side, but lines that overlap its playback in time and closely match what it said are dropped, so it never ends up replying to itself. Without a target app, the speaker side isn't transcribed at all during talk mode. This needs `pw-dump`, `pw-link` and `pw-cat`, and isn't available on Windows.

## Finding past transcripts

The three tabs in the left pane open older records.

- **Dates**: the transcript for each day
- **Meetings**: meeting files grouped by meeting name. Pick a name to see its sessions; the badges on each one tell you what it has: **T** a translation, **S** minutes, **A** AI analysis (Advice or Analysis). ✏ renames the meeting, the sort toggles between ABC and newest first, and ⚙ sets the AI Console's launch directory for that meeting

![The Meetings tab, listing a 週次定例 session with T, S and A badges](images/07_meetings_tab.png)

- **Search**: narrow down by year, month, day and hour, then search transcripts, translations and minutes by keyword. The scope can be **All**, **T** (transcript), **R** (translation) or **S** (summary)

![The Search tab with results for the query 配送枠 (delivery slot)](images/08_search_tab.png)

## Extracting a meeting afterwards

Forgot to press Start Meeting? You can still carve a meeting out of the daily file. Tick two lines to mark a range, then click the ⏱ icon in the Transcript header to open the extract dialog.

![Two lines ticked in a daily transcript; the Transcript header shows 「2件選択」 (2 selected) and the ⏱ icon](images/09_extract_select.png)

The dialog offers these options:

- **Split by silence**: let it divide the whole file, or just the selected range, into meetings automatically, using silences longer than the number of minutes you choose. Handy for sorting out a day with several meetings in it
- **Extract selection**: turn the selected range into a single meeting. For a new meeting, choose ad-hoc (unnamed), an existing meeting name, or a new name. You can also append the range to an existing meeting file

![The 「会議として切り出す」 (Extract as Meeting) dialog, set to extract the selection as a new meeting named 「配送枠確認」](images/10_extract_modal.png)

Click **Create** and the meeting file appears, ready to open from the Meetings tab.

![The new meeting 「配送枠確認」 opened from the Meetings tab, with its transcript and translation](images/11_extract_created.png)

## Editing transcripts

Small talk and garbled lines can be deleted. Tick the lines and click the trash icon.

![Two rows ticked for deletion](images/12_select_rows.png)

The confirmation dialog lets you either **delete all lines in range** between the two ticks or **delete selected lines** only. It previews the affected transcript and translation lines, so you can check before deleting.

![The 「選択した行を削除しますか？」 (Delete selected lines?) dialog, with the two delete options and a preview of the transcript and translation](images/13_delete_rows_modal.png)

The trash button in the Transcript header deletes the whole file. For a meeting file, you can either delete it outright or merge its lines back into the daily file first.

## Voice commands

- **PTT (recommended)**: hold the PTT key (default `f23`, meant to be mapped to something like the Menu key with a key remapper) and say a command such as 「会議開始」 or 「翻訳開始」. No wake word needed
- **Wake word**: without the key, say the wake word first, as in 「シェルク、会議開始」 (spellings like `sheruku` are accepted too). Recognition is less reliable, so PTT is the safer choice. The wake word can be changed in the settings
- **Custom commands**: **Commands** in the header lets you register pairs of a regex pattern and a shell command. When what you say while holding PTT matches a pattern, the command runs

![The Custom Voice Commands editor: a table of regex patterns and the shell commands they run](images/15_commands.png)

- **Asking the LLM**: if nothing built-in or custom matches and an LLM is configured, what you said is sent to the LLM as a question and the answer shows up on the dashboard

## Glossary and misheard pairs

**Glossary** in the header opens `glossary.txt` for editing. It's a TSV with one column per language (`ja`, `en`, …) plus `reading` and `note`.

![The glossary editor, with おやつ便 and other terms in ja / en / reading / note columns](images/14_glossary.png)

- It is passed to the translation and summary prompts, which keeps terms consistent and helps fix misrecognitions
- When a `reading` shows up verbatim in the recognized text, it is replaced with the term itself (a term can have several readings, separated by commas)

Separately, `misheard.tsv` collects pairs of "what was actually said" and "how it was misheard". These are never applied to the transcript. Instead, both the `clerk-meeting-helper` and `clerk-talk` skills read them as hints when interpreting what people said, and add new pairs on their own as they spot them during a meeting.

## Settings

The ⚙ in the header opens the settings dialog. Almost everything can be changed there, and it is saved to `config.yaml`.

![The top half of the settings dialog: UI language, output directory, mic and speaker device selection, transcription, PTT key, wake word and interim settings](images/16_settings_transcription.png)

- **Basic**: UI language (Japanese/English), output directory
- **Audio devices**: choose the microphone and the speaker (monitor) by name. A device plugged in later appears after **Refresh list**
- **Transcription**: language, Whisper model, Japanese ASR model, PTT key, wake word and so on
- **Interim**: interim transcription and its model

![The lower half of the settings dialog: translation, summary and LLM / API settings](images/17_settings_translation_llm.png)

- **Translation**: auto-translate, provider, LibreTranslate, typo correction, the hiragana re-reading step
- **Summary**: auto-summary, source, language, length
- **LLM / API**: LLM provider (`claude` / `api`), endpoint and model of an OpenAI-compatible API

Every config key and its default is listed in the README's [Configuration](../README.md#configuration) section. You can also change settings from the command line with `clerk-util read-config` and `clerk-util write-config-value <key> <value>`.

## Google Calendar and browser screenshots

**Google Calendar**: install the `gcal` extra and authorize with OAuth, and the daemon checks your calendar periodically and starts and ends meetings to match your events. The event title becomes the meeting name, and invitees are shown as expected attendees above the minutes. See [docs/google-calendar-setup.md](google-calendar-setup.md) for the setup.

**Browser screenshots**: the Chrome extension in [`extension/`](../extension/) captures the visible tab (a screen share, for example), saves the image in the data directory and adds a `[画面]` (screen) line to the transcript being recorded. Screens and speech end up on the same timeline, so a remark like "this slot here" still makes sense later. Details are in [extension/README.md](../extension/README.md).

## Data directory

Records and settings live in `~/.local/share/shadow-clerk/` (`%APPDATA%\shadow-clerk` on Windows). The main files:

| File | Contents |
| --- | --- |
| `transcript-YYYYMMDD.txt` | Daily transcript |
| `transcript-YYYYMMDDHHMM[@name].txt` | Meeting transcript |
| `transcript-…-<lang>.txt` | Translation (e.g. `-en`) |
| `summary-….md` | Minutes |
| `advice-….md` / `analysis-….md` | AI Console's open items / established facts |
| `glossary.txt` | Glossary (TSV) |
| `misheard.tsv` | Misheard pairs collected by the skills |
| `meeting.yaml` | Per-meeting settings (such as the AI Console's launch directory) |
| `config.yaml` | Configuration |

The complete list is in the README's [File structure](../README.md#file-structure) section.

## Wrap-up

| Feature | What it does |
| --- | --- |
| Real-time transcription and translation | Whisper / ReazonSpeech / Kotoba-Whisper with LibreTranslate / OpenAI-compatible API / Claude. Can run fully local |
| Meeting mode and minutes | Start and end from a button, by voice or from your calendar. Minutes on demand or automatically |
| Real-time AI analysis | Claude Code or Codex in the AI Console writes down open points and settled facts while the meeting runs |
| Talk with Claude | Discuss with Claude in a VOICEVOX voice; on Linux + PipeWire, Claude can join your meeting app too |
| Organizing records | Dates, Meetings and Search tabs, extracting meetings afterwards, deleting lines or files |
| Voice commands | PTT, wake word, custom commands, questions to the LLM |
| Glossary and misheard pairs | Better translations and summaries, and context hints for the skills |
