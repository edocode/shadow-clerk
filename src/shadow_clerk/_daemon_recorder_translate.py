"""Shadow-clerk daemon: レコーダー翻訳・LLMクエリ ミックスイン"""
# pylint: disable=duplicate-code  # 各モジュールで必要な optional import ブロックは共通形だが抽象化不可
from __future__ import annotations
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import urllib.request

try:
    from shadow_clerk.llm_client import get_api_client, load_glossary, load_dotenv as llm_load_dotenv, _spell_check
    _HAS_LLM_CLIENT = True
except ImportError:
    _HAS_LLM_CLIENT = False

from shadow_clerk import DATA_DIR
from shadow_clerk.i18n import nt
from shadow_clerk._daemon_config import load_config, get_translation_provider
from shadow_clerk.domain import Translation
from shadow_clerk._transcript_name import TranscriptName

logger = logging.getLogger("shadow-clerk")


class _RecorderTranslateMixin:
    """翻訳ループ・中間翻訳・LLMクエリ ミックスイン"""

    def _llm_query(self, text: str) -> None:
        """LLM にクエリを投げて結果を表示・保存する（バックグラウンド実行）"""
        config = load_config()
        provider = config.get("llm_provider") or "claude"
        response_file = os.path.join(DATA_DIR, ".clerk_response")
        answer = ""
        if provider == "claude":
            try:
                from shadow_clerk._llm_config import call_claude_cli
                answer = call_claude_cli(text, nt("llm.query_system"), config).strip()
            except Exception as e:
                logger.error("LLM クエリ (claude) 失敗: %s", e)
                return
        else:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "shadow_clerk.llm_client", "query", text],
                    capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=60,
                )
                if result.returncode != 0:
                    logger.error("LLM クエリエラー: %s", result.stderr.strip())
                    return
                answer = result.stdout.strip()
            except subprocess.TimeoutExpired:
                logger.error("LLM クエリがタイムアウトしました")
                return
            except Exception as e:
                logger.error("LLM クエリ失敗: %s", e)
                return
        if answer:
            logger.info("[LLM] %s", answer)
            try:
                with open(response_file, "w", encoding="utf-8") as f:
                    f.write(answer)
                logger.info("LLM 回答を .clerk_response に保存")
            except OSError as e:
                logger.warning("LLM 回答の保存に失敗: %s", e)

    @staticmethod
    def _translate_offset_file(transcript_path: str) -> str:
        """transcript パスに対応する翻訳 offset ファイルパスを返す。

        例: /path/to/transcript-20260301.txt → /path/to/transcript-20260301.txt.translate_offset
        """
        return transcript_path + ".translate_offset"

    @staticmethod
    def _aligned_chunk_end(path: str, offset: int, chunk_limit: int, size: int) -> int:
        """offset からのチャンク終端バイト位置を返す。

        生バイトで切ると行・UTF-8 マルチバイト文字の途中で分断され、翻訳側で
        U+FFFD 化や行の断片化が起きるため、上限内の最後の改行に丸める。
        残量が上限内に収まる場合はそのまま size を返す。
        """
        if size - offset <= chunk_limit:
            return size
        try:
            with open(path, "rb") as f:
                f.seek(offset)
                data = f.read(chunk_limit)
        except OSError:
            return min(size, offset + chunk_limit)
        nl = data.rfind(b"\n")
        if nl < 0:
            # 上限内に改行がない（異常に長い行）場合のみ分断を許容する
            return offset + chunk_limit
        return offset + nl + 1

    def _translate_loop(self, target_transcript: str | None = None,
                        stop_event: threading.Event | None = None) -> None:
        """翻訳ループスレッド (llm_provider: api 用)

        target_transcript が指定されている場合、そのファイルを一括翻訳して終了する。
        指定がない場合は self.output_path を継続的にポーリングする。

        stop_event はスレッド起動ごとに専用インスタンスを渡すこと。共有の
        self._translate_stop_event を直接参照すると、stop→再起動時の clear() で
        join タイムアウト後も生きている旧スレッドが動作を再開してしまう。
        """
        if stop_event is None:
            stop_event = self._translate_stop_event
        config = load_config()
        lang = config.get("translate_language", "ja")
        one_shot = target_transcript is not None
        provider = get_translation_provider(config)
        logger.info("翻訳ループ開始: provider=%s, lang=%s%s", provider, lang,
                     f" (one-shot: {os.path.basename(target_transcript)})" if one_shot else "")
        if target_transcript:
            self.translate_target_path = target_transcript
        try:
            while not self.stop_event.is_set() and not stop_event.is_set():
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
                        # チャンク分割: 大量テキストを一度に投げないよう制限（改行境界にアライン）
                        chunk_limit = 8000  # bytes
                        effective_size = self._aligned_chunk_end(transcript, offset, chunk_limit, size)
                        # 翻訳先ファイルパスを事前計算（コンテキスト渡しに使用）
                        tn = TranscriptName.parse(os.path.basename(transcript))
                        tr_path = (
                            Translation(transcript_name=tn, language=lang, content="")
                            .file_path(os.path.dirname(transcript))
                            if tn else
                            os.path.join(os.path.dirname(transcript),
                                         os.path.basename(transcript).replace(".txt", f"-{lang}.txt"))
                        )
                        cmd = [sys.executable, "-m", "shadow_clerk.llm_client", "--verbose",
                               "translate", lang, "--file", transcript, "--offset", str(offset),
                               "--max-bytes", str(effective_size - offset)]
                        if os.path.exists(tr_path):
                            cmd += ["--context-file", tr_path]
                        result = subprocess.run(cmd, capture_output=True, text=True,
                                                encoding="utf-8", errors="replace", timeout=300)
                        if result.returncode == 0 and result.stdout.strip():
                            translation = Translation(
                                transcript_name=tn,
                                language=lang,
                                content=result.stdout,
                            ) if tn else None
                            tr_path = (
                                translation.file_path(os.path.dirname(transcript))
                                if translation else tr_path
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
                        else:
                            # stderr の末尾(traceback の本体や ERROR ログ)を出す。
                            # 先頭は --verbose の DEBUG 行で埋まることが多い。
                            stderr_tail = (result.stderr or "").strip()
                            if len(stderr_tail) > 800:
                                stderr_tail = "..." + stderr_tail[-800:]
                            stdout_excerpt = (result.stdout or "").strip()[:200]
                            logger.error("翻訳エラー (rc=%d): stderr_tail=%s%s",
                                         result.returncode, stderr_tail,
                                         f"  stdout_head={stdout_excerpt!r}" if stdout_excerpt else "")
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

                stop_event.wait(timeout=5.0)
        finally:
            self.translate_target_path = None

        logger.info("翻訳ループ終了")

    def _interim_translate_thread(self) -> None:
        """リアルタイム interim 翻訳スレッド

        プロバイダ選択順:
          1. `interim_translation_provider` 明示指定があればそれを使う
             (claude も指定可、ただし遅延 5〜10 秒で interim 向きではない)
          2. 未指定(null)のとき: `translation_provider` を踏襲。claude は
             interim には遅すぎるので api → libretranslate の順で fallback、
             どちらも無ければ interim 翻訳は無効化

        前提: `interim_transcription: true` かつ `interim_translation: true`。
        """
        current_seq: dict[str, int] = {}
        client = None
        model = None
        _logged_provider = False
        _logged_disabled = False

        while not self.stop_event.is_set():
            config = load_config()
            translation_provider = get_translation_provider(config)
            interim_translation_enabled = config.get("interim_translation", True)
            interim_transcription_enabled = config.get("interim_transcription", False)
            interim_provider_override = config.get("interim_translation_provider")

            if not interim_translation_enabled:
                if not _logged_disabled and interim_transcription_enabled:
                    logger.info("中間翻訳: 無効 (interim_translation=false)")
                    _logged_disabled = True
                self.stop_event.wait(timeout=5.0)
                continue

            if interim_provider_override:
                interim_provider = interim_provider_override
                if interim_provider == "claude" and not _logged_provider:
                    logger.warning("中間翻訳: provider=claude を明示指定 (1呼び出し 5〜10秒の遅延あり)")
            else:
                interim_provider = translation_provider
                if interim_provider == "claude":
                    if config.get("api_endpoint") and _HAS_LLM_CLIENT:
                        interim_provider = "api"
                    elif config.get("libretranslate_endpoint"):
                        interim_provider = "libretranslate"
                    else:
                        if not _logged_provider:
                            if interim_transcription_enabled:
                                logger.warning(
                                    "中間翻訳は無効: translation_provider=claude は遅延が大きく "
                                    "interim 用途に使えません。`libretranslate_endpoint` または "
                                    "`api_endpoint`+`api_model` を設定するか、"
                                    "`interim_translation_provider: claude` で明示指定してください "
                                    "(遅延承知の場合)。中間翻訳が不要なら "
                                    "`interim_translation: false` で警告を抑制可")
                            _logged_provider = True
                        self.stop_event.wait(timeout=5.0)
                        continue

            if not _logged_provider:
                src = (f"interim_translation_provider={interim_provider_override}" if interim_provider_override
                       else f"translation_provider={translation_provider}")
                logger.info("中間翻訳スレッド開始: provider=%s (%s)", interim_provider, src)
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
            # claude は call_claude_cli が内部で claude バイナリを解決するので
            # ここでの事前チェックは不要

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
            elif interim_provider == "claude":
                # claude_cli は遅いが明示指定された場合のみ呼ぶ
                try:
                    from shadow_clerk._llm_config import call_claude_cli
                    glossary = load_glossary(lang)
                    system_prompt = nt("llm.translate_system", lang=lang, hiragana_step="")
                    if glossary:
                        system_prompt += "\n" + glossary
                    translated = call_claude_cli(f"1: {text}", system_prompt, config).strip()
                    if translated.startswith("1:"):
                        translated = translated[2:].strip()
                    if translated and hasattr(self, "_file_watcher"):
                        self._file_watcher._broadcast("interim_translation", json.dumps(
                            {"source": source, "speaker": speaker, "text": text,
                             "translated": translated, "timestamp": timestamp},
                            ensure_ascii=False))
                except Exception as e:
                    logger.warning("中間翻訳エラー (claude): %s", e)
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
                    system_prompt = nt("llm.translate_system", lang=lang, hiragana_step="")
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
