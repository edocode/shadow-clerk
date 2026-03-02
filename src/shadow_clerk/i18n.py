"""Minimal i18n for shadow-clerk (ja/en)."""

import os

import yaml

from shadow_clerk import CONFIG_FILE

_current_lang = "ja"


def init(lang=None):
    """config.yaml から ui_language を読み、設定する。lang 引数で上書き可能。"""
    global _current_lang
    if lang:
        _current_lang = lang
        return
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f)
            if isinstance(cfg, dict) and cfg.get("ui_language"):
                _current_lang = cfg["ui_language"]
    except Exception:
        pass


def get_lang() -> str:
    return _current_lang


def t(key: str, **kwargs) -> str:
    """翻訳文字列を返す。フォールバック: current_lang → en → ja → key"""
    s = STRINGS.get(_current_lang, {}).get(key)
    if s is None:
        s = STRINGS.get("en", {}).get(key)
    if s is None:
        s = STRINGS.get("ja", {}).get(key)
    if s is None:
        return key
    if kwargs:
        return s.format(**kwargs)
    return s


def t_all() -> dict:
    """現在言語の全文字列 dict を返す（dashboard JS 注入用）"""
    merged = {}
    merged.update(STRINGS.get("ja", {}))
    merged.update(STRINGS.get("en", {}))
    merged.update(STRINGS.get(_current_lang, {}))
    return merged


