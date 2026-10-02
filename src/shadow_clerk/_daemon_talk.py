"""Shadow-clerk daemon: Claude talk mode（音声で Claude と議論する）

[自分] 行を常駐 claude に送り、応答を [Claude] 行として transcript に書きつつ読み上げる。
"""
from __future__ import annotations

import datetime
import logging
import re
import threading
from typing import Any, Callable

from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_talk_claude import ClaudeTalkProcess, build_claude_argv
from shadow_clerk._daemon_talk_prompt import (
    INTERRUPT_NOTE, KICKOFF_MESSAGE, build_system_prompt, filler_phrase, requested_language,
    resolve_talk_language)
from shadow_clerk._daemon_tts import TtsBackend, TtsError, TtsPlayer, make_backend, make_player
from shadow_clerk.domain import Language, Speaker, TalkPersona, TalkVoice, TranscriptLine
from shadow_clerk.domain.ai_assistant import AiAssistantConfig
from shadow_clerk.i18n import t

logger = logging.getLogger("shadow-clerk")


class TalkStartError(Exception):
    """talk mode を開始できなかった。メッセージはそのままユーザーに見せる"""


def one_line(text: str) -> str:
    """transcript の1行形式を壊さないよう、改行と連続空白を1つの空白にまとめる"""
    return " ".join(text.split())


def now_timestamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stop_pattern(words: object) -> re.Pattern[str] | None:
    """制止の言葉の照合パターン。英数字の語は単語単位で照合する（"wait" が "waiter" に当たらないように）"""
    if not isinstance(words, list):
        return None
    alts = [rf"\b{re.escape(w)}\b" if w.isascii() else re.escape(w)
            for w in (str(x).strip() for x in words) if w]
    return re.compile("|".join(alts), re.IGNORECASE) if alts else None


