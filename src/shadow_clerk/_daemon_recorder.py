"""Shadow-clerk daemon: メインレコーダー"""

import datetime
import json
import logging
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
import numpy as np
import sounddevice as sd
from shadow_clerk import DATA_DIR
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import (
    SAMPLE_RATE, FRAME_SIZE, CHANNELS, DTYPE,
    COMMAND_FILE, SESSION_FILE, GLOSSARY_FILE,
    VOICE_CMD_PREFIX, VOICE_CMD_SUFFIX, VOICE_COMMANDS,
)
from shadow_clerk._daemon_config import load_config, get_translation_provider, _builtin_command_descs
from shadow_clerk._daemon_audio import detect_backend, find_monitor_device_sd
from shadow_clerk._daemon_vad import VADSegmenter
from shadow_clerk._daemon_transcriber import Transcriber, GlossaryReplacer
from shadow_clerk._daemon_dashboard import LogBuffer, FileWatcher, DashboardHandler

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

logger = logging.getLogger("shadow-clerk")

# --- メインレコーダー ---
class Recorder:
    """音声キャプチャ・VAD・文字起こしの統合"""

    def __init__(self, args):
        self.args = args
        self.stop_event = threading.Event()
        self.mic_queue: queue.Queue = queue.Queue()
        self.monitor_queue: queue.Queue = queue.Queue()
        self.vad_queue: queue.Queue = queue.Queue()
        self.transcribe_queue: queue.Queue = queue.Queue()
        self.interim_queue: queue.Queue = queue.Queue(maxsize=2)

        self.backend_name, self.backend = detect_backend(args.backend)

        # config 読み込み
        config = load_config()

        # カスタム音声コマンドをコンパイル
        self._custom_commands = []
        for entry in config.get("custom_commands") or []:
            try:
                pat = re.compile(entry["pattern"], re.IGNORECASE)
                self._custom_commands.append((pat, entry["action"]))
            except (KeyError, re.error) as e:
                logger.warning("カスタムコマンド定義エラー: %s — %s", entry, e)

        # Whisper initial_prompt: トリガーワード + ユーザー指定プロンプト
        default_prompt = "クラーク"
        user_prompt = config.get("initial_prompt")
        initial_prompt = f"{default_prompt}、{user_prompt}" if user_prompt else default_prompt

        self.transcriber = Transcriber(
            model_size=args.model,
            language=args.language,
            initial_prompt=initial_prompt,
            beam_size=args.whisper_beam_size,
            compute_type=args.whisper_compute_type,
            device=args.whisper_device,
        )

        # (api_endpoint の判定は load_config() で毎回取得する)

        # output_directory: config で指定されていればそちらを使う
        output_dir_config = config.get("output_directory")
        if output_dir_config:
            self._output_dir = os.path.expanduser(output_dir_config)
            os.makedirs(self._output_dir, exist_ok=True)
        else:
            self._output_dir = DATA_DIR

        # --output が指定されていれば固定、なければ日付ベースのデフォルト
        self._explicit_output = args.output is not None
        if self._explicit_output:
            self.output_path = args.output
        elif os.path.exists(SESSION_FILE):
            # 会議セッション中に再起動された場合、セッションファイルを復元
            try:
                with open(SESSION_FILE, "r", encoding="utf-8") as f:
                    session_path = f.read().strip()
                if session_path and os.path.exists(session_path):
                    self.output_path = session_path
                    logger.info("会議セッション復元: %s", session_path)
                else:
                    self.output_path = self._get_default_output()
            except Exception:
                self.output_path = self._get_default_output()
        else:
            self.output_path = self._get_default_output()
        self.use_monitor = True
        self.use_mic = True
        self.word_replacer = GlossaryReplacer()

        # Push-to-Talk コマンドモード
        self._command_mode = False
        self._command_mode_release_time: float = 0.0  # キーリリース時刻
        self._voice_command_key = config.get("voice_command_key")

        # Mic/Speaker ミュートフラグ
        self.mute_mic = False
        self.mute_monitor = False

        # 翻訳ループ
        self._translate_stop_event = threading.Event()
        self._translate_thread: threading.Thread | None = None
        self._translating_external = False  # Claude provider 経由の翻訳中フラグ

        # リアルタイム interim 翻訳キュー (maxsize=1 で最新のみ保持)
        self._interim_translate_queue: queue.Queue = queue.Queue(maxsize=1)

    def _get_default_output(self) -> str:
        """現在日付ベースのデフォルト transcript パスを返す"""
        filename = datetime.datetime.now().strftime("transcript-%Y%m%d.txt")
        return os.path.join(self._output_dir, filename)

    def _setup_signal_handlers(self):
        def handler(signum, frame):
            logger.info("シグナル受信 (%s)、終了処理中...", signal.Signals(signum).name)
            self.stop_event.set()

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def _mic_capture_thread(self):
        """マイク音声キャプチャスレッド"""
        mic_device = self.args.mic
        logger.info("マイクキャプチャ開始 (device=%s)", mic_device)

        def callback(indata, frames, time_info, status):
            if status:
                logger.warning("マイク status: %s", status)
            self.mic_queue.put(indata[:, 0].copy().astype(np.int16))

        try:
            with self._stream_lock:
                stream = sd.InputStream(
                    samplerate=SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    blocksize=FRAME_SIZE,
                    device=mic_device,
                    callback=callback,
                )
                stream.start()
            self.stop_event.wait()
            stream.stop()
            stream.close()
        except sd.PortAudioError as e:
            logger.error("マイクキャプチャエラー: %s", e)
            self.use_mic = False

    def _monitor_capture_thread(self):
        """モニター音声キャプチャスレッド"""
        # sounddevice でモニターデバイスを探す
        monitor_device = self.args.monitor
        if monitor_device is None:
            monitor_device = find_monitor_device_sd()

        if monitor_device is not None:
            dev_info = sd.query_devices(monitor_device)
            logger.info("sounddevice monitor キャプチャ開始 (device=%s: %s)", monitor_device, dev_info["name"])
            if self._monitor_capture_sounddevice(monitor_device):
                return
            # sounddevice 失敗 → バックエンドにフォールバック
            logger.info("sounddevice 失敗、%s バックエンドにフォールバック", self.backend_name)

        # バックエンド固有のモニターキャプチャ
        if self.backend:
            monitor_source = self.backend.detect_monitor_source()
            if monitor_source:
                logger.info("%s monitor キャプチャ開始: %s", self.backend_name, monitor_source)
                self.backend.start_monitor_capture(
                    monitor_source, self.monitor_queue, self.stop_event
                )
                return

        logger.warning("モニターソースが見つかりません。マイクのみで録音します。")
        self.use_monitor = False

    def _monitor_capture_sounddevice(self, device) -> bool:
        """sounddevice でモニターデバイスをキャプチャ。成功なら True、失敗なら False。"""

        def callback(indata, frames, time_info, status):
            if status:
                logger.warning("モニター status: %s", status)
            self.monitor_queue.put(indata[:, 0].copy().astype(np.int16))

        max_retries = 2
        for attempt in range(max_retries):
            try:
                sd._initialize()
                with self._stream_lock:
                    stream = sd.InputStream(
                        samplerate=SAMPLE_RATE,
                        channels=CHANNELS,
                        dtype=DTYPE,
                        blocksize=FRAME_SIZE,
                        device=device,
                        callback=callback,
                    )
                    stream.start()
                self.stop_event.wait()
                stream.stop()
                stream.close()
                return True
            except sd.PortAudioError as e:
                if attempt < max_retries - 1:
                    logger.warning("sounddevice モニターエラー (リトライ %d/%d): %s", attempt + 1, max_retries, e)
                    time.sleep(1)
                else:
                    logger.warning("sounddevice モニター失敗、バックエンドにフォールバック: %s", e)
        return False

    def _vad_thread_for_queue(self, audio_queue: queue.Queue, segmenter: VADSegmenter,
                              label: str):
        """指定キューからフレームを読み VAD セグメンテーションを行うスレッド"""
        logger.info("VAD スレッド開始: %s", label)
        command_mode_latch = False  # セグメント中に一度でも command_mode なら True を維持
        PTT_GRACE_SEC = 1.5  # キーリリース後の猶予時間
        interim_seq = 0
        last_interim_time = 0.0
        interim_enabled = load_config().get("interim_transcription", False)

        while not self.stop_event.is_set():
            try:
                frame = audio_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            # フレームサイズ調整
            if len(frame) != FRAME_SIZE:
                if len(frame) > FRAME_SIZE:
                    frame = frame[:FRAME_SIZE]
                else:
                    frame = np.pad(frame, (0, FRAME_SIZE - len(frame)))

            # コマンドモード判定: キー押下中 or リリース後の猶予期間内
            if self._command_mode or (
                self._command_mode_release_time > 0
                and time.time() - self._command_mode_release_time < PTT_GRACE_SEC
            ):
                command_mode_latch = True
            elif command_mode_latch and not self._command_mode:
                # 猶予期間が過ぎてもセグメントが生成されなかった場合、ラッチをリセット
                command_mode_latch = False

            timestamp = time.time()
            segment = segmenter.process_frame(frame, timestamp)
            if segment is not None:
                ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.transcribe_queue.put((segment, ts, label, command_mode_latch))
                command_mode_latch = False  # 次のセグメント用にリセット
                self._command_mode_release_time = 0.0  # 猶予タイマーもクリア
                interim_seq += 1
                last_interim_time = 0.0
                # final segment 確定時に config を再読み込み（ランタイム切替対応）
                interim_enabled = load_config().get("interim_transcription", False)
            elif interim_enabled and label == "monitor" and segmenter.in_speech:
                now = time.time()
                if now - last_interim_time >= 1.5:
                    interim_audio = segmenter.get_interim_segment()
                    if interim_audio is not None:
                        try:
                            self.interim_queue.put_nowait(
                                (interim_audio, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 label, interim_seq))
                        except queue.Full:
                            pass  # best effort
                        last_interim_time = now

        # フラッシュ
        segment = segmenter.flush()
        if segment is not None:
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.transcribe_queue.put((segment, ts, label, command_mode_latch))

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

    def _llm_query(self, text: str):
        """LLM にクエリを投げて結果を表示・保存する（バックグラウンド実行）"""
        response_file = os.path.join(DATA_DIR, ".clerk_response")
        try:
            result = subprocess.run(
                [sys.executable, "-m", "shadow_clerk.llm_client", "query", text],
                capture_output=True, text=True, timeout=60,
            )
            answer = result.stdout.strip()
            if result.returncode != 0:
                logger.error("LLM クエリエラー: %s", result.stderr.strip())
                return
            if answer:
                print(f"[LLM] {answer}")
                with open(response_file, "w", encoding="utf-8") as f:
                    f.write(answer)
                logger.info("LLM 回答を .clerk_response に保存")
        except subprocess.TimeoutExpired:
            logger.error("LLM クエリがタイムアウトしました")
        except Exception as e:
            logger.error("LLM クエリ失敗: %s", e)

    @staticmethod
    def _translate_offset_file(transcript_path: str) -> str:
        """transcript パスに対応する翻訳 offset ファイルパスを返す。

        例: /path/to/transcript-20260301.txt → /path/to/transcript-20260301.txt.translate_offset
        """
        return transcript_path + ".translate_offset"

    def _translate_loop(self):
        """翻訳ループスレッド (llm_provider: api 用)"""
        config = load_config()
        lang = config.get("translate_language", "ja")
        logger.info("翻訳ループ開始: lang=%s", lang)

        while not self.stop_event.is_set() and not self._translate_stop_event.is_set():
            try:
                transcript = self.output_path
                offset_file = self._translate_offset_file(transcript)
                try:
                    with open(offset_file, "r", encoding="utf-8") as f:
                        offset = int(f.read().strip())
                except (OSError, ValueError):
                    offset = 0

                try:
                    size = os.path.getsize(transcript)
                except OSError:
                    size = 0

                if size > offset:
                    # チャンク分割: 大量テキストを一度に投げないよう制限
                    chunk_limit = 8000  # bytes
                    effective_size = min(size, offset + chunk_limit)
                    result = subprocess.run(
                        [sys.executable, "-m", "shadow_clerk.llm_client", "--verbose",
                         "translate", lang, "--file", transcript, "--offset", str(offset),
                         "--max-bytes", str(effective_size - offset)],
                        capture_output=True, text=True, timeout=300,
                    )
                    if result.returncode == 0 and result.stdout.strip():
                        basename = os.path.basename(transcript)
                        tr_name = basename.replace(".txt", f"-{lang}.txt")
                        tr_path = os.path.join(os.path.dirname(transcript), tr_name)
                        mode = "w" if offset == 0 else "a"
                        with open(tr_path, mode, encoding="utf-8") as f:
                            f.write(result.stdout)
                        with open(offset_file, "w", encoding="utf-8") as f:
                            f.write(str(effective_size))
                        logger.info("翻訳完了: %d bytes → %s", effective_size - offset, tr_name)
                    elif result.returncode != 0:
                        logger.error("翻訳エラー: %s", result.stderr.strip()[:200])
            except subprocess.TimeoutExpired:
                logger.error("翻訳タイムアウト")
            except Exception as e:
                logger.error("翻訳ループエラー: %s", e)

            self._translate_stop_event.wait(timeout=5.0)

        logger.info("翻訳ループ終了")

    def _command_watch_thread(self):
        """コマンドファイルをポーリングして実行するスレッド"""
        logger.info("コマンド監視スレッド開始")
        while not self.stop_event.is_set():
            try:
                if os.path.exists(COMMAND_FILE):
                    with open(COMMAND_FILE, "r", encoding="utf-8") as f:
                        cmd = f.read().strip()
                    # 翻訳コマンド: translation_provider で判定
                    _translate_commands = ("translate_start", "translate_stop", "translate_regenerate")
                    # 要約コマンド: llm_provider で判定 (ファイル名付き: generate_summary_full transcript-*.txt)
                    _is_translate = cmd in _translate_commands
                    _is_summary = cmd.startswith("generate_summary")
                    if _is_translate:
                        config = load_config()
                        if get_translation_provider(config) in ("api", "libretranslate"):
                            os.remove(COMMAND_FILE)
                            logger.info("コマンドファイル検出: %s", cmd)
                            self._execute_command(cmd)
                        # claude provider → SKILL.md 向けにファイルを残す
                    elif _is_summary:
                        config = load_config()
                        if config.get("llm_provider") == "api":
                            os.remove(COMMAND_FILE)
                            logger.info("コマンドファイル検出: %s", cmd)
                            self._execute_command(cmd)
                        # claude provider → SKILL.md 向けにファイルを残す
                    else:
                        os.remove(COMMAND_FILE)
                        if cmd:
                            logger.info("コマンドファイル検出: %s", cmd)
                            self._execute_command(cmd)
            except Exception as e:
                logger.error("コマンド処理エラー: %s", e)
            self.stop_event.wait(timeout=0.5)

    # 短いノイズ語フィルタ: 3文字以内、かな/カナ開始、小書きかな/カナ終了
    _SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ")
    _KANA_START = re.compile(r"^[\u3041-\u3096\u30A1-\u30F6]")

    @staticmethod
    def _is_noise_text(text: str) -> bool:
        """短いノイズ語（「あっ」「ピッ」等）かどうか判定"""
        s = text.strip()
        if len(s) > 3 or len(s) == 0:
            return False
        if Recorder._KANA_START.match(s) and s[-1] in Recorder._SMALL_KANA:
            return True
        return False

    @staticmethod
    def _should_skip_response(text: str, file_speaker: str, last_speaker: str | None) -> bool:
        """「はい」「いいえ」などの相手にたいする応答のみの発話を、直前が同じ話者の場合スキップ"""
        s = text.strip()
        if s not in ("はい", "いいえ", "ああ", "うん", "へー", "ほー", "はー"):
            return False
        # 直前の話者が別人なら記録する（= スキップしない）
        if last_speaker is not None and last_speaker != file_speaker:
            return False
        # 直前が同じ話者 or 不明 → スキップ
        return True

    def _transcribe_thread(self):
        """文字起こしスレッド"""
        logger.info("文字起こしスレッド開始")
        self.transcriber.load_model()

        # ファイル書き込み用ラベル（データフォーマット固定）
        file_labels = {"mic": "自分", "monitor": "相手"}
        # ターミナル表示用ラベル（i18n 対応）
        display_labels = {"mic": t("speaker.mic"), "monitor": t("speaker.monitor")}
        last_file_speaker = None  # 直前に書き込んだ話者（はい/いいえフィルタ用）

        while not self.stop_event.is_set():
            try:
                segment, timestamp, source, command_mode = self.transcribe_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # ミュート中のソースはスキップ（ただしコマンドモード中は除く）
            is_muted = (source == "mic" and self.mute_mic) or (source == "monitor" and self.mute_monitor)
            if is_muted and not command_mode:
                logger.debug("%s ミュート中、スキップ", source)
                continue

            duration = len(segment) / SAMPLE_RATE
            display_speaker = display_labels.get(source, source)
            logger.info("文字起こし中 (%s, %.1f秒)...", display_speaker, duration)

            text = self.transcriber.transcribe(segment)
            if text.strip():
                # mic ソースからの音声コマンド検出
                if source == "mic":
                    if command_mode:
                        config = load_config()
                        if config.get("api_endpoint") and config.get("llm_provider") != "claude":
                            # LLM ベースマッチング（別スレッドで実行）
                            threading.Thread(
                                target=self._llm_match_and_execute,
                                args=(text.strip(),),
                                name="cmd-match", daemon=True,
                            ).start()
                        else:
                            # spell-check → 正規表現マッチング
                            threading.Thread(
                                target=self._spell_and_match,
                                args=(text.strip(), timestamp, display_speaker),
                                name="cmd-spell-match", daemon=True,
                            ).start()
                        continue
                    else:
                        # プレフィックス/サフィックス検出 → 誤字訂正経由でマッチング
                        prefix_body = self._extract_command_body(text)
                        if prefix_body is not None:
                            config = load_config()
                            if config.get("api_endpoint") and config.get("llm_provider") != "claude":
                                threading.Thread(
                                    target=self._llm_match_and_execute,
                                    args=(prefix_body,),
                                    name="cmd-match", daemon=True,
                                ).start()
                            else:
                                threading.Thread(
                                    target=self._spell_and_match,
                                    args=(prefix_body, timestamp, display_speaker),
                                    name="cmd-spell-match", daemon=True,
                                ).start()
                            continue

                # 日付変更チェック（セッション中でなく、明示的 output 指定でない場合のみ）
                if not self._explicit_output and not os.path.exists(SESSION_FILE):
                    new_path = self._get_default_output()
                    if new_path != self.output_path:
                        logger.info("日付変更検出、出力先切り替え: %s", new_path)
                        self.output_path = new_path

                text = self.word_replacer.apply(text, self.transcriber.language)
                file_speaker = file_labels.get(source, source)

                # ノイズフィルタ: 短い感嘆語（「あっ」「ピッ」等）
                if self._is_noise_text(text):
                    logger.debug("ノイズフィルタ: %r をスキップ", text.strip())
                    continue
                # はい/いいえフィルタ: 直前が同じ話者ならスキップ
                if self._should_skip_response(text, file_speaker, last_file_speaker):
                    logger.debug("応答フィルタ: %r (speaker=%s) をスキップ", text.strip(), file_speaker)
                    continue

                file_line = f"[{timestamp}] [{file_speaker}] {text}\n"
                with open(self.output_path, "a", encoding="utf-8") as f:
                    f.write(file_line)
                    f.flush()
                last_file_speaker = file_speaker
                display_line = f"[{timestamp}] [{display_speaker}] {text}"
                print(f"  {display_line}")
                # 中間テキストをクリア
                if hasattr(self, "_file_watcher"):
                    self._file_watcher._broadcast("interim_clear", json.dumps(
                        {"source": source}, ensure_ascii=False))
            else:
                logger.debug("空テキスト、スキップ")

        # キュー残りを処理
        while not self.transcribe_queue.empty():
            try:
                segment, timestamp, source, _ = self.transcribe_queue.get_nowait()
                file_speaker = file_labels.get(source, source)
                display_speaker = display_labels.get(source, source)
                text = self.transcriber.transcribe(segment)
                if text.strip():
                    text = self.word_replacer.apply(text, self.transcriber.language)
                    if self._is_noise_text(text):
                        continue
                    if self._should_skip_response(text, file_speaker, last_file_speaker):
                        continue
                    file_line = f"[{timestamp}] [{file_speaker}] {text}\n"
                    with open(self.output_path, "a", encoding="utf-8") as f:
                        f.write(file_line)
                        f.flush()
                    last_file_speaker = file_speaker
                    display_line = f"[{timestamp}] [{display_speaker}] {text}"
                    print(f"  {display_line}")
            except queue.Empty:
                break

    def _interim_transcribe_thread(self):
        """中間文字起こしスレッド（interim_transcription 有効時のみモデルをロード）"""
        display_labels = {"mic": t("speaker.mic"), "monitor": t("speaker.monitor")}
        interim_transcriber = None
        interim_model_name = None
        interim_ja_asr = None
        current_seq: dict[str, int] = {}  # source ごとの最新 seq

        while not self.stop_event.is_set():
            config = load_config()
            if not config.get("interim_transcription", False):
                # 無効中はモデルをロードせず待機
                self.stop_event.wait(timeout=2.0)
                continue

            # 有効化されたらモデルを遅延ロード（モデル変更時は再ロード）
            model_name = config.get("interim_model", "tiny")
            ja_asr = config.get("interim_japanese_asr_model", "default")
            if interim_transcriber is None or interim_model_name != model_name or interim_ja_asr != ja_asr:
                logger.info("中間文字起こし: %s モデル読み込み中...", model_name)
                interim_transcriber = Transcriber(
                    model_size=model_name,
                    language=self.transcriber.language,
                    initial_prompt=self.transcriber.initial_prompt,
                    beam_size=1,
                    compute_type=config.get("whisper_compute_type", "int8"),
                    device=config.get("whisper_device", "cpu"),
                    ja_asr_config_key="interim_japanese_asr_model",
                )
                interim_transcriber.load_model()
                interim_model_name = model_name
                interim_ja_asr = ja_asr
                logger.info("中間文字起こし: %s モデル読み込み完了", model_name)
            # 言語同期
            if interim_transcriber.language != self.transcriber.language:
                interim_transcriber.language = self.transcriber.language
                interim_transcriber.ensure_model_for_language()

            try:
                audio_segment, timestamp, source, seq = self.interim_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # stale チェック
            if seq < current_seq.get(source, 0):
                continue
            current_seq[source] = seq

            try:
                text = interim_transcriber.transcribe(audio_segment)
                if text.strip() and hasattr(self, "_file_watcher"):
                    speaker = display_labels.get(source, source)
                    self._file_watcher._broadcast("interim_transcript", json.dumps(
                        {"source": source, "speaker": speaker, "text": text.strip(),
                         "timestamp": timestamp}, ensure_ascii=False))
                    # リアルタイム翻訳キューに投入（最新のみ保持）
                    try:
                        self._interim_translate_queue.put_nowait(
                            (text.strip(), source, speaker, timestamp, seq))
                    except queue.Full:
                        pass
            except Exception as e:
                logger.debug("中間文字起こしエラー: %s", e)

    def _interim_translate_thread(self):
        """リアルタイム interim 翻訳スレッド"""
        current_seq: dict[str, int] = {}
        client = None
        model = None

        while not self.stop_event.is_set():
            config = load_config()
            translation_provider = get_translation_provider(config)

            if translation_provider == "libretranslate":
                lt_endpoint = config.get("libretranslate_endpoint")
                if not lt_endpoint:
                    self.stop_event.wait(timeout=2.0)
                    continue
            elif translation_provider == "api":
                if not _HAS_LLM_CLIENT:
                    self.stop_event.wait(timeout=5.0)
                    continue
                if not config.get("api_endpoint"):
                    self.stop_event.wait(timeout=2.0)
                    continue
            else:
                # claude provider → interim 翻訳なし
                self.stop_event.wait(timeout=5.0)
                continue

            try:
                text, source, speaker, timestamp, seq = self._interim_translate_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            # stale チェック
            if seq < current_seq.get(source, 0):
                continue
            current_seq[source] = seq

            lang = config.get("translate_language", "ja")

            if translation_provider == "libretranslate":
                try:
                    # spell check（有効時）
                    src_text = text
                    if config.get("libretranslate_spell_check") and _HAS_LLM_CLIENT:
                        spell_model = config.get("spell_check_model", "mbyhphat/t5-japanese-typo-correction")
                        corrected = _spell_check([text], spell_model)
                        src_text = corrected[0] if corrected else text

                    lt_api_key = config.get("libretranslate_api_key")
                    payload = {
                        "q": src_text,
                        "source": "auto",
                        "target": lang,
                        "format": "text",
                    }
                    if lt_api_key:
                        payload["api_key"] = lt_api_key
                    data = json.dumps(payload).encode("utf-8")
                    url = lt_endpoint.rstrip("/") + "/translate"
                    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        result = json.loads(resp.read().decode("utf-8"))
                    translated = result.get("translatedText", "").strip()

                    if translated and hasattr(self, "_file_watcher"):
                        self._file_watcher._broadcast("interim_translation", json.dumps(
                            {"source": source, "speaker": speaker, "text": text,
                             "translated": translated, "timestamp": timestamp},
                            ensure_ascii=False))
                except Exception as e:
                    logger.debug("interim LibreTranslate 翻訳エラー: %s", e)
            else:
                # api_model 未設定時はスキップ
                if not config.get("api_model"):
                    continue

                try:
                    # クライアント初期化（遅延）
                    if client is None:
                        llm_load_dotenv()
                        client, model = get_api_client(config)

                    glossary = load_glossary(lang)
                    system_prompt = t("llm.translate_system", lang=lang)
                    if glossary:
                        system_prompt += "\n" + glossary

                    resp = client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": f"1: {text}"},
                        ],
                        max_tokens=512,
                        temperature=0.3,
                    )
                    translated = resp.choices[0].message.content.strip()
                    # "1: " prefix を除去
                    if translated.startswith("1:"):
                        translated = translated[2:].strip()

                    if translated and hasattr(self, "_file_watcher"):
                        self._file_watcher._broadcast("interim_translation", json.dumps(
                            {"source": source, "speaker": speaker, "text": text,
                             "translated": translated, "timestamp": timestamp},
                            ensure_ascii=False))
                except SystemExit:
                    logger.debug("interim 翻訳: API 設定不足のためスキップ")
                    client = None
                except Exception as e:
                    logger.debug("interim 翻訳エラー: %s", e)
                    # API エラー時はクライアントをリセットして再接続を試みる
                    client = None

    def run(self):
        """メイン実行"""
        self._setup_signal_handlers()

        # LogBuffer をロガーに追加
        self._log_buffer = LogBuffer()
        self._log_buffer.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(self._log_buffer)

        logger.info("Shadow-clerk recorder 開始")
        logger.info("バックエンド: %s", self.backend_name)
        logger.info("出力先: %s", self.output_path)
        logger.info("モデル: %s", self.args.model)
        logger.info("言語: %s", self.args.language or "auto")
        print(t("rec.recording"))
        print(t("rec.output", path=self.output_path))

        self.mic_segmenter = VADSegmenter()
        self.monitor_segmenter = VADSegmenter()

        # PortAudio ストリーム作成の排他制御
        self._stream_lock = threading.Lock()

        threads = [
            threading.Thread(target=self._mic_capture_thread, name="mic-capture", daemon=True),
            threading.Thread(target=self._monitor_capture_thread, name="monitor-capture", daemon=True),
            threading.Thread(
                target=self._vad_thread_for_queue,
                args=(self.mic_queue, self.mic_segmenter, "mic"),
                name="vad-mic", daemon=True,
            ),
            threading.Thread(
                target=self._vad_thread_for_queue,
                args=(self.monitor_queue, self.monitor_segmenter, "monitor"),
                name="vad-monitor", daemon=True,
            ),
            threading.Thread(target=self._transcribe_thread, name="transcribe", daemon=True),
            threading.Thread(target=self._interim_transcribe_thread, name="interim-transcribe", daemon=True),
            threading.Thread(target=self._interim_translate_thread, name="interim-translate", daemon=True),
            threading.Thread(target=self._command_watch_thread, name="cmd-watch", daemon=True),
        ]

        # Push-to-Talk キーリスナー（Wayland → evdev、X11 → pynput）
        if self._voice_command_key:
            is_wayland = os.environ.get("XDG_SESSION_TYPE") == "wayland"
            if is_wayland and _HAS_EVDEV:
                threads.append(
                    threading.Thread(target=self._key_listener_thread_evdev, name="key-listener", daemon=True),
                )
            elif _HAS_PYNPUT:
                threads.append(
                    threading.Thread(target=self._key_listener_thread, name="key-listener", daemon=True),
                )
            elif _HAS_EVDEV:
                # X11 でも pynput がなければ evdev にフォールバック
                threads.append(
                    threading.Thread(target=self._key_listener_thread_evdev, name="key-listener", daemon=True),
                )
            else:
                logger.warning("Push-to-Talk に必要なパッケージがありません。"
                               " Wayland: 'uv pip install evdev' + input グループ追加、"
                               " X11: 'uv pip install pynput'")

        # ダッシュボード
        if getattr(self.args, "dashboard", True):
            self._file_watcher = FileWatcher(self, self._log_buffer)
            threads.append(self._file_watcher)

            DashboardHandler.recorder = self
            DashboardHandler.log_buffer = self._log_buffer
            DashboardHandler.file_watcher = self._file_watcher

            port = getattr(self.args, "dashboard_port", 8765)
            ThreadingHTTPServer.allow_reuse_address = True
            self._dashboard_server = ThreadingHTTPServer(("", port), DashboardHandler)
            threads.append(threading.Thread(
                target=self._dashboard_server.serve_forever,
                name="dashboard", daemon=True))
            logger.info("ダッシュボード: http://localhost:%d", port)

        for th in threads:
            th.start()

        # メインスレッドで待機
        try:
            while not self.stop_event.is_set():
                self.stop_event.wait(timeout=0.5)
        except KeyboardInterrupt:
            self.stop_event.set()

        logger.info("スレッド終了待機中...")
        for th in threads:
            th.join(timeout=5.0)

        logger.info("Shadow-clerk recorder 終了")