STRINGS = {
    "ja": {
        # --- rec.* : clerk_daemon.py ターミナル出力 ---
        "rec.recording": "録音中... (Ctrl+C で停止)",
        "rec.output": "出力先: {path}",
        "rec.backend": "バックエンド: {name}",
        "rec.pipewire_devices": "\n=== PipeWire デバイス ===",
        "rec.pulseaudio_sources": "\n=== PulseAudio ソース ===",
        "rec.sounddevice_devices": "=== sounddevice デバイス ===",
        "rec.no_devices": "  (デバイスが見つかりません)",
        "rec.no_sources": "  (ソースが見つかりません)",
        "rec.pw_unavailable": "  (pw-record が利用できません)",
        "rec.pa_unavailable": "  (pactl が利用できません)",
        "rec.auto_detect_sd": "\n[自動検出] sounddevice monitor: device #{device}",
        "rec.auto_detect_backend": "[自動検出] {backend} monitor: {source}",
        "rec.meeting_start": "会議開始: {path}",
        "rec.meeting_end": "会議終了: {path}",
        "rec.model_changing": "モデル変更中: {model} ...",
        "rec.model_changed": "モデル変更完了: {model}",
        "rec.translate_start": "翻訳開始",
        "rec.translate_stop": "翻訳停止",
        "rec.custom_exec": "カスタムコマンド実行: {action}",
        "rec.voice_cmd_llm": "  音声コマンド (LLM): {text} → {command} (confidence={confidence})",
        "rec.voice_cmd_fail": "  コマンドを聞き取れませんでした: {text} (confidence={confidence})",
        "rec.auto_summary_start": "  自動要約生成中: {src} → {dst}",
        "rec.auto_summary_done": "  自動要約完了: {name}",
        "rec.auto_summary_fail": "  自動要約失敗: {error}",
        "rec.auto_summary_timeout": "  自動要約タイムアウト",
        "rec.ptt_on": "[PTT] コマンドモード ON ({vkey} pressed)",
        "rec.ptt_off": "[PTT] コマンドモード OFF ({vkey} released)",

        # --- dash.* : ダッシュボード UI ---
        "dash.meeting_start": "会議開始",
        "dash.meeting_end": "会議終了",
        "dash.translate_start": "翻訳開始",
        "dash.translate_stop": "翻訳停止",
        "dash.translate_regen": "翻訳を再生成",
        "dash.translate_regen_confirm": "翻訳を最初から再生成しますか？",
        "dash.translate_claude_hint": "llm_provider が claude の場合、翻訳は Claude Code から実行してください（/shadow-clerk translate <lang>）",
        "dash.realtime_translation": "リアルタイム翻訳",
        "dash.summary": "要約",
        "dash.view_summary": "要約閲覧",
        "dash.custom_cmd_placeholder": "カスタムコマンド",
        "dash.send": "送信",
        "dash.glossary": "用語集",
        "dash.settings": "設定",
        "dash.settings_title": "設定",
        "dash.glossary_title": "用語集 (glossary.txt)",
        "dash.summary_title": "要約",
        "dash.saved": "保存しました",
        "dash.cancel": "キャンセル",
        "dash.save": "保存",
        "dash.close": "閉じる",
        "dash.add_row": "+ 行追加",
        "dash.summary_started": "要約生成を開始しました。完了後に通知されます。",
        "dash.summary_prefix": "要約: ",
        "dash.no_summary": "(要約がありません)",
        "dash.alert_cmd_fail": "コマンドを聞き取れませんでした: {text}",
        "dash.alert_summary_done": "議事録を生成しました: {name}",
        "dash.transcript_not_found": "transcript が見つかりません",
        "dash.summary_generation_started": "要約生成を開始しました",
        "dash.detect_language": "検出言語",
        "dash.meeting_toggle_start": "会議開始",
        "dash.meeting_toggle_end": "会議終了",
        "dash.mute_mic": "マイクミュート",
        "dash.unmute_mic": "マイクミュート解除",
        "dash.mute_monitor": "スピーカーミュート",
        "dash.unmute_monitor": "スピーカーミュート解除",
        "dash.custom_commands": "コマンド",
        "dash.custom_commands_title": "カスタム音声コマンド",
        "dash.custom_cmd_pattern": "パターン（正規表現）",
        "dash.custom_cmd_action": "アクション（シェルコマンド）",
        "dash.custom_cmd_hint": "PTTキーを押しながら発話した内容がパターンにマッチすると、アクションが実行されます。",
        "dash.help": "ヘルプ",
        "dash.help_title": "ヘルプ",
        "dash.help_body": (
            "【ボタン操作】\n"
            "▶ 会議開始 / ■ 会議終了\n"
            "  会議セッションを開始・終了します。\n"
            "  開始すると専用の transcript ファイルが作成されます。\n\n"
            "▶ 翻訳開始 / ■ 翻訳停止\n"
            "  リアルタイム翻訳を開始・停止します。\n"
            "  llm_provider が api の場合のみ動作します。\n\n"
            "要約\n"
            "  現在の transcript から議事録を生成します。\n\n"
            "要約閲覧\n"
            "  生成済みの議事録を表示します。\n\n"
            "【パネル操作】\n"
            "T|R ボタン: Transcript/Translation の表示を切替\n"
            "  T|R → T のみ → R のみ → T|R（循環）\n\n"
            "Logs ▼▲: ログパネルの表示・非表示を切替\n\n"
            "🎤 / 🔊: マイク・スピーカーの書き起こしミュート\n"
            "  ミュート中は音声キャプチャは継続しますが、\n"
            "  文字起こしはスキップされます。\n\n"
            "【音声コマンド】\n"
            "PTT キー（デフォルト: Menu）を押しながら発話\n"
            "  「会議開始」「会議終了」「翻訳開始」「翻訳停止」\n"
            "  「言語 日本語」「言語 英語」\n\n"
            "【設定】\n"
            "⚙ ボタンで設定モーダルを開きます。\n"
            "主な設定項目:\n"
            "  - UI言語 / 翻訳先言語 / Whisperモデル\n"
            "  - LLMプロバイダ / APIエンドポイント\n"
            "  - PTTキー / 中間文字起こし\n"
        ),

        # --- cfg.section.* : 設定セクション ---
        "cfg.section.general": "基本設定",
        "cfg.section.transcription": "文字起こし",
        "cfg.section.translation": "翻訳",
        "cfg.section.summary": "要約",
        "cfg.section.api": "LLM / API",

        # --- cfg.* : 設定モーダルフィールド ---
        "cfg.translate_language": "翻訳先言語",
        "cfg.auto_translate": "自動翻訳",
        "cfg.auto_summary": "自動Summary",
        "cfg.default_language": "デフォルト言語",
        "cfg.default_model": "Whisperモデル",
        "cfg.output_directory": "出力ディレクトリ",
        "cfg.output_directory_ph": "null=データディレクトリ",
        "cfg.llm_provider": "LLMプロバイダ",
        "cfg.api_endpoint": "APIエンドポイント",
        "cfg.api_model": "APIモデル",
        "cfg.api_key_env": "APIキー環境変数",
        "cfg.initial_prompt": "初期プロンプト",
        "cfg.initial_prompt_ph": "Whisperヒント語彙",
        "cfg.voice_command_key": "PTTキー",
        "cfg.whisper_beam_size": "Beam Size",
        "cfg.whisper_compute_type": "計算精度",
        "cfg.whisper_device": "デバイス",
        "cfg.interim_transcription": "中間文字起こし",
        "cfg.interim_model": "中間モデル",
        "cfg.custom_commands": "カスタムコマンド",
        "cfg.ui_language": "UI言語",
        "cfg.translation_provider": "翻訳プロバイダ",
        "cfg.libretranslate_endpoint": "LibreTranslate URL",
        "cfg.libretranslate_api_key": "LibreTranslate APIキー",
        "cfg.libretranslate_spell_check": "誤字訂正(LibreTranslate用)",
        "cfg.spell_check_model": "誤字訂正モデル",
        "cfg.summary_source": "要約ソース",
        "cfg.use_kotoba_whisper": "Kotoba-Whisper (日本語)",
        "cfg.kotoba_whisper_model": "Kotoba-Whisper モデル",
        "cfg.interim_use_kotoba_whisper": "中間Kotoba-Whisper (日本語)",

        # --- llm.* : LLM プロンプト ---
        "llm.translate_system": (
            "あなたは翻訳アシスタントです。以下のルールに従ってテキストを{lang}に翻訳してください:\n"
            "\n"
            "1. 各行は「番号: テキスト」形式で与えられます。同じ「番号: 翻訳結果」形式で返してください。\n"
            "2. 音声認識の書き起こしテキストです。明らかな誤認識は文脈から推測して補正してから翻訳してください。\n"
            "3. 翻訳先言語（{lang}）と同じ言語で書かれている行は翻訳不要ですが、音声認識の誤認識・typo があれば修正して出力してください。\n"
            "4. 番号とコロンの後の翻訳テキストのみを出力してください。余計な説明は不要です。"
        ),
        "llm.summary_full_system": (
            "あなたは議事録作成アシスタントです。指定されたテンプレートに厳密に従って議事録を出力してください。\n"
            "テンプレート以外の形式で出力しないでください。"
        ),
        "llm.summary_full_user": (
            "以下の transcript（音声書き起こし）から議事録を作成してください。\n"
            "\n"
            "【出力テンプレート（この構造に厳密に従うこと）】\n"
            "{summary_format}\n"
            "\n"
            "【注意事項】\n"
            "- 日本語で作成してください\n"
            "- transcript の各行は [YYYY-MM-DD HH:MM:SS] [スピーカー] テキスト 形式です\n"
            "- 音声認識による誤字・誤変換を文脈から推測して正しい表記に修正してください\n"
            "- 固有名詞や専門用語は前後の文脈から最も適切な表記を推定してください\n"
            "\n"
            "【transcript】\n"
            "{transcript}"
        ),
        "llm.summary_update_system": (
            "あなたは議事録作成アシスタントです。指定されたテンプレートに厳密に従って議事録を出力してください。\n"
            "テンプレート以外の形式で出力しないでください。"
        ),
        "llm.summary_update_user": (
            "既存の議事録を新しい transcript の内容で更新してください。\n"
            "\n"
            "【出力テンプレート（この構造に厳密に従うこと）】\n"
            "{summary_format}\n"
            "\n"
            "【注意事項】\n"
            "- 日本語で作成してください\n"
            "- 既存の議事録の内容は維持しつつ、新しい情報を追加・統合してください\n"
            "- transcript の各行は [YYYY-MM-DD HH:MM:SS] [スピーカー] テキスト 形式です\n"
            "- 音声認識による誤字・誤変換を文脈から推測して正しい表記に修正してください\n"
            "- 固有名詞や専門用語は前後の文脈から最も適切な表記を推定してください\n"
            "\n"
            "## 既存の議事録\n"
            "{existing}\n"
            "\n"
            "## 新しい transcript（差分）\n"
            "{transcript}"
        ),
        "llm.summary_update_none": "(なし — 新規作成してください)",
        "llm.summary_format": (
            "以下のテンプレートの見出し構造・書式を厳密に守って出力してください。\n"
            "見出しの追加・変更・省略はしないでください。内容がない場合は「特になし」と記載してください。\n"
            "\n"
            "```\n"
            "# 議事録\n"
            "\n"
            "- **日時**: YYYY-MM-DD HH:MM〜HH:MM（transcript のタイムスタンプから推定）\n"
            "- **参加者**: （判別できれば記載、不明なら省略）\n"
            "\n"
            "## 要約\n"
            "（会議全体の要約を3〜5文で）\n"
            "\n"
            "## 主な議題と決定事項\n"
            "- **議題1**: 内容の要約\n"
            "  - 決定事項: ...\n"
            "- **議題2**: ...\n"
            "\n"
            "## アクションアイテム\n"
            "- [ ] 担当者: タスク内容（期限があれば記載）\n"
            "\n"
            "## 詳細メモ\n"
            "（重要な発言や補足情報）\n"
            "```"
        ),
        "llm.query_system": "あなたは親切なアシスタントです。簡潔に回答してください。",
        "llm.match_command_system": (
            "あなたは音声コマンド認識アシスタントです。\n"
            "ユーザーの音声認識テキストを受け取り、最も近いコマンドを推測してください。\n"
            "\n"
            "利用可能なコマンド一覧:\n"
            "{commands}\n"
            "\n"
            "ルール:\n"
            "1. 音声認識の誤認識を考慮し、意味的に最も近いコマンドを選んでください。\n"
            '2. 結果を JSON で返してください（JSON のみ）:\n'
            '   {{"command": "マッチしたコマンド", "confidence": 0-100の整数}}\n'
            "3. confidence は確信度です。完全一致なら100、やや曖昧なら60-80、関係なさそうなら0-30としてください。"
        ),

        # --- vcmd.* : 音声コマンド説明 ---
        "vcmd.start_meeting": "会議を開始する (start meeting)",
        "vcmd.end_meeting": "会議を終了する (end meeting)",
        "vcmd.translate_start": "翻訳を開始する (start translation)",
        "vcmd.translate_stop": "翻訳を停止する (stop translation)",
        "vcmd.set_language_ja": "言語を日本語に設定する (set language Japanese)",
        "vcmd.set_language_en": "言語を英語に設定する (set language English)",
        "vcmd.unset_language": "言語設定を自動検出にする (unset language)",

        # --- speaker.* : スピーカーラベル表示用 ---
        "speaker.mic": "自分",
        "speaker.monitor": "相手",

        # --- err.* : エラーメッセージ ---
        "err.dotenv_load_fail": ".env の読み込みに失敗: {error}",
        "err.config_load_fail": "config.yaml の読み込みに失敗: {error}",
        "err.api_endpoint_missing": "エラー: api_endpoint が設定されていません。",
        "err.api_endpoint_hint": "  config set api_endpoint <URL> で設定してください。",
        "err.api_model_missing": "エラー: api_model が設定されていません。",
        "err.api_model_hint": "  config set api_model <model> で設定してください。",
        "err.api_key_missing": "エラー: API キーが見つかりません。",
        "err.api_key_hint": "  {dir}/.env に {env_var}=<your-api-key> を記載してください。",
        "err.file_not_found": "エラー: ファイルが見つかりません: {path}",
        "err.transcript_not_found": "エラー: transcript ファイルが見つかりません: {path}",
        "err.transcript_empty": "エラー: transcript が空です。",
    },
    "en": {
        # --- rec.* ---
        "rec.recording": "Recording... (Ctrl+C to stop)",
        "rec.output": "Output: {path}",
        "rec.backend": "Backend: {name}",
        "rec.pipewire_devices": "\n=== PipeWire Devices ===",
        "rec.pulseaudio_sources": "\n=== PulseAudio Sources ===",
        "rec.sounddevice_devices": "=== sounddevice Devices ===",
        "rec.no_devices": "  (No devices found)",
        "rec.no_sources": "  (No sources found)",
        "rec.pw_unavailable": "  (pw-record is not available)",
        "rec.pa_unavailable": "  (pactl is not available)",
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
        "dash.custom_commands": "Commands",
        "dash.custom_commands_title": "Custom Voice Commands",
        "dash.custom_cmd_pattern": "Pattern (regex)",
        "dash.custom_cmd_action": "Action (shell command)",
        "dash.custom_cmd_hint": "When you speak while holding the PTT key and the text matches a pattern, the action is executed.",
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

        # --- cfg.section.* ---
        "cfg.section.general": "General",
        "cfg.section.transcription": "Transcription",
        "cfg.section.translation": "Translation",
        "cfg.section.summary": "Summary",
        "cfg.section.api": "LLM / API",

        # --- cfg.* ---
        "cfg.translate_language": "Translation Language",
        "cfg.auto_translate": "Auto Translate",
        "cfg.auto_summary": "Auto Summary",
        "cfg.default_language": "Default Language",
        "cfg.default_model": "Whisper Model",
        "cfg.output_directory": "Output Directory",
        "cfg.output_directory_ph": "null=data directory",
        "cfg.llm_provider": "LLM Provider",
        "cfg.api_endpoint": "API Endpoint",
        "cfg.api_model": "API Model",
        "cfg.api_key_env": "API Key Env Var",
        "cfg.initial_prompt": "Initial Prompt",
        "cfg.initial_prompt_ph": "Whisper hint words",
        "cfg.voice_command_key": "PTT Key",
        "cfg.whisper_beam_size": "Beam Size",
        "cfg.whisper_compute_type": "Compute Type",
        "cfg.whisper_device": "Device",
        "cfg.interim_transcription": "Interim Transcription",
        "cfg.interim_model": "Interim Model",
        "cfg.custom_commands": "Custom Commands",
        "cfg.ui_language": "UI Language",
        "cfg.translation_provider": "Translation Provider",
        "cfg.libretranslate_endpoint": "LibreTranslate URL",
        "cfg.libretranslate_api_key": "LibreTranslate API Key",
        "cfg.libretranslate_spell_check": "Spell Check (LibreTranslate)",
        "cfg.spell_check_model": "Spell Check Model",
        "cfg.summary_source": "Summary Source",
        "cfg.use_kotoba_whisper": "Kotoba-Whisper (Japanese)",
        "cfg.kotoba_whisper_model": "Kotoba-Whisper Model",
        "cfg.interim_use_kotoba_whisper": "Interim Kotoba-Whisper (Japanese)",

        # --- llm.* ---
        "llm.translate_system": (
            "You are a translation assistant. Follow these rules to translate text into {lang}:\n"
            "\n"
            "1. Each line is given in 'number: text' format. Return results in the same 'number: translated text' format.\n"
            "2. This is speech recognition transcript text. Correct obvious misrecognitions from context before translating.\n"
            "3. Lines already in the target language ({lang}) do not need translation, but fix any speech recognition errors or typos.\n"
            "4. Output only the number and translated text after the colon. No extra explanations."
        ),
        "llm.summary_full_system": (
            "You are a meeting minutes assistant. Strictly follow the given template to output meeting minutes.\n"
            "Do not output in any format other than the template."
        ),
        "llm.summary_full_user": (
            "Create meeting minutes from the following transcript (speech-to-text).\n"
            "\n"
            "[OUTPUT TEMPLATE - follow this structure exactly]\n"
            "{summary_format}\n"
            "\n"
            "[RULES]\n"
            "- Write in English\n"
            "- Each transcript line is in [YYYY-MM-DD HH:MM:SS] [Speaker] Text format\n"
            "- Fix speech recognition errors by inferring correct words from context\n"
            "- Infer the most appropriate spelling for proper nouns and technical terms\n"
            "\n"
            "[TRANSCRIPT]\n"
            "{transcript}"
        ),
        "llm.summary_update_system": (
            "You are a meeting minutes assistant. Strictly follow the given template to output meeting minutes.\n"
            "Do not output in any format other than the template."
        ),
        "llm.summary_update_user": (
            "Update the existing meeting minutes with the new transcript content.\n"
            "\n"
            "[OUTPUT TEMPLATE - follow this structure exactly]\n"
            "{summary_format}\n"
            "\n"
            "[RULES]\n"
            "- Write in English\n"
            "- Maintain existing minutes content while adding/integrating new information\n"
            "- Each transcript line is in [YYYY-MM-DD HH:MM:SS] [Speaker] Text format\n"
            "- Fix speech recognition errors by inferring correct words from context\n"
            "- Infer the most appropriate spelling for proper nouns and technical terms\n"
            "\n"
            "## Existing Meeting Minutes\n"
            "{existing}\n"
            "\n"
            "## New Transcript (diff)\n"
            "{transcript}"
        ),
        "llm.summary_update_none": "(None — please create new minutes)",
        "llm.summary_format": (
            "Follow this template structure exactly. Do not add, change, or omit any headings.\n"
            "If a section has no content, write \"N/A\".\n"
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
    },
}
