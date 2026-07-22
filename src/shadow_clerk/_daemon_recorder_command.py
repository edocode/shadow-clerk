"""Shadow-clerk daemon: レコーダーコマンド・キーリスナー ミックスイン"""
# pylint: disable=duplicate-code  # 各モジュールで必要な optional import ブロックは共通形だが抽象化不可
from __future__ import annotations
from typing import Any
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time

from shadow_clerk.i18n import t
from shadow_clerk._transcript_name import TranscriptName
from shadow_clerk.domain import MeetingSession
from shadow_clerk._daemon_constants import (
    SESSION_FILE,
    VOICE_CMD_PREFIX, VOICE_CMD_SUFFIX, VOICE_COMMANDS,
    build_wake_word_patterns,
    pynput_keyboard, _HAS_PYNPUT, evdev, _ecodes, _HAS_EVDEV,
)
from shadow_clerk._daemon_config import load_config, get_translation_provider, _builtin_command_descs

logger = logging.getLogger("shadow-clerk")


def _sanitize_meeting_name(name: str) -> str:
    """会議名をファイル名に使用できる形式にエスケープする"""
    # ファイル名に使えない文字を除去
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', '', name)
    # @ は区切り文字と衝突するため除去
    name = name.replace('@', '')
    # 連続空白を _ に置換、前後トリム
    name = re.sub(r'\s+', '_', name.strip())
    # 末尾の _ を除去、長さ制限
    return name[:50].rstrip('_')