class TalkDriver:
    def __init__(self, write_line: Callable[[TranscriptLine], None], *,
                 config_loader: Callable[[], dict] = load_config,
                 backend_factory: Callable[[dict, TalkVoice | None], TtsBackend] = make_backend,
                 player_factory: Callable[[TtsBackend, dict, Callable[[str], None]], TtsPlayer] = make_player,
                 process_factory: Callable[..., ClaudeTalkProcess] = ClaudeTalkProcess,
                 clock: Callable[[], str] = now_timestamp) -> None:
        self._write_line = write_line
        self._config_loader = config_loader
        self._backend_factory = backend_factory
        self._player_factory = player_factory
        self._process_factory = process_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._active = False
        self._busy = False
        self._pending: list[str] = []
        self._proc: Any = None
        self._player: Any = None
        self._topic = ""
        self._persona: TalkPersona | None = None
        self._language = ""
        self._credit = ""
        self._error = ""
        self._lang = Language.JA
        self._filler_sec = 0.0
        self._stop_re: re.Pattern[str] | None = None
        self._turn = 0                # claude に送るたびに進める。古いつなぎのタイマーを無効にする
        self._spoke = False           # このターンで claude が何か話したか
        self._interrupted = False     # 制止されたターン。終わるまで claude の発話を捨てる

    # --- ライフサイクル ---

    def start(self, topic: str, persona: str | None) -> None:
        with self._lock:
            if self._active:
                return
            config = self._config_loader()
            backend = self._backend_factory(config, None)
            try:
                backend.check()
            except TtsError as e:
                raise TalkStartError(str(e)) from e
            lang = resolve_talk_language(requested_language(config), backend)
            chosen = TalkPersona.resolve(TalkPersona.all_from_config(config.get("talk_personas")),
                                         persona, config.get("talk_default_persona"))
            argv = build_claude_argv(config, build_system_prompt(lang, chosen, topic))
            workdir = AiAssistantConfig.from_config(config).resolve_workdir()
            player = self._player_factory(backend, config, self._report_error)
            proc = self._process_factory(argv, workdir, self._on_text, self._on_turn_end, self._on_exit)
            try:
                proc.start()
            except OSError as e:
                player.close()
                raise TalkStartError(t("talk.claude_start_failed", error=str(e))) from e
            self._proc, self._player = proc, player
            self._topic, self._persona, self._language = topic, chosen, lang.value
            self._credit, self._error = backend.credit(), ""
            self._lang = lang
            self._filler_sec = float(config.get("talk_filler_sec") or 0)
            self._stop_re = stop_pattern(config.get("talk_stop_words"))
            self._pending.clear()
            self._interrupted = False
            self._active = True
            self._send_locked(KICKOFF_MESSAGE)
            logger.info("talk: 開始 (topic=%r, persona=%s, language=%s)",
                        topic, chosen.name if chosen else "-", lang.value)

    def stop(self) -> None:
        with self._lock:
            if not self._active:
                return
            self._active = False
            proc, player = self._proc, self._player
            self._proc = self._player = None
        # 子の終了待ちと再生の後始末はロックの外で。待つ間も on_self_line を止めない
        proc.stop()
        player.close()
        logger.info("talk: 終了")

    # --- Recorder から ---

    @property
    def active(self) -> bool:
        return self._active

    def is_suppressed(self, source: str) -> bool:
        """この source の文字起こしを捨てるか。フェーズ1は talk mode 中の monitor（Claude の声）"""
        return self._active and source == "monitor"

    def on_self_line(self, line: TranscriptLine) -> None:
        with self._lock:
            if not self._active:
                return
            text = line.text
            if self._stop_re is not None and self._stop_re.search(text):
                text = self._interrupt_locked(text)
            if self._busy:
                self._pending.append(text)
            else:
                self._send_locked(text)

    def _interrupt_locked(self, text: str) -> str:
        """読み上げを止め、生成中ならこのターンの残りを捨てる。claude に送る文（注記つき）を返す"""
        cut = self._player.interrupt()
        self._spoke = True  # 止めたあとにつなぎを挟まない
        if self._busy:
            self._interrupted = True
        logger.info("talk: 制止で読み上げを停止 (%r)", cut)
        return f"{INTERRUPT_NOTE.format(cut=cut)}\n{text}" if cut or self._busy else text

    def _send_locked(self, text: str) -> None:
        self._busy = True
        self._turn += 1
        self._spoke = False
        self._proc.send(text)
        if self._filler_sec > 0:
            timer = threading.Timer(self._filler_sec, self._filler, args=(self._turn,))
            timer.daemon = True
            timer.start()

    def _filler(self, turn: int) -> None:
        with self._lock:
            if not (self._active and self._busy and turn == self._turn and not self._spoke):
                return
            player, phrase = self._player, filler_phrase(self._lang)
        player.speak(phrase)

    # --- 出力 ---

    def say(self, text: str) -> None:
        """[Claude] 行を書いて読み上げる。talk mode でなければ一時的な再生器を使う"""
        text = one_line(text)
        if not text:
            return
        self._write_line(TranscriptLine(self._clock(), Speaker.CLAUDE, text))
        with self._lock:
            player = self._player
        if player is not None:
            player.speak(text)
            return
        config = self._config_loader()
        self._speak_once(self._backend_factory(config, None), config, text)

    def preview(self, voice: TalkVoice, text: str) -> None:
        """その声で1回だけ読み上げる（声の設定の試聴）。transcript には書かない。届かなければ TtsError"""
        config = self._config_loader()
        backend = self._backend_factory(config, voice)
        backend.check()
        self._speak_once(backend, config, text)

    def voices(self) -> list[dict]:
        """TTS の話者一覧。届かなければ TtsError"""
        return self._backend_factory(self._config_loader(), None).voices()

    def _speak_once(self, backend: TtsBackend, config: dict, text: str) -> None:
        player = self._player_factory(backend, config, self._report_error)
        player.speak(text)
        threading.Thread(target=player.close, kwargs={"discard_pending": False},
                         name="talk-say", daemon=True).start()

    def _on_text(self, text: str) -> None:
        """claude の text ブロック。ターンの途中でもすぐ話す（ツール実行前の「ちょっと考えます」など）"""
        with self._lock:
            if not self._active or self._interrupted:
                return
            self._spoke = True
        self.say(text)

    def _on_turn_end(self, ok: bool) -> None:
        with self._lock:
            if not self._active:
                return
            self._interrupted = False
            batch = "\n".join(self._pending)
            self._pending.clear()
            if batch:
                self._send_locked(batch)
            else:
                self._busy = False

    def _on_exit(self, code: int | None) -> None:
        self._report_error(t("talk.claude_exited", code=code))
        self.stop()

    def _report_error(self, message: str) -> None:
        self._error = message

    def snapshot(self) -> dict:
        return {"active": self._active, "topic": self._topic,
                "persona": self._persona.name if self._persona else "",
                "language": self._language, "credit": self._credit, "error": self._error}
