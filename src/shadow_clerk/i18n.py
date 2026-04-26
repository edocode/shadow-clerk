"""Minimal i18n for shadow-clerk (ja/en)."""

import os

import yaml

from shadow_clerk import CONFIG_FILE

_current_lang = "ja"


def init(lang: str | None = None) -> None:
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


def nt(key: str, **kwargs) -> str:
    """常に英語文字列を返す（LLMプロンプト用・locale非依存）。フォールバック: en → ja → key"""
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
        "rec.wasapi_loopback_mics": "\n=== WASAPI ループバックマイク ===",
        "rec.wasapi_soundcard_unavailable": "  (soundcard が利用できません)",
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
        "dash.translating": "翻訳中...",
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
        "dash.summary_regen": "要約を再生成",
        "dash.summary_regen_confirm": "要約を最初から再生成しますか？",
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
        "dash.mic_unavailable": "マイク利用不可",
        "dash.monitor_unavailable": "スピーカー利用不可",
        "dash.ts_mic_title": "マイクのキャプチャに失敗しました",
        "dash.ts_monitor_title": "スピーカー（モニター）のキャプチャに失敗しました",
        "dash.ts_possible_causes": "考えられる原因:",
        "dash.ts_mic_cause1": "マイクが接続されていない",
        "dash.ts_monitor_cause1": "モニターデバイス（ループバック）が見つからない",
        "dash.ts_cause_service": "オーディオサービスがクラッシュしている",
        "dash.ts_fix_steps": "対処手順:",
        "dash.ts_restart_service": "オーディオサービスを再起動:",
        "dash.ts_list_devices": "利用可能なデバイスを確認:",
        "dash.ts_restart_clerk": "デバイス ID を指定して clerk-daemon を起動し直す:<br><code>clerk-daemon {opt} DEVICE_ID</code>",
        "dash.custom_commands": "コマンド",
        "dash.custom_commands_title": "カスタム音声コマンド",
        "dash.custom_cmd_pattern": "パターン（正規表現）",
        "dash.custom_cmd_action": "アクション（シェルコマンド）",
        "dash.custom_cmd_hint": "PTTキーを押しながら発話した内容がパターンにマッチすると、アクションが実行されます。",
        "dash.delete_line_title": "この行を削除しますか？",
        "dash.delete_line_transcript": "文字起こし",
        "dash.delete_line_translation": "翻訳",
        "dash.delete": "削除",
        "dash.delete_error": "削除に失敗しました",
        "dash.bulk_delete_title": "選択した行を削除しますか？",
        "dash.bulk_delete_selected": "選択した行を削除",
        "dash.bulk_delete_range": "範囲内のすべてを削除",
        "dash.delete_file_title": "このファイルを削除しますか？",
        "dash.delete_file_desc": "以下のファイルが削除されます:",
        "dash.extract_meeting_title": "会議として切り出す",
        "dash.extract_meeting_new": "新規会議とする",
        "dash.extract_meeting_adhoc": "ad-hoc（名前なし）",
        "dash.extract_meeting_use_group": "既存の会議名に紐付ける",
        "dash.extract_meeting_new_name": "新しい会議名を作る",
        "dash.extract_meeting_name_ph": "会議名を入力",
        "dash.extract_meeting_existing": "既存の会議ファイルに追加",
        "dash.extract_meeting_create": "作成",
        "dash.extract_meeting_range": "範囲: {start} 〜 {end}",
        "dash.extract_meeting_lines": "{count}行が対象です",
        "dash.extract_meeting_success": "会議ファイルを作成しました: {name}",
        "dash.extract_meeting_error": "会議切り出しに失敗しました",
        "dash.extract_meeting_no_lines": "選択範囲に行がありません",
        "dash.delete_file_merge": "日次ファイルに戻す（会議行を日次transcriptにマージして削除）",
        "dash.delete_file_delete_only": "完全に削除する",
        "dash.merge_to_daily_error": "日次ファイルへのマージに失敗しました",
        "dash.extract_split_all": "全体を",
        "dash.extract_split_range": "選択範囲を",
        "dash.extract_split_min_suffix": "分以上の沈黙で開始候補・1分以内ギャップが3分継続で確定・3分沈黙で終了",
        "dash.extract_extract_range": "選択範囲を切り出す",
        "dash.extract_split_success": "{count}件の会議ファイルに分割しました",
        "dash.extract_split_error": "沈黙分割に失敗しました",
        "dash.extract_split_no_segments": "指定した沈黙期間での分割点が見つかりませんでした",
        "dash.selected_count": "{count}件選択",
        "dash.meetings": "会議",
        "dash.meetings_back": "一覧へ",
        "dash.meetings_empty": "会議記録はありません",
        "dash.sort_abc": "ABC順",
        "dash.sort_newest": "新しい順",
        "dash.sort_title": "並び順を切り替え",
        "dash.tab_dates": "日付",
        "dash.tab_meetings": "会議",
        "dash.tab_search": "検索",
        "dash.dates_empty": "日次記録はありません",
        "dash.search_year": "年",
        "dash.search_month": "月",
        "dash.search_day": "日",
        "dash.search_hour": "時",
        "dash.search_query": "テキスト",
        "dash.search_type_all": "全て",
        "dash.search_type_transcript": "文字起こし",
        "dash.search_type_translation": "翻訳",
        "dash.search_type_summary": "要約",
        "dash.search_btn": "検索",
        "dash.search_empty": "該当なし",
        "dash.rename_group_title": "会議名を変更",
        "dash.rename_group_new": "新しい会議名",
        "dash.rename_group_preview": "{n} 件のファイルがリネームされます",
        "dash.rename_meeting_title": "会議に紐付ける",
        "dash.rename_meeting_existing": "既存の会議から選ぶ",
        "dash.rename_meeting_new": "新しい会議名",
        "dash.rename_meeting_placeholder": "会議名を入力（空欄で ad-hoc）",
        "dash.rename_meeting_apply": "適用",
        "dash.gcal_events": "Google Calendar",
        "dash.gcal_events_title": "Google Calendar 予定",
        "dash.gcal_disabled": "Google Calendar 連携は無効です。",
        "dash.gcal_no_events": "本日の予定はありません。",
        "dash.attendees": "参加予定者",
        "dash.attendees_empty": "（参加予定者の情報はありません）",
        "dash.attendees_note": "※ 招待情報に基づくリストです。実際の出席者と異なる場合があります。",
        "dash.loading": "読み込み中...",
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
        "cfg.section.interim": "中間処理 (確定前)",
        "cfg.section.translation": "翻訳",
        "cfg.section.summary": "要約",
        "cfg.section.api": "LLM / API",
        "cfg.section.gcal": "Google Calendar 連携",

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
        "cfg.wake_word": "ウェイクワード",
        "cfg.wake_word_ph": "音声コマンドのトリガーワード",
        "cfg.whisper_beam_size": "Beam Size",
        "cfg.whisper_compute_type": "計算精度",
        "cfg.whisper_device": "デバイス",
        "cfg.interim_transcription": "中間文字起こし",
        "cfg.interim_translation": "中間翻訳",
        "cfg.interim_translation_provider": "中間翻訳プロバイダ (空=自動)",
        "cfg.interim_model": "中間モデル",
        "cfg.custom_commands": "カスタムコマンド",
        "cfg.ui_language": "UI言語",
        "cfg.translation_provider": "翻訳プロバイダ",
        "cfg.libretranslate_endpoint": "LibreTranslate URL",
        "cfg.libretranslate_api_key": "LibreTranslate APIキー",
        "cfg.libretranslate_spell_check": "誤字訂正(LibreTranslate用)",
        "cfg.spell_check_model": "誤字訂正モデル",
        "cfg.summary_source": "要約ソース",
        "cfg.summary_language": "要約の言語",
        "cfg.translation_hiragana_step": "平仮名思考ステップ",
        "cfg.summary_hiragana_step": "平仮名思考ステップ",
        "cfg.summary_length": "要約の長さ",
        "cfg.japanese_asr_model": "日本語ASRモデル",
        "cfg.kotoba_whisper_model": "Kotoba-Whisper モデル",
        "cfg.interim_japanese_asr_model": "中間 日本語ASRモデル",
        "cfg.gcal_integration": "Google Calendar 連携を有効にする",
        "cfg.gcal_credentials_file": "credentials.json パス",
        "cfg.gcal_credentials_file_ph": "~/.local/share/shadow-clerk/credentials.json",
        "cfg.gcal_calendar_id": "カレンダーID",
        "cfg.gcal_buffer_minutes": "開始バッファ（分）",
        "cfg.gcal_end_buffer_minutes": "終了バッファ（分）",

        # --- llm.* : LLM プロンプト ---
        "llm.translate_system": (
            "あなたは翻訳アシスタントです。以下のルールに従ってテキストを{lang}に翻訳してください:\n"
            "\n"
            "1. 各行は「番号: テキスト」形式で与えられます。同じ「番号: 翻訳結果」形式で返してください。\n"
            "2. 音声認識の書き起こしテキストです。明らかな誤認識は文脈から推測して補正してから翻訳してください。\n"
            "3. 用語集にreadingが記載されている場合、音声認識結果にそのreadingと類似する語句があれば、対応する正しい用語に修正してください。上から順に優先的に照合してください。\n"
            "4. 番号とコロンの後の翻訳テキストのみを出力してください。余計な説明は不要です。\n"
            "{hiragana_step}"
        ),
        "llm.correct_system": (
            "あなたは音声認識テキストの誤変換修正アシスタントです。\n"
            "入力テキストは日本語の音声認識結果であり、多数の漢字誤変換を含みます。\n"
            "以下のルールに従って誤変換を修正してください:\n"
            "\n"
            "1. 各行は「番号: テキスト」形式で与えられます。同じ「番号: 修正後テキスト」形式で返してください。\n"
            "2. 音声認識は同音異義語を頻繁に誤変換します。各単語の「読み」を考え、文脈に合った正しい漢字・表記に修正してください。\n"
            "3. 用語集のreadingマッピングに一致する読みを持つ語句は、必ず用語集の正しい表記に修正してください。上から順に優先的に照合してください。\n"
            "4. 用語集にない語句でも、文脈から明らかに誤変換と判断できる場合は修正してください。\n"
            "5. 番号とコロンの後の修正済みテキストのみを出力してください。余計な説明は不要です。\n"
            "6. 修正が不要な行もそのまま出力してください（省略しないこと）。"
        ),
        "llm.summary_full_system": (
            "あなたは議事録作成アシスタントです。指定されたテンプレートに厳密に従って議事録を出力してください。\n"
            "テンプレート以外の形式で出力しないでください。{length_instruction}"
        ),
        "llm.summary_full_user": (
            "以下の transcript（音声書き起こし）から議事録を作成してください。\n"
            "\n"
            "【出力テンプレート（この構造に厳密に従うこと）】\n"
            "{summary_format}\n"
            "\n"
            "【注意事項】\n"
            "- {summary_language}で作成してください\n"
            "- transcript の各行は [YYYY-MM-DD HH:MM:SS] [スピーカー] テキスト 形式です\n"
            "- 音声認識による誤字・誤変換を文脈から推測して正しい表記に修正してください\n"
            "- 固有名詞や専門用語は前後の文脈から最も適切な表記を推定してください\n"
            "- 用語集にreadingが記載されている場合、音声認識結果にそのreadingと類似する語句があれば、対応する正しい用語に修正してください。上から順に優先的に照合してください\n"
            "- タスクやTODOになりそうな内容は、短い議論や補足的な話題であっても漏らさず記載してください\n"
            "- 発言者名を無理に推測しないでください。transcript のスピーカーは「自分」と「相手」の2者しか区別できないため、具体的な個人名での発言の帰属は不正確になります。引用は「〜という意見があった」等の形式にしてください\n"
            "{hiragana_step}"
            "{length_instruction}"
            "{attendees_block}"
            "\n"
            "【transcript】\n"
            "{transcript}"
        ),
        "llm.summary_update_system": (
            "あなたは議事録作成アシスタントです。指定されたテンプレートに厳密に従って議事録を出力してください。\n"
            "テンプレート以外の形式で出力しないでください。{length_instruction}"
        ),
        "llm.summary_update_user": (
            "既存の議事録を新しい transcript の内容で更新してください。\n"
            "\n"
            "【出力テンプレート（この構造に厳密に従うこと）】\n"
            "{summary_format}\n"
            "\n"
            "【注意事項】\n"
            "- {summary_language}で作成してください\n"
            "- 既存の議事録の内容は維持しつつ、新しい情報を追加・統合してください\n"
            "- transcript の各行は [YYYY-MM-DD HH:MM:SS] [スピーカー] テキスト 形式です\n"
            "- 音声認識による誤字・誤変換を文脈から推測して正しい表記に修正してください\n"
            "- 固有名詞や専門用語は前後の文脈から最も適切な表記を推定してください\n"
            "- 用語集にreadingが記載されている場合、音声認識結果にそのreadingと類似する語句があれば、対応する正しい用語に修正してください。上から順に優先的に照合してください\n"
            "- タスクやTODOになりそうな内容は、短い議論や補足的な話題であっても漏らさず記載してください\n"
            "- 発言者名を無理に推測しないでください。transcript のスピーカーは「自分」と「相手」の2者しか区別できないため、具体的な個人名での発言の帰属は不正確になります。引用は「〜という意見があった」等の形式にしてください\n"
            "{hiragana_step}"
            "{length_instruction}"
            "{attendees_block}"
            "\n"
            "## 既存の議事録\n"
            "{existing}\n"
            "\n"
            "## 新しい transcript（差分）\n"
            "{transcript}"
        ),
        "llm.summary_hiragana_step": (
            "\n"
            "【重要】議事録を作成する前に以下の思考手順を内部で実行してください（出力には含めないこと）:\n"
            "  a. transcript の各行の日本語テキストの漢字をすべて平仮名（読み）に変換して意味を再解釈する\n"
            "  b. 平仮名にした読みを用語集の reading と照合し、音声認識の誤変換を特定する\n"
            "  c. 文脈に基づいて正しい漢字・用語に修正してから議事録を作成する\n"
            "  平仮名や中間ステップは絶対に出力しないでください。議事録のみ出力してください。\n"
        ),
        "llm.translation_hiragana_step": (
            "\n"
            "【重要】翻訳前に以下の思考手順を内部で実行してください（出力には含めないこと）:\n"
            "  a. 各行の日本語テキストの漢字をすべて平仮名（読み）に変換して意味を再解釈する\n"
            "  b. 平仮名にした読みを用語集の reading マッピングと照合し、音声認識の誤変換を特定する\n"
            "     例: 「習性」→ ひらがな「しゅうせい」→ glossaryで「しゅうせい→修正」を発見 → 文脈的に「修正」が正しい\n"
            "  c. 文脈に基づいて正しい漢字・用語に修正する\n"
            "  d. 修正後のテキストを翻訳先言語（{lang}）に翻訳する\n"
            "  出力は最終的な翻訳結果（「番号: 翻訳テキスト」形式）のみにしてください。\n"
            "  平仮名や中間ステップは絶対に出力しないでください。"
        ),
        "llm.summary_update_none": "(なし — 新規作成してください)",
        "llm.summary_attendees_block": (
            "\n【参加予定者（Google Calendar より）】\n"
            "{attendees}\n"
            "※ 参加予定者リストは招待情報に基づくため、実際の出席者と異なる場合があります。"
            "議事録内で発言者名を明示する必要がある場合でも、"
            "誰が実際に発言したかは transcript だけでは判別できないことを踏まえ、"
            "断定的な帰属は避けてください。"
        ),
        "llm.summary_length_half": "\n【出力量】A4半枚（400字）以上でまとめてください。重要な内容があればそれ以上長くなっても構いません。",
        "llm.summary_length_1page": "\n【出力量】A41枚（800字）以上でまとめてください。重要な内容があればそれ以上長くなっても構いません。",
        "llm.summary_length_2pages": "\n【出力量】A42枚（1600字）以上で詳細にまとめてください。各議題の議論内容を具体的に記述してください。重要な内容があればそれ以上長くなっても構いません。",
        "llm.summary_length_3pages": (
            "\n【出力量】A43枚（2400字）以上で出力してください。"
            "各議題について背景・議論の経緯・結論を丁寧に記述し、「詳細メモ」セクションでは重要な発言を具体的に記載してください。"
            "重要な内容を端折らず、必要に応じてさらに長くなっても構いません。"
        ),
        "llm.summary_length_4pages": (
            "\n【出力量】A44枚（3200字）以上で出力してください。"
            "各議題について背景・議論の経緯・各参加者の意見・結論を漏れなく記述してください。"
            "「詳細メモ」セクションでは重要な発言を具体的に引用し、議論の流れが再現できるレベルで記載してください。"
            "重要な内容を端折らず、必要に応じてさらに長くなっても構いません。"
        ),
        "llm.summary_length_5pages": (
            "\n【出力量】A45枚（4000字）以上で出力してください。"
            "各議題について背景・議論の経緯・各参加者の意見・結論・アクションアイテムを漏れなく記述してください。"
            "「詳細メモ」セクションでは重要な発言を具体的に引用し、議論の流れが再現できるレベルで詳細に記載してください。"
            "要約ではなく詳細な議事録として、会議に参加していない人が読んでも議論の全体像を把握できる分量で出力してください。"
        ),
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

        # --- cfg.section.* ---
        "cfg.section.general": "General",
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
        "cfg.llm_provider": "LLM Provider",
        "cfg.api_endpoint": "API Endpoint",
        "cfg.api_model": "API Model",
        "cfg.api_key_env": "API Key Env Var",
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
    },
}