class _RecorderCommandMixin:
    """コマンド処理・キーリスナー ミックスイン"""

    def _extract_command_body(self, text: str) -> str | None:
        """プレフィックス/サフィックスのウェイクワードを検出し、コマンド本文を返す。未検出なら None。"""
        prefix = getattr(self, "_wake_prefix", VOICE_CMD_PREFIX)
        suffix = getattr(self, "_wake_suffix", VOICE_CMD_SUFFIX)
        if prefix.match(text):
            return prefix.sub("", text).strip()
        elif suffix.search(text):
            return suffix.sub("", text).strip()
        return None

    def _match_command_body(self, text: str) -> str | None:
        """プレフィックス/サフィックスなしでコマンドマッチ（Push-to-Talk 用）"""
        body = text.strip()
        if not body:
            return None
        # 1. 組み込みコマンド（優先）
        for pattern, command in VOICE_COMMANDS:
            if pattern.search(body):
                return command
        # 2. カスタムコマンド
        for pattern, action in self._custom_commands:
            if pattern.search(body):
                return f"custom_exec {action}"
        # 3. LLM フォールバック（API 設定済み or claude プロバイダの場合）
        config = load_config()
        if body and (config.get("api_endpoint") or config.get("llm_provider") == "claude"):
            return f"llm_query {body}"
        return None

    def _get_command_list(self) -> list[str]:
        """ビルトイン + カスタムコマンドのパターン説明リストを生成"""
        commands = [c["description"] for c in _builtin_command_descs()]
        for pattern, action in self._custom_commands:
            commands.append(pattern.pattern)
        return commands

    def _spell_and_match(self, text: str, timestamp: str = "", display_speaker: str = "") -> None:
        """spell-check で誤字訂正してからパターンマッチを実行する"""
        corrected = text
        try:
            result = subprocess.run(
                [sys.executable, "-m", "shadow_clerk.llm_client", "spell-check"],
                input=text, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                corrected = result.stdout.strip()
                if corrected != text:
                    logger.info("spell-check 訂正: '%s' → '%s'", text, corrected)
        except subprocess.TimeoutExpired:
            logger.warning("spell-check タイムアウト")
        except Exception as e:
            logger.warning("spell-check エラー: %s", e)

        voice_cmd = self._match_command_body(corrected)
        if voice_cmd:
            logger.info("音声コマンド検出 (PTT+spell): %s → %s", corrected, voice_cmd)
            if voice_cmd.startswith("custom_exec "):
                logger.info("[%s] [%s] %s", timestamp, display_speaker, text)
            self._execute_command(voice_cmd)
        else:
            logger.info("音声コマンド不一致 (PTT+spell): '%s' (訂正後: '%s')", text, corrected)
            print(t("rec.voice_cmd_fail", text=text, confidence=0))

    def _llm_match_and_execute(self, text: str) -> None:
        """LLM にコマンドマッチングを依頼し、confidence が高ければ実行する"""
        commands = self._get_command_list()
        payload = json.dumps({"text": text, "commands": commands}, ensure_ascii=False)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "shadow_clerk.llm_client", "match-command"],
                input=payload, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=30,
            )
            if result.returncode != 0:
                logger.warning("match-command 失敗: %s", result.stderr.strip())
                return
            response = json.loads(result.stdout.strip())
        except subprocess.TimeoutExpired:
            logger.warning("match-command タイムアウト")
            return
        except (json.JSONDecodeError, Exception) as e:
            logger.warning("match-command レスポンスエラー: %s", e)
            return

        command = response.get("command", "")
        confidence = response.get("confidence", 0)

        if confidence >= 80 and command:
            logger.info("LLM コマンドマッチ: '%s' → %s (confidence=%d)", text, command, confidence)
            print(t("rec.voice_cmd_llm", text=text.strip(), command=command, confidence=confidence))
            self._execute_command(command)
        else:
            logger.info("LLM コマンドマッチ低信頼度: '%s' → %s (confidence=%d)", text, command, confidence)
            # コマンドにマッチしなかった場合、LLM クエリにフォールバック
            config = load_config()
            if text.strip() and (config.get("api_endpoint") or config.get("llm_provider") == "claude"):
                logger.info("LLM クエリにフォールバック: %s", text.strip())
                self._execute_command(f"llm_query {text.strip()}")
            else:
                print(t("rec.voice_cmd_fail", text=text.strip(), confidence=confidence))
                if hasattr(self, "_file_watcher"):
                    self._file_watcher._broadcast("alert", json.dumps(
                        {"message": t("dash.alert_cmd_fail", text=text.strip())},
                        ensure_ascii=False))

    def _save_attendees_for_session(self, transcript_path: str) -> None:
        """gcal 連携が有効かつ進行中イベントがあれば、参加予定者を JSON で保存する。"""
        gcal = getattr(self, "gcal_monitor", None)
        attendees = gcal.get_ongoing_event_attendees() if gcal else []
        if not attendees:
            return
        tn = TranscriptName.parse(os.path.basename(transcript_path))
        if tn is None:
            return
        out_path = os.path.join(os.path.dirname(transcript_path), tn.attendees_filename)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump({"attendees": attendees}, f, ensure_ascii=False, indent=2)
            logger.info("参加予定者を保存: %s (%d名)", out_path, len(attendees))
        except OSError as e:
            logger.warning("参加予定者の保存に失敗: %s", e)

    def _auto_summarize(self, transcript_path: str) -> None:
        """会議終了時に自動で議事録を生成する"""
        basename = os.path.basename(transcript_path)
        tn = TranscriptName.parse(basename)
        if tn is None:
            logger.warning("_auto_summarize: TranscriptName パース失敗: %s", basename)
            return
        summary_path = os.path.join(self._output_dir, tn.summary_filename)
        summary_name = tn.summary_filename

        # summary_source に応じてソースファイルを切り替え
        # - "transcript": 強制的に transcript
        # - "translate":  強制的に translation（無ければ transcript にフォールバック）
        # - None (未指定): translation があれば translation、無ければ transcript
        config = load_config()
        source_path = transcript_path
        summary_source = config.get("summary_source")
        if summary_source in ("translate", None):
            lang = config.get("translate_language", "ja")
            tr_name = tn.translation_filename(lang)
            tr_path = os.path.join(os.path.dirname(transcript_path), tr_name)
            if os.path.exists(tr_path):
                source_path = tr_path
                logger.info("summary_source=%s: 翻訳ファイル使用: %s",
                            summary_source or "auto", tr_name)
            elif summary_source == "translate":
                logger.warning("summary_source=translate: 翻訳ファイル未検出、transcript にフォールバック: %s", tr_name)

        # 既存 summary があれば --existing で渡す
        cmd = [
            sys.executable, "-m", "shadow_clerk.llm_client",
            "summarize", "--mode", "full",
            "--file", source_path,
            "--output", summary_path,
        ]

        src_name = os.path.basename(source_path)
        logger.info("要約実行: provider=api, %s → %s", src_name, summary_name)
        print(t("rec.auto_summary_start", src=src_name, dst=summary_name))

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=600,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            if result.returncode == 0:
                logger.info("自動要約完了: %s", summary_path)
                print(t("rec.auto_summary_done", name=summary_name))
                if hasattr(self, "_file_watcher"):
                    self._file_watcher._broadcast("alert", json.dumps(
                        {"message": t("dash.alert_summary_done", name=summary_name)},
                        ensure_ascii=False))
            else:
                logger.warning("自動要約失敗: %s", result.stderr.strip())
                print(t("rec.auto_summary_fail", error=result.stderr.strip()[:100]))
        except subprocess.TimeoutExpired:
            logger.warning("自動要約タイムアウト")
            print(t("rec.auto_summary_timeout"))
        except Exception as e:
            logger.warning("自動要約エラー: %s", e)

    def _resolve_pynput_key(self, key_name: str) -> Any | None:
        """config の voice_command_key 文字列を pynput のキーオブジェクトに変換"""
        if not _HAS_PYNPUT:
            return None
        key_map = {
            "menu": pynput_keyboard.Key.menu,
            "ctrl_r": pynput_keyboard.Key.ctrl_r,
            "ctrl_l": pynput_keyboard.Key.ctrl_l,
            "alt_r": pynput_keyboard.Key.alt_r,
            "alt_l": pynput_keyboard.Key.alt_l,
            "shift_r": pynput_keyboard.Key.shift_r,
            "shift_l": pynput_keyboard.Key.shift_l,
        }
        return key_map.get(key_name)

    def _key_listener_thread(self) -> None:
        """pynput でグローバルキー監視を行うスレッド"""
        from typing import Any
        target_key = self._resolve_pynput_key(self._voice_command_key)
        if target_key is None:
            logger.warning("voice_command_key '%s' を解決できません", self._voice_command_key)
            return

        logger.info("キーリスナー開始: %s", self._voice_command_key)

        def on_press(key: Any) -> None:
            if key == target_key:
                self._command_mode = True
                logger.info("コマンドモード ON (%s pressed)", self._voice_command_key)
                print(t("rec.ptt_on", vkey=self._voice_command_key))

        def on_release(key: Any) -> None:
            if key == target_key:
                self._command_mode = False
                self._command_mode_release_time = time.time()
                logger.info("コマンドモード OFF (%s released)", self._voice_command_key)
                print(t("rec.ptt_off", vkey=self._voice_command_key))

        with pynput_keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
            self.stop_event.wait()
            listener.stop()

    def _resolve_evdev_key(self, key_name: str) -> int | None:
        """config の voice_command_key 文字列を evdev キーコードに変換"""
        if not _HAS_EVDEV:
            return None
        key_map = {
            "menu": _ecodes.KEY_COMPOSE,
            "f23": _ecodes.KEY_F23,
            "ctrl_r": _ecodes.KEY_RIGHTCTRL,
            "ctrl_l": _ecodes.KEY_LEFTCTRL,
            "alt_r": _ecodes.KEY_RIGHTALT,
            "alt_l": _ecodes.KEY_LEFTALT,
            "shift_r": _ecodes.KEY_RIGHTSHIFT,
            "shift_l": _ecodes.KEY_LEFTSHIFT,
        }
        return key_map.get(key_name)

    def _find_keyboard_devices(self) -> list:
        """evdev でキーボードデバイスを検出"""
        devices = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                if _ecodes.EV_KEY in caps and _ecodes.KEY_A in caps[_ecodes.EV_KEY]:
                    devices.append(dev)
                else:
                    dev.close()
            except (PermissionError, OSError):
                pass
        return devices

    def _key_listener_thread_evdev(self) -> None:
        """evdev でグローバルキー監視を行うスレッド (Wayland 対応)"""
        import select

        target_code = self._resolve_evdev_key(self._voice_command_key)
        if target_code is None:
            logger.warning("voice_command_key '%s' を evdev キーコードに解決できません",
                           self._voice_command_key)
            return

        keyboards = self._find_keyboard_devices()
        if not keyboards:
            logger.warning("evdev: キーボードデバイスが見つかりません。"
                           " 'sudo usermod -aG input $USER' を実行してください。")
            return

        logger.info("evdev キーリスナー開始: %s (デバイス: %s)",
                     self._voice_command_key,
                     ", ".join(d.name for d in keyboards))

        # 起動時に既に押下されているキーを検出し、初期イベントを無視するためのフラグ
        initially_held = False
        for dev in keyboards:
            try:
                if target_code in dev.active_keys():
                    initially_held = True
                    break
            except OSError:
                pass
        if initially_held:
            logger.info("evdev: %s は起動時に押下状態 — 初期イベントを無視",
                        self._voice_command_key)

        try:
            while not self.stop_event.is_set():
                if not keyboards:
                    # 全デバイス切断 → 再接続を待って再スキャン
                    self.stop_event.wait(timeout=3.0)
                    keyboards = self._find_keyboard_devices()
                    if keyboards:
                        logger.info("evdev: キーボード再検出: %s",
                                    ", ".join(d.name for d in keyboards))
                    continue
                try:
                    r, _, _ = select.select(keyboards, [], [], 0.1)
                except OSError:
                    # 無効な fd が混入 → 全デバイスを破棄して再スキャンへ
                    for dev in keyboards:
                        try:
                            dev.close()
                        except Exception:
                            pass
                    keyboards = []
                    continue
                for dev in r:
                    try:
                        for event in dev.read():
                            if event.type == _ecodes.EV_KEY and event.code == target_code:
                                if event.value == 1:  # key down
                                    if initially_held:
                                        # 起動前から押されていたキーの down イベント → 無視
                                        continue
                                    self._command_mode = True
                                    logger.info("コマンドモード ON (%s pressed) [evdev]",
                                                self._voice_command_key)
                                    print(t("rec.ptt_on", vkey=self._voice_command_key))
                                elif event.value == 0:  # key up
                                    initially_held = False  # リリースされたのでフラグ解除
                                    self._command_mode = False
                                    self._command_mode_release_time = time.time()
                                    logger.info("コマンドモード OFF (%s released) [evdev]",
                                                self._voice_command_key)
                                    print(t("rec.ptt_off", vkey=self._voice_command_key))
                                # value == 2 (キーリピート) は無視
                    except OSError:
                        # デバイス切断。リストに残すと select が即時 return し
                        # busy-loop になるため必ず除去する
                        logger.warning("evdev: デバイス切断を検出、監視から除外: %s", dev.name)
                        keyboards.remove(dev)
                        try:
                            dev.close()
                        except Exception:
                            pass
        finally:
            for dev in keyboards:
                try:
                    dev.close()
                except Exception:
                    pass

    def _resolve_translate_target(self, date_arg: str) -> str | None:
        """date_arg が指定されていれば transcript パスに解決。空なら None（→ self.output_path を使用）。"""
        if not date_arg.strip():
            return None
        path = os.path.join(self._output_dir, TranscriptName.from_date_str(date_arg.strip()).filename)
        logger.info("翻訳対象ファイル指定: %s", os.path.basename(path))
        return path

    def _launch_translate_thread(self, target: str | None, reset_offset: bool) -> None:
        """翻訳スレッドを起動する。reset_offset=True の場合はオフセットをリセットする。"""
        transcript = target or self.output_path
        if reset_offset:
            offset_file = self._translate_offset_file(transcript)
            with open(offset_file, "w", encoding="utf-8") as f:
                f.write("0")
            # 翻訳ファイルも truncate して古い内容が混在しないようにする
            config = load_config()
            lang = config.get("translate_language", "ja")
            tn = TranscriptName.parse(os.path.basename(transcript))
            tr_name = tn.translation_filename(lang) if tn else os.path.basename(transcript).replace(".txt", f"-{lang}.txt")
            tr_path = os.path.join(os.path.dirname(transcript), tr_name)
            try:
                open(tr_path, "w").close()
                logger.debug("翻訳ファイル truncate: %s", tr_name)
            except OSError:
                pass
        # 過去ファイル指定なら one-shot、現在ファイルなら継続ループ
        loop_target = target if target != self.output_path else None
        self._translate_stop_event.clear()
        self._translate_thread = threading.Thread(
            target=self._translate_loop, args=(loop_target,),
            name="translate-loop", daemon=True)
        self._translate_thread.start()
        logger.info("翻訳スレッド起動: target=%s, reset_offset=%s",
                    os.path.basename(transcript), reset_offset)

    def _broadcast_asr_status(self) -> None:
        """ASRバックエンド/モデル変更をSSEで通知"""
        if hasattr(self, "_file_watcher"):
            self._file_watcher._broadcast("asr_status", json.dumps({
                "asr_backend": self.transcriber._backend,
                "asr_model_id": self.transcriber._loaded_model_id or self.transcriber.model_size,
            }))

    def _execute_command(self, cmd: str) -> None:
        """コマンド文字列をパースして実行"""
        cmd = cmd.strip()
        if not cmd:
            return

        if cmd.startswith("set_language "):
            lang = cmd.split(None, 1)[1].strip()
            self.transcriber.language = lang
            logger.info("言語を変更: %s", lang)
            self.transcriber.ensure_model_for_language()
            self._broadcast_asr_status()

        elif cmd == "unset_language":
            self.transcriber.language = None
            logger.info("言語を自動検出に変更")
            self.transcriber.ensure_model_for_language()
            self._broadcast_asr_status()

        elif cmd.startswith("start_meeting"):
            parts = cmd.split(None, 1)
            if len(parts) > 1:
                meeting_name = _sanitize_meeting_name(parts[1])
            else:
                # 名前なし: 進行中の gcal イベントがあればその名前を自動割り当て
                gcal = getattr(self, "gcal_monitor", None)
                meeting_name = gcal.get_ongoing_event_name() if gcal else ""
                if meeting_name:
                    logger.info("gcal 進行中イベントを会議名に割り当て: %s", meeting_name)
            now = datetime.datetime.now()
            name_suffix = f"@{meeting_name}" if meeting_name else ""
            filename = now.strftime(f"transcript-%Y%m%d%H%M{name_suffix}.txt")
            with self.transcript_lock:
                self.output_path = os.path.join(self._output_dir, filename)
                marker = f"--- 会議開始 {now.strftime('%Y-%m-%d %H:%M')} ---\n"
                with open(self.output_path, "a", encoding="utf-8") as f:
                    f.write(marker)
            self.current_session = MeetingSession.start(self.output_path, now)
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                f.write(self.output_path)
            logger.info("会議開始: %s", self.output_path)
            print(t("rec.meeting_start", path=self.output_path))
            self._save_attendees_for_session(self.output_path)

        elif cmd == "end_meeting":
            marker = "--- 会議終了 ---\n"
            with self.transcript_lock:
                session_transcript = self.output_path
                with open(session_transcript, "a", encoding="utf-8") as f:
                    f.write(marker)
            logger.info("会議終了: %s", session_transcript)
            print(t("rec.meeting_end", path=session_transcript))
            # 明示的 output 指定の場合はその値に戻す、そうでなければ現在日付のデフォルト
            if self._explicit_output:
                self.output_path = self.args.output
            else:
                self.output_path = self._get_default_output()
            if self.current_session:
                ended = self.current_session.end()
                logger.info("会議セッション終了: 開始=%s 終了=%s",
                            ended.started_at.strftime("%H:%M:%S"),
                            ended.ended_at.strftime("%H:%M:%S"))
                self.current_session = None
            try:
                os.remove(SESSION_FILE)
            except FileNotFoundError:
                pass
            # auto_summary: 会議終了時に自動で議事録を生成
            config = load_config()
            if config.get("auto_summary"):
                logger.info("自動要約開始: provider=%s", config.get("llm_provider", "claude"))
                threading.Thread(
                    target=self._auto_summarize,
                    args=(session_transcript,),
                    name="auto-summary", daemon=True,
                ).start()

        elif cmd.startswith("set_model "):
            model_size = cmd.split(None, 1)[1].strip()
            logger.info("モデル変更中: %s ...", model_size)
            print(t("rec.model_changing", model=model_size))
            self.transcriber.reload_model(model_size)
            logger.info("モデル変更完了: %s", model_size)
            print(t("rec.model_changed", model=model_size))

        elif cmd == "translate_start" or cmd.startswith("translate_start "):
            parts = cmd.split(None, 1)
            target = self._resolve_translate_target(parts[1] if len(parts) > 1 else "")
            config = load_config()
            provider = get_translation_provider(config)
            if self._translate_thread and self._translate_thread.is_alive():
                logger.info("翻訳ループは既に動作中 (provider=%s)", provider)
            else:
                self._launch_translate_thread(target, reset_offset=False)
            print(t("rec.translate_start"))

        elif cmd == "translate_stop":
            if self._translate_thread and self._translate_thread.is_alive():
                self._translate_stop_event.set()
                self._translate_thread.join(timeout=10)
                self._translate_thread = None
                logger.info("翻訳停止: 内部スレッド")
            print(t("rec.translate_stop"))

        elif cmd.startswith("translate_regenerate"):
            parts = cmd.split(None, 1)
            target = self._resolve_translate_target(parts[1] if len(parts) > 1 else "")
            config = load_config()
            provider = get_translation_provider(config)
            logger.info("翻訳再生成: provider=%s, file=%s, offset リセット",
                        provider, os.path.basename(target or self.output_path))
            if self._translate_thread and self._translate_thread.is_alive():
                self._translate_stop_event.set()
                self._translate_thread.join(timeout=10)
                self._translate_thread = None
            self._launch_translate_thread(target, reset_offset=True)

        elif cmd.startswith("custom_exec "):
            action = cmd.split(None, 1)[1]
            logger.info("カスタムコマンド実行: %s", action)
            print(t("rec.custom_exec", action=action))
            subprocess.Popen(action, shell=True)

        elif cmd.startswith("llm_query "):
            query_text = cmd.split(None, 1)[1]
            logger.info("LLM クエリ: %s", query_text)
            threading.Thread(
                target=self._llm_query, args=(query_text,),
                name="llm-query", daemon=True,
            ).start()

        elif cmd == "mute_mic":
            self.mute_mic = True
            logger.info("マイクミュート ON")

        elif cmd == "unmute_mic":
            self.mute_mic = False
            logger.info("マイクミュート OFF")

        elif cmd == "mute_monitor":
            self.mute_monitor = True
            logger.info("スピーカーミュート ON")

        elif cmd == "unmute_monitor":
            self.mute_monitor = False
            logger.info("スピーカーミュート OFF")

        elif cmd == "ptt_on":
            self._command_mode = True
            logger.info("PTT 強制 ON (Dashboard)")

        elif cmd == "ptt_off":
            self._command_mode = False
            self._command_mode_release_time = time.time()
            logger.info("PTT 強制 OFF (Dashboard)")

        else:
            # LLM が description 側の文字列を返した場合、パターンに再マッチ
            for pattern, mapped_cmd in VOICE_COMMANDS:
                if pattern.search(cmd):
                    logger.info("コマンド再マッチ(builtin): %s → %s", cmd, mapped_cmd)
                    self._execute_command(mapped_cmd)
                    return
            for pattern, action in self._custom_commands:
                if pattern.search(cmd):
                    logger.info("コマンド再マッチ(custom): %s → %s", cmd, action)
                    print(t("rec.custom_exec", action=action))
                    subprocess.Popen(action, shell=True)
                    return
            logger.warning("不明なコマンド: %s", cmd)
