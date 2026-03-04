"""Shadow-clerk daemon: レコーダーコマンド・キーリスナー ミックスイン"""
import datetime
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time

try:
    from shadow_clerk.llm_client import get_api_client, load_glossary, load_glossary_replacements, load_dotenv as llm_load_dotenv, _spell_check
    _HAS_LLM_CLIENT = True
except ImportError:
    _HAS_LLM_CLIENT = False

try:
    from pynput import keyboard as pynput_keyboard
    _HAS_PYNPUT = True
except ImportError:
    _HAS_PYNPUT = False

try:
    import evdev
    from evdev import ecodes as _ecodes
    _HAS_EVDEV = True
except ImportError:
    _HAS_EVDEV = False

from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import (
    SAMPLE_RATE, COMMAND_FILE, SESSION_FILE, GLOSSARY_FILE,
    VOICE_CMD_PREFIX, VOICE_CMD_SUFFIX, VOICE_COMMANDS,
)
from shadow_clerk._daemon_config import load_config, get_translation_provider, _builtin_command_descs

logger = logging.getLogger("shadow-clerk")


class _RecorderCommandMixin:
    """コマンド処理・キーリスナー ミックスイン"""

    def _extract_command_body(self, text: str) -> str | None:
        """プレフィックス/サフィックス「クラーク」を検出し、コマンド本文を返す。未検出なら None。"""
        if VOICE_CMD_PREFIX.match(text):
            return VOICE_CMD_PREFIX.sub("", text).strip()
        elif VOICE_CMD_SUFFIX.search(text):
            return VOICE_CMD_SUFFIX.sub("", text).strip()
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
        # 3. LLM フォールバック（API 設定済みの場合）
        if load_config().get("api_endpoint") and body:
            return f"llm_query {body}"
        return None

    def _get_command_list(self) -> list[str]:
        """ビルトイン + カスタムコマンドのパターン説明リストを生成"""
        commands = [c["description"] for c in _builtin_command_descs()]
        for pattern, action in self._custom_commands:
            commands.append(pattern.pattern)
        return commands

    def _spell_and_match(self, text: str, timestamp: str = "", display_speaker: str = ""):
        """spell-check で誤字訂正してからパターンマッチを実行する"""
        corrected = text
        try:
            result = subprocess.run(
                [sys.executable, "-m", "shadow_clerk.llm_client", "spell-check"],
                input=text, capture_output=True, text=True, timeout=30,
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

    def _llm_match_and_execute(self, text: str):
        """LLM にコマンドマッチングを依頼し、confidence が高ければ実行する"""
        commands = self._get_command_list()
        payload = json.dumps({"text": text, "commands": commands}, ensure_ascii=False)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "shadow_clerk.llm_client", "match-command"],
                input=payload, capture_output=True, text=True, timeout=30,
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
            print(t("rec.voice_cmd_fail", text=text.strip(), confidence=confidence))
            if hasattr(self, "_file_watcher"):
                self._file_watcher._broadcast("alert", json.dumps(
                    {"message": t("dash.alert_cmd_fail", text=text.strip())},
                    ensure_ascii=False))

    def _auto_summarize(self, transcript_path: str):
        """会議終了時に自動で議事録を生成する"""
        basename = os.path.basename(transcript_path)
        summary_name = basename.replace("transcript-", "summary-").replace(".txt", ".md")
        summary_path = os.path.join(self._output_dir, summary_name)

        # summary_source に応じてソースファイルを切り替え
        config = load_config()
        source_path = transcript_path
        if config.get("summary_source") == "translate":
            lang = config.get("translate_language", "ja")
            tr_name = basename.replace(".txt", f"-{lang}.txt")
            tr_path = os.path.join(os.path.dirname(transcript_path), tr_name)
            if os.path.exists(tr_path):
                source_path = tr_path
                logger.info("summary_source=translate: 翻訳ファイル使用: %s", tr_name)
            else:
                logger.warning("summary_source=translate: 翻訳ファイル未検出、transcript にフォールバック: %s", tr_name)

        # 既存 summary があれば --existing で渡す
        cmd = [
            sys.executable, "-m", "shadow_clerk.llm_client",
            "summarize", "--mode", "full",
            "--file", source_path,
            "--output", summary_path,
        ]

        src_name = os.path.basename(source_path)
        logger.info("自動要約開始: %s → %s", src_name, summary_name)
        print(t("rec.auto_summary_start", src=src_name, dst=summary_name))

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=180,
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

    def _resolve_pynput_key(self, key_name: str):
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

    def _key_listener_thread(self):
        """pynput でグローバルキー監視を行うスレッド"""
        target_key = self._resolve_pynput_key(self._voice_command_key)
        if target_key is None:
            logger.warning("voice_command_key '%s' を解決できません", self._voice_command_key)
            return

        logger.info("キーリスナー開始: %s", self._voice_command_key)

        def on_press(key):
            if key == target_key:
                self._command_mode = True
                logger.info("コマンドモード ON (%s pressed)", self._voice_command_key)
                print(t("rec.ptt_on", vkey=self._voice_command_key))

        def on_release(key):
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

    def _key_listener_thread_evdev(self):
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
                r, _, _ = select.select(keyboards, [], [], 0.1)
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
                        pass  # デバイス切断等
        finally:
            for dev in keyboards:
                try:
                    dev.close()
                except Exception:
                    pass

    def _execute_command(self, cmd: str):
        """コマンド文字列をパースして実行"""
        cmd = cmd.strip()
        if not cmd:
            return

        if cmd.startswith("set_language "):
            lang = cmd.split(None, 1)[1].strip()
            self.transcriber.language = lang
            logger.info("言語を変更: %s", lang)
            self.transcriber.ensure_model_for_language()

        elif cmd == "unset_language":
            self.transcriber.language = None
            logger.info("言語を自動検出に変更")
            self.transcriber.ensure_model_for_language()

        elif cmd.startswith("start_meeting"):
            parts = cmd.split(None, 1)
            now = datetime.datetime.now()
            filename = now.strftime("transcript-%Y%m%d%H%M.txt")
            self.output_path = os.path.join(self._output_dir, filename)
            marker = f"--- 会議開始 {now.strftime('%Y-%m-%d %H:%M')} ---\n"
            with open(self.output_path, "a", encoding="utf-8") as f:
                f.write(marker)
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                f.write(self.output_path)
            logger.info("会議開始: %s", self.output_path)
            print(t("rec.meeting_start", path=self.output_path))

        elif cmd == "end_meeting":
            marker = "--- 会議終了 ---\n"
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
            try:
                os.remove(SESSION_FILE)
            except FileNotFoundError:
                pass
            # auto_summary: 会議終了時に自動で議事録を生成
            config = load_config()
            if config.get("auto_summary"):
                if config.get("llm_provider") == "api":
                    threading.Thread(
                        target=self._auto_summarize,
                        args=(session_transcript,),
                        name="auto-summary", daemon=True,
                    ).start()
                else:
                    # Claude provider: .clerk_command に書いて Claude Code に処理させる
                    session_name = os.path.basename(session_transcript)
                    with open(COMMAND_FILE, "w", encoding="utf-8") as f:
                        f.write(f"generate_summary {session_name}")
                    logger.info("要約コマンドを .clerk_command に書き込み (claude provider)")

        elif cmd.startswith("set_model "):
            model_size = cmd.split(None, 1)[1].strip()
            logger.info("モデル変更中: %s ...", model_size)
            print(t("rec.model_changing", model=model_size))
            self.transcriber.reload_model(model_size)
            logger.info("モデル変更完了: %s", model_size)
            print(t("rec.model_changed", model=model_size))

        elif cmd == "translate_start":
            config = load_config()
            if get_translation_provider(config) in ("api", "libretranslate"):
                if self._translate_thread and self._translate_thread.is_alive():
                    logger.info("翻訳ループは既に動作中")
                else:
                    self._translate_stop_event.clear()
                    self._translate_thread = threading.Thread(
                        target=self._translate_loop, name="translate-loop", daemon=True)
                    self._translate_thread.start()
            else:
                self._translating_external = True
                with open(COMMAND_FILE, "w", encoding="utf-8") as f:
                    f.write("translate_start")
                logger.info("翻訳開始コマンドを .clerk_command に書き込み (claude provider)")
            print(t("rec.translate_start"))

        elif cmd == "translate_stop":
            if self._translate_thread and self._translate_thread.is_alive():
                self._translate_stop_event.set()
                self._translate_thread.join(timeout=10)
                self._translate_thread = None
                logger.info("翻訳ループ停止")
            else:
                self._translating_external = False
                with open(COMMAND_FILE, "w", encoding="utf-8") as f:
                    f.write("translate_stop")
                logger.info("翻訳停止コマンドを .clerk_command に書き込み")
            print(t("rec.translate_stop"))


        elif cmd == "translate_regenerate":
            # 翻訳中なら停止
            if self._translate_thread and self._translate_thread.is_alive():
                self._translate_stop_event.set()
                self._translate_thread.join(timeout=10)
                self._translate_thread = None

            config = load_config()
            lang = config.get("translate_language", "ja")
            transcript = self.output_path

            # オフセットリセット（翻訳ファイルは _translate_loop 側で上書き）
            offset_file = self._translate_offset_file(transcript)
            with open(offset_file, "w", encoding="utf-8") as f:
                f.write("0")
            logger.info("翻訳再生成: offset リセット")

            # provider に応じて翻訳を再開
            if get_translation_provider(config) in ("api", "libretranslate"):
                self._translate_stop_event.clear()
                self._translate_thread = threading.Thread(
                    target=self._translate_loop, name="translate-loop", daemon=True)
                self._translate_thread.start()
            else:
                self._translating_external = True
                with open(COMMAND_FILE, "w", encoding="utf-8") as f:
                    f.write("translate_start")

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
