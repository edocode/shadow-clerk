"""Shadow-clerk daemon: レコーダー文字起こし・実行ループ ミックスイン

翻訳ループ・中間翻訳・LLMクエリは _daemon_recorder_translate.py 参照。
"""
from __future__ import annotations
import json
import logging
import os
import queue
import re
import threading
from http.server import ThreadingHTTPServer
from typing import Any

from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import (
    SAMPLE_RATE, SESSION_FILE,
    _HAS_PYNPUT, _HAS_EVDEV,
)
from shadow_clerk._daemon_config import load_config

from shadow_clerk._daemon_vad import VADSegmenter
from shadow_clerk._daemon_transcriber import Transcriber
from shadow_clerk._daemon_dashboard import LogBuffer, FileWatcher, DashboardHandler
from shadow_clerk.domain import Speaker, TranscriptLine

logger = logging.getLogger("shadow-clerk")


class _RecorderTranscribeMixin:
    """文字起こし・実行ループ ミックスイン"""

    # 短いノイズ語フィルタ: 3文字以内、かな/カナ開始、小書きかな/カナ終了
    _SMALL_KANA = set("ぁぃぅぇぉっゃゅょゎゕゖァィゥェォッャュョヮヵヶ")
    _KANA_START = re.compile(r"^[\u3041-\u3096\u30A1-\u30F6]")
    # 半濁音 + ン/ん パターン（「ピン」「プン」等の効果音）
    _HANDAKUON_N = re.compile(r"^[パピプペポぱぴぷぺぽ][ンん]$")
    # 単独のかな/カナ（「あ」「い」「フ」等）
    _SINGLE_KANA = re.compile(r"^[\u3041-\u3096\u30A1-\u30F6]$")
    # 同じかなの繰り返し（「フフ」「ハハ」「ああ」等の笑い声・フィラー）
    _REPEATED_KANA = re.compile(r"^([\u3041-\u3096\u30A1-\u30F6])\1+$")
    # 短いフィラー語（「はあ」「ふう」等）
    _SHORT_FILLERS = frozenset({
        "はあ", "はぁ", "ハア", "ハァ",
        "ふう", "ふぅ", "フウ", "フゥ",
        "ほう", "ほぅ", "ホウ", "ホゥ",
    })
    # 末尾句読点（Whisper が付加することがある）
    _TRAILING_PUNCT = re.compile(r"[。、！？\.,!?\s]+$")

    @staticmethod
    def _is_noise_text(text: str) -> bool:
        """短いノイズ語（「あっ」「ピッ」「ピン」「フフ」「はあ」「あ」等）かどうか判定"""
        s = _RecorderTranscribeMixin._TRAILING_PUNCT.sub("", text.strip())
        if len(s) > 3 or len(s) == 0:
            return False
        if _RecorderTranscribeMixin._KANA_START.match(s) and s[-1] in _RecorderTranscribeMixin._SMALL_KANA:
            return True
        if _RecorderTranscribeMixin._HANDAKUON_N.match(s):
            return True
        if _RecorderTranscribeMixin._SINGLE_KANA.match(s):
            return True
        if _RecorderTranscribeMixin._REPEATED_KANA.match(s):
            return True
        if s in _RecorderTranscribeMixin._SHORT_FILLERS:
            return True
        return False

    @staticmethod
    def _should_skip_response(text: str, file_speaker: Speaker, last_speaker: Speaker | None) -> bool:
        """「はい」「いいえ」などの相手にたいする応答のみの発話を、直前が同じ話者の場合スキップ"""
        s = text.strip()
        if s not in ("はい", "いいえ", "ああ", "うん", "はー", "ひー", "ふー", "へー", "ほー", "あー", "いー", "うー", "えー", "おー"):
            return False
        # 直前の話者が別人なら記録する（= スキップしない）
        if last_speaker is not None and last_speaker != file_speaker:
            return False
        # 直前が同じ話者 or 不明 → スキップ
        return True

    def _process_transcribe_item(self, segment: Any, timestamp: str, source: str,
                                 command_mode: bool, display_labels: dict[str, str],
                                 last_file_speaker: Speaker | None) -> Speaker | None:
        """キューから取り出した1セグメントを文字起こし・書き込みし、更新後の直前話者を返す"""
        # ミュート中のソースはスキップ（ただしコマンドモード中は除く）
        is_muted = (source == "mic" and self.mute_mic) or (source == "monitor" and self.mute_monitor)
        if is_muted and not command_mode:
            logger.debug("%s ミュート中、スキップ", source)
            return last_file_speaker

        duration = len(segment) / SAMPLE_RATE
        display_speaker = display_labels.get(source, source)
        logger.info("文字起こし中 (%s, %.1f秒)...", display_speaker, duration)

        text = self.transcriber.transcribe(segment)
        if not text.strip():
            logger.debug("空テキスト、スキップ")
            return last_file_speaker

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
                return last_file_speaker
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
                return last_file_speaker

        # 日付変更チェック（セッション中でなく、明示的 output 指定でない場合のみ）
        if not self._explicit_output and not os.path.exists(SESSION_FILE):
            new_path = self._get_default_output()
            if new_path != self.output_path:
                logger.info("日付変更検出、出力先切り替え: %s", new_path)
                self.output_path = new_path

        text = self.word_replacer.apply(text, self.transcriber.language)
        file_speaker = Speaker.from_source(source)

        # ノイズフィルタ: 短い感嘆語（「あっ」「ピッ」等）
        if self._is_noise_text(text):
            logger.debug("ノイズフィルタ: %r をスキップ", text.strip())
            return last_file_speaker
        # はい/いいえフィルタ: 直前が同じ話者ならスキップ
        if self._should_skip_response(text, file_speaker, last_file_speaker):
            logger.debug("応答フィルタ: %r (speaker=%s) をスキップ", text.strip(), file_speaker)
            return last_file_speaker

        tl = TranscriptLine(timestamp=timestamp, speaker=file_speaker, text=text)
        with self.transcript_lock:
            with open(self.output_path, "a", encoding="utf-8") as f:
                f.write(tl.format())
                f.flush()
        display_line = f"[{timestamp}] [{display_speaker}] {text}"
        print(f"  {display_line}")
        # 中間テキストをクリア
        if hasattr(self, "_file_watcher"):
            self._file_watcher._broadcast("interim_clear", json.dumps(
                {"source": source}, ensure_ascii=False))
        return file_speaker

    def _transcribe_thread(self) -> None:
        """文字起こしスレッド"""
        logger.info("文字起こしスレッド開始")
        self.transcriber.load_model()

        # ターミナル表示用ラベル（i18n 対応）
        display_labels = {"mic": t("speaker.mic"), "monitor": t("speaker.monitor")}
        last_file_speaker: Speaker | None = None  # 直前に書き込んだ話者（はい/いいえフィルタ用）

        while not self.stop_event.is_set():
            try:
                segment, timestamp, source, command_mode = self.transcribe_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                last_file_speaker = self._process_transcribe_item(
                    segment, timestamp, source, command_mode, display_labels, last_file_speaker)
            except Exception:
                # ここでスレッドが死ぬと以降の文字起こしが無言で全停止するため、
                # セグメント単位でエラーを記録して継続する
                logger.exception("文字起こし処理でエラー、セグメントをスキップして継続します")

        # キュー残りを処理（VAD スレッドの flush がまだ put していない可能性があるため猶予付き）
        while True:
            try:
                segment, timestamp, source, _ = self.transcribe_queue.get(timeout=2.0)
            except queue.Empty:
                break
            try:
                file_speaker = Speaker.from_source(source)
                display_speaker = display_labels.get(source, source)
                text = self.transcriber.transcribe(segment)
                if text.strip():
                    text = self.word_replacer.apply(text, self.transcriber.language)
                    if self._is_noise_text(text):
                        continue
                    if self._should_skip_response(text, file_speaker, last_file_speaker):
                        continue
                    tl = TranscriptLine(timestamp=timestamp, speaker=file_speaker, text=text)
                    with self.transcript_lock:
                        with open(self.output_path, "a", encoding="utf-8") as f:
                            f.write(tl.format())
                            f.flush()
                    last_file_speaker = file_speaker
                    display_line = f"[{timestamp}] [{display_speaker}] {text}"
                    print(f"  {display_line}")
            except Exception:
                logger.exception("終了時の文字起こし処理でエラー、スキップします")

    def _interim_transcribe_thread(self) -> None:
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
                    label="interim",
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

    def run(self) -> None:
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
        from shadow_clerk import is_microsoft_store_python
        if is_microsoft_store_python():
            logger.warning(
                "Microsoft Store 版 Python を検出。データディレクトリは "
                "AppContainer サンドボックス内 (%LOCALAPPDATA%\\Packages\\"
                "PythonSoftwareFoundation.Python.X.YY_*\\LocalCache\\Roaming\\"
                "shadow-clerk) に作られ、Python マイナーバージョンが変わると "
                "別パスに移ります。uv 管理 Python (`uv python install` + "
                "`uv tool install --python 3.13 ...`) か python.org 版 Python "
                "の使用を推奨。SHADOW_CLERK_DATA_DIR で固定パスへ強制も可")
        print(t("rec.recording"))
        print(t("rec.output", path=self.output_path))

        self.mic_segmenter = VADSegmenter()
        self.monitor_segmenter = VADSegmenter()

        threads = [
            threading.Thread(target=self._audio_capture_thread, name="audio-capture", daemon=True),
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

            class _QuietServer(ThreadingHTTPServer):
                def handle_error(self, request, client_address):
                    # ブラウザの接続切断は害がないので、ConnectionError 系は静かに無視する
                    import sys as _sys
                    exc = _sys.exc_info()[1]
                    if isinstance(exc, (ConnectionError, BrokenPipeError, TimeoutError)):
                        logger.debug("dashboard 接続切断: %s", exc)
                        return
                    super().handle_error(request, client_address)

            self._dashboard_server = _QuietServer(("", port), DashboardHandler)
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
        # monitor-backend は遅延起動で threads に載らないが、join しないと
        # pw-record/parec の子プロセスが finally を通らず取り残される
        for th in threads + [self._monitor_backend]:
            if th is not None:
                th.join(timeout=5.0)

        logger.info("Shadow-clerk recorder 終了")
