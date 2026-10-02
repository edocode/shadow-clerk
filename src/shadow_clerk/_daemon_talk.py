"""Shadow-clerk daemon: Claude talk mode（音声で Claude と議論する）

[自分] 行を常駐 claude に送り、応答を [Claude] 行として transcript に書きつつ読み上げる。
"""
from __future__ import annotations

import datetime
import logging
import threading
from typing import Any, Callable

from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_talk_claude import ClaudeTalkProcess, build_claude_argv
from shadow_clerk._daemon_talk_prompt import (
    KICKOFF_MESSAGE, build_system_prompt, requested_language, resolve_talk_language)
from shadow_clerk._daemon_tts import TtsBackend, TtsError, TtsPlayer, make_backend, make_player
from shadow_clerk.domain import Speaker, TalkPersona, TalkVoice, TranscriptLine
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
            proc = self._process_factory(argv, workdir, self._on_reply, self._on_exit)
            try:
                proc.start()
            except OSError as e:
                player.close()
                raise TalkStartError(t("talk.claude_start_failed", error=str(e))) from e
            self._proc, self._player = proc, player
            self._topic, self._persona, self._language = topic, chosen, lang.value
            self._credit, self._error = backend.credit(), ""
            self._pending.clear()
            self._active = self._busy = True
            proc.send(KICKOFF_MESSAGE)
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
            if self._busy:
                self._pending.append(line.text)
                return
            self._busy = True
            proc = self._proc
        proc.send(line.text)

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

    def _on_reply(self, text: str) -> None:
        with self._lock:
            if not self._active:
                return
            batch = "\n".join(self._pending)
            self._pending.clear()
            self._busy = bool(batch)
            proc = self._proc
        if one_line(text):
            self.say(text)
        if batch:
            proc.send(batch)

    def _on_exit(self, code: int | None) -> None:
        self._report_error(t("talk.claude_exited", code=code))
        self.stop()

    def _report_error(self, message: str) -> None:
        self._error = message

    def snapshot(self) -> dict:
        return {"active": self._active, "topic": self._topic,
                "persona": self._persona.name if self._persona else "",
                "language": self._language, "credit": self._credit, "error": self._error}
