"""Shadow-clerk: i18n 文字列テーブル (en)"""
# pylint: disable=duplicate-code  # 日英テーブルは同一プレースホルダ構造を持つため
from __future__ import annotations

STRINGS_EN: dict[str, str] = {
    # --- rec.* ---
    "rec.recording": "Recording... (Ctrl+C to stop)",
    "rec.output": "Output: {path}",
    "rec.backend": "Backend: {name}",
    "rec.already_running": "Error: clerk-daemon is already running (PID: {pid}). Stop it with `clerk-util stop` first.",
    "rec.pipewire_devices": "\n=== PipeWire Devices ===",
    "rec.pulseaudio_sources": "\n=== PulseAudio Sources ===",
    "rec.sounddevice_devices": "=== sounddevice Devices ===",
    "rec.no_devices": "  (No devices found)",
    "rec.no_sources": "  (No sources found)",
    "rec.pw_unavailable": "  (pw-record is not available)",
    "rec.pa_unavailable": "  (pactl is not available)",
    "rec.wasapi_loopback_mics": "\n=== WASAPI Loopback Microphones ===",
    "rec.wasapi_soundcard_unavailable": "  (soundcard not available)",
    "rec.auto_detect_sd": "\n[Auto-detect] sounddevice monitor: device #{device}",
    "rec.auto_detect_backend": "[Auto-detect] {backend} monitor: {source}",
    "rec.meeting_start": "Meeting started: {path}",
    "rec.meeting_end": "Meeting ended: {path}",
    "rec.model_changing": "Changing model: {model} ...",
    "rec.model_changed": "Model changed: {model}",
    "rec.translate_start": "Translation started",
    "rec.translate_stop": "Translation stopped",
    "rec.custom_exec": "Custom command: {action}",
    "rec.voice_cmd_llm": "  Voice command (LLM): {text} -> {command} (confidence={confidence})",
    "rec.voice_cmd_fail": "  Could not recognize command: {text} (confidence={confidence})",
    "rec.auto_summary_start": "  Generating summary: {src} -> {dst}",
    "rec.auto_summary_done": "  Summary complete: {name}",
    "rec.auto_summary_fail": "  Summary failed: {error}",
    "rec.auto_summary_timeout": "  Summary timed out",
    "rec.ptt_on": "[PTT] Command mode ON ({vkey} pressed)",
    "rec.ptt_off": "[PTT] Command mode OFF ({vkey} released)",

    # --- dash.* ---
    "dash.meeting_start": "Start Meeting",
    "dash.meeting_end": "End Meeting",
    "dash.translate_start": "Start Translation",
    "dash.translate_stop": "Stop Translation",
    "dash.translate_regen": "Regenerate translation",
    "dash.translate_regen_confirm": "Regenerate translation from scratch?",
    "dash.translating": "Translating...",
    "dash.translate_claude_hint": "When llm_provider is claude, please run translation from Claude Code (/shadow-clerk translate <lang>)",
    "dash.realtime_translation": "Realtime Translation",
    "dash.summary": "Summary",
    "dash.view_summary": "View Summary",
    "dash.custom_cmd_placeholder": "Custom command",
    "dash.send": "Send",
    "dash.glossary": "Glossary",
    "dash.settings": "Settings",
    "dash.settings_title": "Settings",
    "dash.glossary_title": "Glossary (glossary.txt)",
    "dash.summary_title": "Summary",
    "dash.saved": "Saved",
    "dash.cancel": "Cancel",
    "dash.save": "Save",
    "dash.close": "Close",
    "dash.add_row": "+ Add Row",
    "dash.summary_regen": "Regenerate summary",
    "dash.summary_regen_confirm": "Regenerate summary from scratch?",
    "dash.summary_started": "Summary generation started. You will be notified when complete.",
    "dash.summary_prefix": "Summary: ",
    "dash.no_summary": "(No summary available)",
    "dash.alert_cmd_fail": "Could not recognize command: {text}",
    "dash.alert_summary_done": "Summary generated: {name}",
    "dash.transcript_not_found": "Transcript not found",
    "dash.summary_generation_started": "Summary generation started",
    "dash.detect_language": "Detection Lang",
    "dash.meeting_toggle_start": "Start Meeting",
    "dash.meeting_toggle_end": "End Meeting",
    "dash.mute_mic": "Mute Mic",
    "dash.unmute_mic": "Unmute Mic",
    "dash.mute_monitor": "Mute Speaker",
    "dash.unmute_monitor": "Unmute Speaker",
    "dash.mic_unavailable": "Mic Unavailable",
    "dash.monitor_unavailable": "Speaker Unavailable",
    "dash.ts_mic_title": "Microphone capture failed",
    "dash.ts_monitor_title": "Speaker (monitor) capture failed",
    "dash.ts_possible_causes": "Possible causes:",
    "dash.ts_mic_cause1": "Microphone is not connected",
    "dash.ts_monitor_cause1": "Monitor device (loopback) not found",
    "dash.ts_cause_service": "Audio service has crashed",
    "dash.ts_fix_steps": "How to fix:",
    "dash.ts_restart_service": "Restart the audio service:",
    "dash.ts_list_devices": "Check available devices:",
    "dash.ts_restart_clerk": "Restart clerk-daemon with the device ID:<br><code>clerk-daemon {opt} DEVICE_ID</code>",
    "dash.custom_commands": "Commands",
    "dash.custom_commands_title": "Custom Voice Commands",
    "dash.custom_cmd_pattern": "Pattern (regex)",
    "dash.custom_cmd_action": "Action (shell command)",
    "dash.custom_cmd_hint": "When you speak while holding the PTT key and the text matches a pattern, the action is executed.",
    "dash.delete_line_title": "Delete this line?",
    "dash.delete_line_transcript": "Transcript",
    "dash.delete_line_translation": "Translation",
    "dash.delete": "Delete",
    "dash.delete_error": "Failed to delete",
    "dash.bulk_delete_title": "Delete selected lines?",
    "dash.bulk_delete_selected": "Delete selected lines",
    "dash.bulk_delete_range": "Delete all lines in range",
    "dash.delete_file_title": "Delete this file?",
    "dash.delete_file_desc": "The following files will be deleted:",
    "dash.extract_meeting_title": "Extract as Meeting",
    "dash.extract_meeting_new": "Create new meeting",
    "dash.extract_meeting_adhoc": "Ad-hoc (unnamed)",
    "dash.extract_meeting_use_group": "Assign to existing group",
    "dash.extract_meeting_new_name": "Create new name",
    "dash.extract_meeting_name_ph": "Enter meeting name",
    "dash.extract_meeting_existing": "Add to existing meeting file",
    "dash.extract_meeting_create": "Create",
    "dash.extract_meeting_range": "Range: {start} - {end}",
    "dash.extract_meeting_lines": "{count} lines selected",
    "dash.extract_meeting_success": "Meeting file created: {name}",
    "dash.extract_meeting_error": "Failed to extract meeting",
    "dash.extract_meeting_no_lines": "No lines in selected range",
    "dash.delete_file_merge": "Merge back to daily (merge meeting lines into daily transcript and delete)",
    "dash.delete_file_delete_only": "Delete completely",
    "dash.merge_to_daily_error": "Failed to merge into daily transcript",
    "dash.extract_split_all": "All: split by",
    "dash.extract_split_range": "Selection: split by",
    "dash.extract_split_min_suffix": "min+ silence → candidate; confirmed if active for 3min (gap≤1min); ended by 3min silence",
    "dash.extract_extract_range": "Extract selection",
    "dash.extract_split_success": "Split into {count} meeting files",
    "dash.extract_split_error": "Failed to split by silence",
    "dash.extract_split_no_segments": "No split point found for the specified silence",
    "dash.selected_count": "{count} selected",
    "dash.meetings": "Meetings",
    "dash.meetings_back": "Back to list",
    "dash.meetings_empty": "No meetings yet.",
    "dash.sort_abc": "ABC",
    "dash.sort_newest": "Newest first",
    "dash.sort_title": "Toggle sort order",
    "dash.tab_dates": "Dates",
    "dash.tab_meetings": "Meetings",
    "dash.tab_search": "Search",
    "dash.dates_empty": "No daily transcripts.",
    "dash.search_year": "Y",
    "dash.search_month": "M",
    "dash.search_day": "D",
    "dash.search_hour": "H",
    "dash.search_query": "Text",
    "dash.search_type_all": "All",
    "dash.search_type_transcript": "Transcript",
    "dash.search_type_translation": "Translation",
    "dash.search_type_summary": "Summary",
    "dash.search_btn": "Search",
    "dash.search_empty": "No results.",
    "dash.rename_group_title": "Rename Meeting",
    "dash.rename_group_new": "New meeting name",
    "dash.rename_group_preview": "{n} files will be renamed",
    "dash.rename_meeting_title": "Assign to Meeting",
    "dash.rename_meeting_existing": "Select existing meeting",
    "dash.rename_meeting_new": "New meeting name",
    "dash.rename_meeting_placeholder": "Enter name (blank = ad-hoc)",
    "dash.rename_meeting_apply": "Apply",
    "dash.gcal_events": "Google Calendar",
    "dash.gcal_events_title": "Google Calendar Events",
    "dash.attendees": "Expected Attendees",
    "dash.attendees_empty": "(No attendee information)",
    "dash.attendees_note": "Note: Based on calendar invitations; may differ from actual attendance.",
    "dash.gcal_disabled": "Google Calendar integration is not enabled.",
    "dash.gcal_no_events": "No events today.",
    "dash.loading": "Loading...",
    "dash.help": "Help",
    "dash.help_title": "Help",
    "dash.help_body": (
        "[Button Controls]\n"
        "▶ Start Meeting / ■ End Meeting\n"
        "  Start/end a meeting session.\n"
        "  A dedicated transcript file is created on start.\n\n"
        "▶ Start Translation / ■ Stop Translation\n"
        "  Start/stop real-time translation.\n"
        "  Only works when llm_provider is set to api.\n\n"
        "Summary\n"
        "  Generate meeting minutes from current transcript.\n\n"
        "View Summary\n"
        "  View generated meeting minutes.\n\n"
        "[Panel Controls]\n"
        "T|R button: Cycle Transcript/Translation display\n"
        "  T|R → T only → R only → T|R (cycle)\n\n"
        "Logs ▼▲: Toggle log panel visibility\n\n"
        "🎤 / 🔊: Mute mic/speaker transcription\n"
        "  Audio capture continues while muted,\n"
        "  but transcription is skipped.\n\n"
        "[Voice Commands]\n"
        "Hold PTT key (default: Menu) and speak:\n"
        "  Start/End Meeting, Start/Stop Translation\n"
        "  Set Language Japanese/English\n\n"
        "[Settings]\n"
        "Click ⚙ to open settings.\n"
        "Key settings:\n"
        "  - UI Language / Translation Language / Whisper Model\n"
        "  - LLM Provider / API Endpoint\n"
        "  - PTT Key / Interim Transcription\n"
    ),

    "dash.audio_device_monitor": "monitor",

    # --- cfg.section.* ---
    "cfg.section.general": "General",
    "cfg.section.audio": "Audio Devices",
    "cfg.section.transcription": "Transcription",
    "cfg.section.interim": "Interim (pre-confirmed)",
    "cfg.section.translation": "Translation",
    "cfg.section.summary": "Summary",
    "cfg.section.api": "LLM / API",
    "cfg.section.gcal": "Google Calendar Integration",

    # --- cfg.* ---
    "cfg.translate_language": "Translation Language",
    "cfg.auto_translate": "Auto Translate",
    "cfg.auto_summary": "Auto Summary",
    "cfg.default_language": "Default Language",
    "cfg.default_model": "Whisper Model",
    "cfg.output_directory": "Output Directory",
    "cfg.output_directory_ph": "null=data directory",
    "cfg.mic_device": "Microphone",
    "cfg.monitor_device": "Speaker (monitor)",
    "cfg.device_auto": "Auto (OS default)",
    "cfg.device_cli_pinned": "Pinned by CLI (--mic / --monitor)",
    "cfg.device_refresh": "Refresh list",
    "cfg.device_refresh_title": "Re-detect devices. Audio drops briefly.",
    "cfg.llm_provider": "LLM Provider",
    "cfg.api_endpoint": "API Endpoint",
    "cfg.api_model": "API Model",
    "cfg.api_key_env": "API Key Env Var",
    "cfg.api_disable_thinking": "Disable Thinking (translation/interim)",
    "cfg.initial_prompt": "Initial Prompt",
    "cfg.initial_prompt_ph": "Whisper hint words",
    "cfg.voice_command_key": "PTT Key",
    "cfg.wake_word": "Wake Word",
    "cfg.wake_word_ph": "Trigger word for voice commands",
    "cfg.whisper_beam_size": "Beam Size",
    "cfg.whisper_compute_type": "Compute Type",
    "cfg.whisper_device": "Device",
    "cfg.interim_transcription": "Interim Transcription",
    "cfg.interim_translation": "Interim Translation",
    "cfg.interim_translation_provider": "Interim Translation Provider (empty=auto)",
    "cfg.interim_translation_provider_claude_warn": "⚠ claude takes 5-10s per call which is too slow for interim. Updates that arrive while a translation is in flight are dropped from the queue, so the result lands at roughly the same time as the confirmed translation. libretranslate / api strongly recommended.",
    "cfg.interim_model": "Interim Model",
    "cfg.custom_commands": "Custom Commands",
    "cfg.ui_language": "UI Language",
    "cfg.translation_provider": "Translation Provider",
    "cfg.libretranslate_endpoint": "LibreTranslate URL",
    "cfg.libretranslate_api_key": "LibreTranslate API Key",
    "cfg.libretranslate_spell_check": "Spell Check (LibreTranslate)",
    "cfg.spell_check_model": "Spell Check Model",
    "cfg.summary_source": "Summary Source",
    "cfg.summary_language": "Summary Language",
    "cfg.translation_hiragana_step": "Hiragana Thinking Step",
    "cfg.summary_hiragana_step": "Hiragana Thinking Step",
    "cfg.summary_length": "Summary Length",
    "cfg.japanese_asr_model": "Japanese ASR Model",
    "cfg.kotoba_whisper_model": "Kotoba-Whisper Model",
    "cfg.interim_japanese_asr_model": "Interim Japanese ASR Model",
    "cfg.gcal_integration": "Enable Google Calendar Integration",
    "cfg.gcal_credentials_file": "credentials.json Path",
    "cfg.gcal_credentials_file_ph": "~/.local/share/shadow-clerk/credentials.json",
    "cfg.gcal_calendar_id": "Calendar ID",
    "cfg.gcal_buffer_minutes": "Start Buffer (minutes)",
    "cfg.gcal_end_buffer_minutes": "End Buffer (minutes)",

    # --- llm.* ---
    "llm.translate_system": (
        "You are a translation assistant. Translate the following speech recognition transcript into {lang}.\n"
        "\n"
        "1. Correct speech recognition errors from context, and apply glossary corrections if a reading matches (match top to bottom in order).\n"
        "2. Translate each line into {lang} and return in 'number: translated text' format. Output only the translated lines, no extra explanations.\n"
        "{hiragana_step}"
    ),
    "llm.correct_system": (
        "You are a speech recognition error correction assistant.\n"
        "The input is Japanese speech recognition output containing many kanji misconversions.\n"
        "Follow these rules to correct misconversions:\n"
        "\n"
        "1. Each line is given in 'number: text' format. Return results in the same 'number: corrected text' format.\n"
        "2. Speech recognition frequently misconverts homophones. Consider the 'reading' of each word and correct to the right kanji/notation based on context.\n"
        "3. Words whose reading matches a glossary reading mapping MUST be corrected to the glossary's correct notation. Match readings from top to bottom in order.\n"
        "4. Even words not in the glossary should be corrected if clearly misconverted based on context.\n"
        "5. Output only the number and corrected text after the colon. No extra explanations.\n"
        "6. Output all lines including those that need no correction (do not omit any)."
    ),
    "llm.summary_full_system": (
        "You are a meeting minutes assistant. Strictly follow the given template to output meeting minutes.\n"
        "Do not output in any format other than the template.{length_instruction}"
    ),
    "llm.summary_full_user": (
        "Create meeting minutes from the following transcript (speech-to-text).\n"
        "\n"
        "[OUTPUT TEMPLATE - follow this structure exactly]\n"
        "{summary_format}\n"
        "\n"
        "[RULES]\n"
        "- Write the entire output in {summary_language}. Translate the template's headings and labels (e.g. \"Meeting Minutes\", \"Date/Time\", \"Summary\") into {summary_language} while preserving the markdown structure (heading levels, bullet markers, code fences)\n"
        "- Each transcript line is in [YYYY-MM-DD HH:MM:SS] [Speaker] Text format\n"
        "- Fix speech recognition errors by inferring correct words from context\n"
        "- Infer the most appropriate spelling for proper nouns and technical terms\n"
        "- If the glossary includes a 'reading' for a term, and the transcript contains a similar-sounding word, correct it to the proper term. Match readings from top to bottom in order\n"
        "- Do not omit anything that could become a task or TODO, even if the discussion was brief or supplementary\n"
        "- Do not guess speaker names. The transcript only distinguishes 'self' and 'other', so attributing statements to specific individuals is unreliable. Use impersonal forms like 'it was suggested that...' instead\n"
        "{hiragana_step}"
        "{length_instruction}"
        "{attendees_block}"
        "\n"
        "[TRANSCRIPT]\n"
        "{transcript}"
    ),
    "llm.summary_update_system": (
        "You are a meeting minutes assistant. Strictly follow the given template to output meeting minutes.\n"
        "Do not output in any format other than the template.{length_instruction}"
    ),
    "llm.summary_update_user": (
        "Update the existing meeting minutes with the new transcript content.\n"
        "\n"
        "[OUTPUT TEMPLATE - follow this structure exactly]\n"
        "{summary_format}\n"
        "\n"
        "[RULES]\n"
        "- Write the entire output in {summary_language}. Translate the template's headings and labels (e.g. \"Meeting Minutes\", \"Date/Time\", \"Summary\") into {summary_language} while preserving the markdown structure (heading levels, bullet markers, code fences)\n"
        "- Maintain existing minutes content while adding/integrating new information\n"
        "- Each transcript line is in [YYYY-MM-DD HH:MM:SS] [Speaker] Text format\n"
        "- Fix speech recognition errors by inferring correct words from context\n"
        "- Infer the most appropriate spelling for proper nouns and technical terms\n"
        "- If the glossary includes a 'reading' for a term, and the transcript contains a similar-sounding word, correct it to the proper term. Match readings from top to bottom in order\n"
        "- Do not omit anything that could become a task or TODO, even if the discussion was brief or supplementary\n"
        "- Do not guess speaker names. The transcript only distinguishes 'self' and 'other', so attributing statements to specific individuals is unreliable. Use impersonal forms like 'it was suggested that...' instead\n"
        "{hiragana_step}"
        "{length_instruction}"
        "{attendees_block}"
        "\n"
        "## Existing Meeting Minutes\n"
        "{existing}\n"
        "\n"
        "## New Transcript (diff)\n"
        "{transcript}"
    ),
    "llm.summary_hiragana_step": "",
    "llm.translation_hiragana_step": "",
    "llm.summary_update_none": "(None — please create new minutes)",
    "llm.summary_attendees_block": (
        "\n[EXPECTED ATTENDEES (from Google Calendar)]\n"
        "{attendees}\n"
        "Note: this list is based on calendar invitations and may differ from actual attendance. "
        "Even when attributing remarks, avoid definitive attribution since the transcript alone "
        "cannot determine who actually spoke."
    ),
    "llm.summary_length_half": "\n[OUTPUT LENGTH] At least half an A4 page (400+ characters). May be longer if important content warrants it.",
    "llm.summary_length_1page": "\n[OUTPUT LENGTH] At least one A4 page (800+ characters). May be longer if important content warrants it.",
    "llm.summary_length_2pages": "\n[OUTPUT LENGTH] At least two A4 pages (1600+ characters). Describe each topic's discussion in detail. May be longer if important content warrants it.",
    "llm.summary_length_3pages": (
        "\n[OUTPUT LENGTH] At least three A4 pages (2400+ characters)."
        " Describe each topic's background, discussion, and conclusions thoroughly."
        " In the Detailed Notes section, include specific quotes from key statements."
        " Do not omit important content — longer output is fine if needed."
    ),
    "llm.summary_length_4pages": (
        "\n[OUTPUT LENGTH] At least four A4 pages (3200+ characters)."
        " Describe each topic's background, discussion, each participant's opinions, and conclusions comprehensively."
        " In the Detailed Notes section, include specific quotes and capture the flow of discussion."
        " Do not omit important content — longer output is fine if needed."
    ),
    "llm.summary_length_5pages": (
        "\n[OUTPUT LENGTH] At least five A4 pages (4000+ characters)."
        " Describe each topic's background, discussion, each participant's opinions, conclusions, and action items comprehensively."
        " In the Detailed Notes section, include extensive specific quotes and capture the full flow of discussion."
        " Write as detailed minutes, not a summary — someone who did not attend should be able to fully understand the discussion."
    ),
    "llm.summary_format": (
        "Follow this template structure exactly. Do not add or omit any headings.\n"
        "Heading and label text (e.g. \"Meeting Minutes\", \"Date/Time\", \"Summary\") MUST be translated into the output language, but preserve the markdown structure (heading levels, bullets, indentation, code fences).\n"
        "If a section has no content, write the output language's equivalent of \"N/A\".\n"
        "\n"
        "```\n"
        "# Meeting Minutes\n"
        "\n"
        "- **Date/Time**: YYYY-MM-DD HH:MM - HH:MM (estimated from transcript timestamps)\n"
        "- **Participants**: (list if identifiable, omit if unknown)\n"
        "\n"
        "## Summary\n"
        "(3-5 sentence summary of the meeting)\n"
        "\n"
        "## Key Topics and Decisions\n"
        "- **Topic 1**: Summary of discussion\n"
        "  - Decision: ...\n"
        "- **Topic 2**: ...\n"
        "\n"
        "## Action Items\n"
        "- [ ] Owner: Task description (deadline if applicable)\n"
        "\n"
        "## Detailed Notes\n"
        "(Important statements and supplementary information)\n"
        "```"
    ),
    "llm.query_system": "You are a helpful assistant. Please respond concisely.",
    "llm.match_command_system": (
        "You are a voice command recognition assistant.\n"
        "Receive the user's speech recognition text and predict the closest matching command.\n"
        "\n"
        "Available commands:\n"
        "{commands}\n"
        "\n"
        "Rules:\n"
        "1. Consider speech recognition errors and choose the semantically closest command.\n"
        '2. Return results in JSON only:\n'
        '   {{"command": "matched command", "confidence": 0-100 integer}}\n'
        "3. confidence: 100 for exact match, 60-80 for somewhat ambiguous, 0-30 for unrelated."
    ),

    # --- vcmd.* ---
    "vcmd.start_meeting": "Start meeting",
    "vcmd.end_meeting": "End meeting",
    "vcmd.translate_start": "Start translation",
    "vcmd.translate_stop": "Stop translation",
    "vcmd.set_language_ja": "Set language to Japanese",
    "vcmd.set_language_en": "Set language to English",
    "vcmd.unset_language": "Set language to auto-detect",

    # --- speaker.* ---
    "speaker.mic": "Me",
    "speaker.monitor": "Others",

    # --- err.* ---
    "err.dotenv_load_fail": "Failed to load .env: {error}",
    "err.config_load_fail": "Failed to load config.yaml: {error}",
    "err.api_endpoint_missing": "Error: api_endpoint is not configured.",
    "err.api_endpoint_hint": "  Set it with: config set api_endpoint <URL>",
    "err.api_model_missing": "Error: api_model is not configured.",
    "err.api_model_hint": "  Set it with: config set api_model <model>",
    "err.api_key_missing": "Error: API key not found.",
    "err.api_key_hint": "  Add {env_var}=<your-api-key> to {dir}/.env",
    "err.file_not_found": "Error: File not found: {path}",
    "err.transcript_not_found": "Error: Transcript file not found: {path}",
    "err.transcript_empty": "Error: Transcript is empty.",
    "err.summary_failed": "Error: Summary generation failed (LLM call failed or insufficient response).",
}
