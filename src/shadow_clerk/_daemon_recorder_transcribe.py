"""Shadow-clerk daemon: レコーダー文字起こし・翻訳・実行ループ ミックスイン"""
# pylint: disable=duplicate-code  # 各モジュールで必要な optional import ブロックは共通形だが抽象化不可
from __future__ import annotations
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

try:
    from shadow_clerk.llm_client import get_api_client, load_glossary, load_dotenv as llm_load_dotenv, _spell_check
    _HAS_LLM_CLIENT = True
except ImportError:
    _HAS_LLM_CLIENT = False

from shadow_clerk import DATA_DIR
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import (
    SAMPLE_RATE, COMMAND_FILE, SESSION_FILE,
    _HAS_PYNPUT, evdev, _HAS_EVDEV,
)
from shadow_clerk._daemon_config import load_config, get_translation_provider

from shadow_clerk._daemon_vad import VADSegmenter
from shadow_clerk._daemon_transcriber import Transcriber
from shadow_clerk._daemon_dashboard import LogBuffer, FileWatcher, DashboardHandler
from shadow_clerk.domain import Speaker, TranscriptLine, Translation
from shadow_clerk._transcript_name import TranscriptName

logger = logging.getLogger("shadow-clerk")


class _RecorderTranscribeMixin:
    """文字起こし・翻訳・実行ループ ミックスイン"""

    def _llm_query(self, text: str) -> None:
        """LLM にクエリを投げて結果を表示・保存する（バックグラウンド実行）"""
        config = load_config()
        if config.get("llm_provider") == "claude":
            # Claude プロバイダ: .clerk_command 経由で Claude Code subagent に処理させる
            command_file = os.path.join(DATA_DIR, ".clerk_command")
            try:
                with open(command_file, "w", encoding="utf-8") as f:
                    f.write(f"llm_query {text}")
                logger.info("LLM クエリを .clerk_command に書き込み (claude): %s", text)
            except Exception as e:
                logger.error("LLM クエリ (.clerk_command 書き込み失敗): %s", e)
            return

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
                logger.info("[LLM] %s", answer)
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

    def _translate_loop(self, target_transcript: str | None = None) -> None:
        """翻訳ループスレッド (llm_provider: api 用)

        target_transcript が指定されている場合、そのファイルを一括翻訳して終了する。
        指定がない場合は self.output_path を継続的にポーリングする。
        """
        config = load_config()
        lang = config.get("translate_language", "ja")
        one_shot = target_transcript is not None
        provider = get_translation_provider(config)
        logger.info("翻訳ループ開始: provider=%s, lang=%s%s", provider, lang,
                     f" (one-shot: {os.path.basename(target_transcript)})" if one_shot else "")

        while not self.stop_event.is_set() and not self._translate_stop_event.is_set():
            try:
                transcript = target_transcript or self.output_path
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
                        tn = TranscriptName.parse(os.path.basename(transcript))
                        translation = Translation(
                            transcript_name=tn,
                            language=lang,
                            content=result.stdout,
                        ) if tn else None
                        tr_path = (
                            translation.file_path(os.path.dirname(transcript))
                            if translation else
                            os.path.join(os.path.dirname(transcript),
                                         os.path.basename(transcript).replace(".txt", f"-{lang}.txt"))
                        )
                        tr_name = os.path.basename(tr_path)
                        mode = "w" if offset == 0 else "a"
                        with open(tr_path, mode, encoding="utf-8") as f:
                            f.write(result.stdout)
                        with open(offset_file, "w", encoding="utf-8") as f:
                            f.write(str(effective_size))
                        logger.info("翻訳完了: %d bytes → %s", effective_size - offset, tr_name)
                        # one-shot: 全チャンク翻訳完了したら終了
                        if one_shot and effective_size >= size:
                            logger.info("one-shot 翻訳完了: %s", tr_name)
                            return
                    elif result.returncode != 0:
                        logger.error("翻訳エラー: %s", result.stderr.strip()[:200])
                        if one_shot:
                            return
                elif one_shot:
                    # one-shot でサイズ変化なし → 翻訳対象なし
                    logger.info("one-shot 翻訳: 対象テキストなし")
                    return
            except subprocess.TimeoutExpired:
                logger.error("翻訳タイムアウト")
                if one_shot:
                    return
            except Exception as e:
                logger.error("翻訳ループエラー: %s", e)
                if one_shot:
                    return

            self._translate_stop_event.wait(timeout=5.0)

        logger.info("翻訳ループ終了")

    def _command_watch_thread(self) -> None:
        """コマンドファイルをポーリングして実行するスレッド"""
        logger.info("コマンド監視スレッド開始")
        while not self.stop_event.is_set():
            try:
                if os.path.exists(COMMAND_FILE):
                    with open(COMMAND_FILE, "r", encoding="utf-8") as f:
                        cmd = f.read().strip()
                    # 翻訳コマンド: translation_provider で判定
                    _translate_prefixes = ("translate_start", "translate_stop", "translate_regenerate")
                    # 要約コマンド: llm_provider で判定 (ファイル名付き: generate_summary_full transcript-*.txt)
                    _is_translate = any(cmd == p or cmd.startswith(p + " ") for p in _translate_prefixes)
                    _is_summary = cmd.startswith("generate_summary")
                    if _is_translate:
                        config = load_config()
                        provider = get_translation_provider(config)
                        if provider in ("api", "libretranslate"):
                            os.remove(COMMAND_FILE)
                            logger.info("翻訳コマンド検出: %s (provider=%s, 内部処理)", cmd, provider)
                            self._execute_command(cmd)
                        else:
                            logger.info("翻訳コマンド検出: %s (provider=claude, subagent に委譲)", cmd)
                    elif _is_summary:
                        config = load_config()
                        llm_prov = config.get("llm_provider", "claude")
                        if llm_prov == "api":
                            os.remove(COMMAND_FILE)
                            logger.info("要約コマンド検出: %s (provider=api, 内部処理)", cmd)
                            self._execute_command(cmd)
                        else:
                            logger.info("要約コマンド検出: %s (provider=claude, subagent に委譲)", cmd)
                    elif cmd.startswith("llm_query "):
                        # llm_query は _llm_query (claude provider) が自分で COMMAND_FILE に書き込む。
                        # ここで _execute_command を呼ぶと再度書き込まれ無限ループになるため、
                        # claude provider の場合はファイルを残して Claude Code に委譲する。
                        config = load_config()
                        if config.get("llm_provider") == "claude":
                            logger.debug("LLM クエリ検出 (provider=claude, Claude Code に委譲): %s", cmd)
                        else:
                            os.remove(COMMAND_FILE)
                            logger.info("コマンドファイル検出: %s", cmd)
                            self._execute_command(cmd)
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
                file_speaker = Speaker.from_source(source)

                # ノイズフィルタ: 短い感嘆語（「あっ」「ピッ」等）
                if self._is_noise_text(text):
                    logger.debug("ノイズフィルタ: %r をスキップ", text.strip())
                    continue
                # はい/いいえフィルタ: 直前が同じ話者ならスキップ
                if self._should_skip_response(text, file_speaker, last_file_speaker):
                    logger.debug("応答フィルタ: %r (speaker=%s) をスキップ", text.strip(), file_speaker)
                    continue

                tl = TranscriptLine(timestamp=timestamp, speaker=file_speaker, text=text)
                with self.transcript_lock:
                    with open(self.output_path, "a", encoding="utf-8") as f:
                        f.write(tl.format())
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
            except queue.Empty:
                break

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

    def _interim_translate_thread(self) -> None:
        """リアルタイム interim 翻訳スレッド

        claude provider の場合は Claude Code に依頼できないため、
        api_endpoint があれば API に、libretranslate_endpoint があれば
        LibreTranslate にフォールバックする。
        """
        current_seq: dict[str, int] = {}
        client = None
        model = None
        _logged_provider = False

        while not self.stop_event.is_set():
            config = load_config()
            translation_provider = get_translation_provider(config)

            # claude provider → 中間翻訳に使えるバックエンドを探す
            interim_provider = translation_provider
            if interim_provider == "claude":
                if config.get("api_endpoint") and _HAS_LLM_CLIENT:
                    interim_provider = "api"
                elif config.get("libretranslate_endpoint"):
                    interim_provider = "libretranslate"
                else:
                    # フォールバック先なし
                    if not _logged_provider:
                        logger.info("中間翻訳: provider=claude, フォールバック先なし (api_endpoint/libretranslate 未設定)")
                        _logged_provider = True
                    self.stop_event.wait(timeout=5.0)
                    continue

            if not _logged_provider:
                logger.info("中間翻訳スレッド開始: provider=%s%s",
                            interim_provider,
                            f" (translation_provider={translation_provider} からフォールバック)" if interim_provider != translation_provider else "")
                _logged_provider = True

            if interim_provider == "libretranslate":
                lt_endpoint = config.get("libretranslate_endpoint")
                if not lt_endpoint:
                    self.stop_event.wait(timeout=2.0)
                    continue
            elif interim_provider == "api":
                if not _HAS_LLM_CLIENT:
                    self.stop_event.wait(timeout=5.0)
                    continue
                if not config.get("api_endpoint"):
                    self.stop_event.wait(timeout=2.0)
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

            if interim_provider == "libretranslate":
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
                    logger.warning("中間翻訳エラー (libretranslate): %s", e)
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
                    system_prompt = t("llm.translate_system", lang=lang, hiragana_step="")
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
                    logger.warning("中間翻訳: API 設定不足のためスキップ (provider=api)")
                    client = None
                except Exception as e:
                    logger.warning("中間翻訳エラー (api): %s", e)
                    # API エラー時はクライアントをリセットして再接続を試みる
                    client = None

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
