"""Shadow-clerk: i18n 文字列テーブル (ja)"""
# pylint: disable=duplicate-code  # 日英テーブルは同一プレースホルダ構造を持つため
from __future__ import annotations

STRINGS_JA: dict[str, str] = {
    # --- rec.* : clerk_daemon.py ターミナル出力 ---
    "rec.recording": "録音中... (Ctrl+C で停止)",
    "rec.output": "出力先: {path}",
    "rec.backend": "バックエンド: {name}",
    "rec.already_running": "エラー: clerk-daemon は既に稼働中です (PID: {pid})。`clerk-util stop` で停止してから起動してください。",
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
    "dash.tab_summary": "議事録",
    "dash.badge_ai": "AI分析あり",
    "dash.tab_ai": "AI分析",
    "dash.no_advice": "提案はまだありません。",
    "dash.no_analysis": "分析はまだありません。",
    "dash.start_analysis": "分析開始",
    "dash.start_analysis_title": "AI アシスタントを起動して会議スキルを実行します",
    "dash.stop_analysis": "分析停止",
    "dash.stop_analysis_title": "AI アシスタントを停止します",
    "dash.tab_logs": "ログ",
    "dash.tab_console": "AI コンソール",
    "dash.font_size": "文字サイズ(小/中/大)",
    "dash.font_s": "小",
    "dash.font_m": "中",
    "dash.font_l": "大",
    "dash.console_launch": "起動",
    "dash.console_launch_title": "初期プロンプトを送らずにアシスタントだけを起動します(/resume 用)",
    "dash.console_stop": "停止",
    "dash.console_stop_confirm": "AI アシスタントを停止しますか?",
    "dash.console_start_failed": "AI アシスタントの起動に失敗しました。",
    "dash.console_hint": "ここをクリックして入力すると、アシスタントにキーが送られます。",
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
    "dash.workdir_title": "この会議の起動ディレクトリ",
    "dash.workdir_pattern": "会議名パターン (正規表現)",
    "dash.workdir_pattern_hint": "会議名には表記ゆれがあります (Board_Meeting / Board MTG)。全部に当たるようパターンを緩めてください。",
    "dash.workdir_path": "起動ディレクトリ",
    "dash.workdir_default": "既定: {path}",
    "dash.workdir_file": "設定ファイル: {path}",
    "dash.workdir_delete": "ルールを削除",
    "dash.workdir_saved": "保存しました。",
    "dash.workdir_btn_title": "この会議の起動ディレクトリを設定します",
    "dash.summary_reload": "要約を再読み込み",
    "dash.summary_copy": "Markdown としてコピー",
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
    "dash.level_mic": "マイク入力レベル",
    "dash.level_monitor": "スピーカー入力レベル",
    "dash.level_noise": "定常ノイズのみ検出（デバイスを確認してください）",
    "dash.level_silent": "音が届いていません（デバイスの電源・接続を確認してください）",
    "dash.level_fallback": "指定デバイスが見つからないため自動で代替中",
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
        "文字サイズ (小/中/大)\n"
        "  transcript の文字サイズを切り替えます。\n\n"
        "用語集 / コマンド\n"
        "  用語集は文字起こしの表記ゆれを補正します。\n"
        "  コマンドは音声で起動する任意の操作を登録します。\n\n"
        "📅 Google Calendar\n"
        "  本日の予定と、会議の自動開始・終了の状態を表示します。\n\n"
        "【パネル操作】\n"
        "T|R ボタン: 中央ペインの表示を切替（押すたびに循環）\n"
        "  T|R（両方）→ T のみ → R のみ → AI → T|R\n"
        "  AI では AI コンソールだけが残ります。\n\n"
        "◀ ボタン（左右）: 会議一覧・要約ペインの開閉\n\n"
        "Logs ▼▲: ログパネルの表示・非表示を切替\n\n"
        "🎤 / 🔊: マイク・スピーカーの書き起こしミュート\n"
        "  ミュート中は音声キャプチャは継続しますが、\n"
        "  文字起こしはスキップされます。\n\n"
        "【音声コマンド】\n"
        "PTT キー（デフォルト: Menu）を押しながら発話\n"
        "  「会議開始」「会議終了」「翻訳開始」「翻訳停止」\n"
        "  「言語 日本語」「言語 英語」\n\n"
        "【AI コンソール】\n"
        "画面下の「AI コンソール」タブで、会議アシスタントが動きます。\n"
        "会議開始と同時に起こすなら auto_analyze を有効にします。\n"
        "起動ディレクトリは設定の「既定の起動ディレクトリ」、\n"
        "会議ごとの上書きは会議一覧の各行の ⚙ から指定できます。\n\n"
        "【スキルの配布】\n"
        "アシスタントは同梱スキル clerk-meeting-helper を使います。\n"
        "エージェント側のスキルディレクトリへ配る必要があります。\n"
        "  claude → ~/.claude/skills/     (Claude Code)\n"
        "  agents → ~/.agents/skills/     (Codex ほか)\n"
        "初回起動時のモーダルから配れます。コマンドからでも同じです:\n"
        "  clerk-util install-skill\n"
        "  clerk-util install-skill --target agents\n"
        "  clerk-util install-skill --target <パス>\n"
        "同梱スキルが更新されると、次にダッシュボードを開いたときに\n"
        "更新を促すモーダルが出ます。\n\n"
        "【設定】\n"
        "⚙ ボタンで設定モーダルを開きます。\n"
        "主な設定項目:\n"
        "  - UI言語 / 翻訳先言語 / Whisperモデル\n"
        "  - LLMプロバイダ / APIエンドポイント\n"
        "  - PTTキー / 中間文字起こし\n"
        "  - Google Calendar 連携 (予定から会議を自動で開始・終了)\n"
    ),

    "dash.audio_device_monitor": "モニター",

    # --- cfg.section.* : 設定セクション ---
    "cfg.section.general": "基本設定",
    "cfg.section.audio": "オーディオデバイス",
    "cfg.section.transcription": "文字起こし",
    "cfg.section.interim": "中間処理 (確定前)",
    "cfg.section.translation": "翻訳",
    "cfg.section.summary": "要約",
    "cfg.section.api": "LLM / API",
    "cfg.section.gcal": "Google Calendar 連携",
    "cfg.section.ai_console": "AI コンソール",

    # --- cfg.* : 設定モーダルフィールド ---
    "cfg.translate_language": "翻訳先言語",
    "cfg.auto_translate": "自動翻訳",
    "cfg.auto_summary": "自動Summary",
    "cfg.default_language": "デフォルト言語",
    "cfg.default_model": "Whisperモデル",
    "cfg.output_directory": "出力ディレクトリ",
    "cfg.output_directory_ph": "null=データディレクトリ",
    "cfg.mic_device": "マイク",
    "cfg.monitor_device": "スピーカー（モニター）",
    "cfg.device_auto": "自動（OS のデフォルト）",
    "cfg.device_cli_pinned": "CLI で固定中（--mic / --monitor）",
    "cfg.device_refresh": "一覧を更新",
    "cfg.device_refresh_title": "デバイスを再検出します。音が一瞬途切れます",
    "cfg.llm_provider": "LLMプロバイダ",
    "cfg.api_endpoint": "APIエンドポイント",
    "cfg.api_model": "APIモデル",
    "cfg.api_key_env": "APIキー環境変数",
    "cfg.api_disable_thinking": "思考を無効化（翻訳・中間翻訳）",
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
    "cfg.interim_translation_provider_claude_warn": "⚠ claude は1呼び出し 5〜10秒かかり interim 用途には遅すぎます。間に合わない更新はキューから捨てられ、確定翻訳とほぼ同時に出るだけになります。libretranslate / api を強く推奨。",
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
    "cfg.gcal_calendar_id": "カレンダーID",
    "cfg.gcal_buffer_minutes": "開始バッファ（分）",
    "cfg.gcal_end_buffer_minutes": "終了バッファ（分）",
    "cfg.auto_analyze": "会議開始と同時に分析を始める",
    "cfg.forbid_analyze": "分析しない話題",
    "cfg.forbid_analyze_hint": "ここに挙げた話題は AI 分析の対象外になります。空なら制限なし（どんな会話でも分析）。",
    "cfg.forbid_analyze_free": "その他（1行に1件）",
    "cfg.forbid_preset.evaluation": "個人の評価",
    "cfg.forbid_preset.compensation": "給与・処遇",
    "cfg.forbid_preset.private": "プライベートの内容（結婚、出産、健康など）",
    "cfg.forbid_preset.hiring": "採用・退職",
    "cfg.forbid_preset.legal": "法務・係争",
    "cfg.ai_assistant_command": "アシスタントのコマンド",
    "cfg.ai_assistant_args": "アシスタントの引数",
    "cfg.ai_assistant_args_ph": "--permission-mode acceptEdits",
    "cfg.ai_assistant_init_prompt": "初期プロンプト",
    "cfg.ai_assistant_init_prompt_ph": "/clerk-meeting-helper {transcript}",
    "cfg.ai_assistant_workdir": "既定の起動ディレクトリ",
    "cfg.gcal_setup_url": "https://github.com/edocode/shadow-clerk/blob/main/docs/google-calendar-setup.ja.md",
    "cfg.gcal_setup_link": "設定手順（Google Cloud の準備が必要です）",
    "cfg.skill_install": "スキルの配布",
    "welcome.title": "shadow-clerk へようこそ",
    "welcome.intro": "会議の音声を文字起こしし、要約と議事録を作ります。まず会議アシスタントのスキルを配ってください。",
    "welcome.skill": "スキルを配る",
    "welcome.skill_done": "配布しました",
    "welcome.skill_where": "配布先",
    "welcome.settings": "設定を開く",
    "welcome.recommend": "はじめに見ておくとよい設定",
    "welcome.rec_auto_analyze": "会議が始まったら AI アシスタントを自動で起こす",
    "welcome.rec_gcal": "Google Calendar の予定から会議の開始と終了を検出する",
    "welcome.rec_asr": "日本語の文字起こしモデル",
    "welcome.rec_workdir": "AI アシスタントの起動ディレクトリ",
    "welcome.close": "閉じる",
    "skill_update.title": "スキルが更新されています",
    "skill_update.body": "同梱 {bundled} に対して、配布済みが古いままです。",
    "skill_update.update": "更新する",
    "skill_update.later": "あとで",
    "cfg.path_missing_dir": "ディレクトリが見つかりません: {path}",
    "cfg.path_missing_file": "ファイルが見つかりません: {path}",
    "cfg.ai_assistant_workdir_warn": "アシスタントはスキルのシェルスクリプトを実行します。そのディレクトリの .claude/settings.json で許可しておかないと、会議中に承認プロンプトで止まります。",

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
    "err.summary_failed": "エラー: 要約の生成に失敗しました（LLM 呼び出し失敗または応答不足）。",
}
