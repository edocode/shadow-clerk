"""Shadow-clerk daemon: Claude talk mode（音声で Claude と議論する）

[自分] 行を engine（会話の担い手）に渡し、engine の応答を [Claude] 行として transcript に書きつつ読み上げる。
TTS・monitor の抑制・制止・つなぎの一言はここが持つ。
"""
from __future__ import annotations

import datetime
import logging
import os
import re
import threading
import time
from collections import deque
from typing import Any, Callable

from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_talk_engine import TalkContext, TalkEngine, TalkStartError, make_engine
from shadow_clerk._daemon_talk_route import TalkRoute, make_route
from shadow_clerk._daemon_talk_prompt import filler_phrase, requested_language, resolve_talk_language
from shadow_clerk._daemon_talk_speech import BrowserSpeech
from shadow_clerk._daemon_tts import TtsBackend, TtsError, TtsPlayer, make_backend, make_player
from shadow_clerk._daemon_tts_pipewire import PwCatSink
from shadow_clerk.domain import (EchoFilter, Language, SpeechTab, SpokenSpan, Speaker, TalkPersona, TalkVoice,
                                 TranscriptLine)
from shadow_clerk.domain.ai_assistant import AiAssistantConfig
from shadow_clerk.i18n import t

__all__ = ["TalkDriver", "TalkStartError", "one_line", "now_timestamp", "stop_pattern", "resolve_talk_workdir"]

logger = logging.getLogger("shadow-clerk")

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


def _line_texts(lines: list[TranscriptLine]) -> list[str]:
    return [tl.format().rstrip("\n") for tl in lines]


def _float_setting(config: dict, key: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(config.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if lo <= value <= hi else default


def resolve_talk_workdir(config: dict, requested: str | None) -> str:
    """会話役の作業ディレクトリ。開始時の指定 → talk_workdir → ai_assistant_workdir → ホーム。

    開始時に明示された場所が無いときは黙ってホームに落とさない。違うリポジトリで作業を始めてしまうため
    """
    if requested and requested.strip():
        path = os.path.expanduser(requested.strip())
        if not os.path.isdir(path):
            raise TalkStartError(t("talk.workdir_missing", path=path))
        return path
    return AiAssistantConfig.from_config(config).resolve_workdir(str(config.get("talk_workdir") or ""))


# つなぎどうしの最短間隔（秒）。返事待ちのたびに挟むと、うるさく同じ言葉が続いて聞こえる
FILLER_COOLDOWN_SEC = 30.0
# 中間文字起こしがこの秒数更新されなければ話し終えたとみなす（確定行が捨てられて消されなかったときの保険）
SPEAKING_STALE_SEC = 4.0
_FLOOR_POLL_SEC = 0.1
_HEARD_LINES_MAX = 20  # 待つ間に届いた発言として返す最大行数

class TalkDriver:
    def __init__(self, write_line: Callable[[TranscriptLine], None], *,
                 config_loader: Callable[[], dict] = load_config,
                 backend_factory: Callable[[dict, TalkVoice | None], TtsBackend] = make_backend,
                 player_factory: Callable[[TtsBackend, dict, Callable[[str], None]], TtsPlayer] = make_player,
                 engine_factory: Callable[[str], TalkEngine] = make_engine,
                 route_factory: Callable[[], TalkRoute] = make_route,
                 sink_factory: Callable[[], Any] = PwCatSink,
                 clock: Callable[[], str] = now_timestamp,
                 speech: BrowserSpeech | None = None) -> None:
        self._write_line = write_line
        self._config_loader = config_loader
        self._backend_factory = backend_factory
        self._player_factory = player_factory
        self._engine_factory = engine_factory
        self._route_factory = route_factory
        self._sink_factory = sink_factory
        self._clock = clock
        self._speech = speech or BrowserSpeech()
        self._lock = threading.Lock()
        self._active = False
        self._engine: Any = None
        self._engine_name = ""
        self._player: Any = None
        self._route: Any = None
        self._sink: Any = None
        self._echo = EchoFilter()
        self._topic = ""
        self._persona: TalkPersona | None = None
        self._lang = Language.JA
        self._language = ""
        self._workdir = ""
        self._credit = ""
        self._error = ""
        self._filler_sec = 0.0
        self._stop_re: re.Pattern[str] | None = None
        self._said = 0  # 話した回数。つなぎのタイマーが「その後に話したか」を見る
        self._filler_said = -1  # 最後につなぎを挟んだときの _said。1回の返事待ちに1回まで
        self._filler_at = float("-inf")  # 最後につなぎを挟んだ時刻（monotonic）
        self._filler_last = ""
        self._floor_wait_sec = 0.0
        self._heard: dict[str, float] = {}  # source → 中間文字起こしに文字が出た最後の時刻（monotonic）
        self._lines_seen = 0  # talk mode 中に届いた [自分]・[相手] 行の数
        self._recent_lines: deque[TranscriptLine] = deque(maxlen=_HEARD_LINES_MAX)

    def start(self, topic: str, persona: str | None, workdir: str | None = None,
              route: str | None = None) -> None:
        with self._lock:
            if self._active:
                return
            config = self._config_loader()
            resolved = resolve_talk_workdir(config, workdir)
            backend = self._backend_factory(config, None)
            try:
                backend.check()
            except TtsError as e:
                raise TalkStartError(str(e)) from e
            lang = resolve_talk_language(requested_language(config), backend)
            chosen = TalkPersona.resolve(TalkPersona.all_from_config(config.get("talk_personas")),
                                         persona, config.get("talk_default_persona"))
            route_obj, sink = None, None
            if route:
                route_obj = self._route_factory()
                if not route_obj.available():
                    raise TalkStartError(t("talk.route_unavailable"))
                sink = self._sink_factory()
                try:
                    source_port = sink.start()
                except TtsError as e:
                    raise TalkStartError(str(e)) from e
                player = TtsPlayer(backend, sink.play, self._report_error)
            else:
                player = self._player_factory(backend, config, self._report_error)
                player.set_remote(self._speech)  # 練習言語の文はダッシュボードのブラウザで読む（届け先ありでは使わない）
            echo = EchoFilter(tail_sec=_float_setting(config, "talk_echo_tail_sec", 0.3, 0.0, 30.0))
            player.set_on_played(lambda text, s, e: echo.record(SpokenSpan(s, e, text)))
            name = "headless" if config.get("talk_engine") == "headless" else "console"
            try:
                if route_obj is not None:
                    route_obj.connect(route, source_port)
                engine = self._engine_factory(name)
                engine.start(TalkContext(topic, chosen, lang, resolved, config,
                                         self._engine_say, self._engine_ended))
            except Exception:
                if route_obj is not None:
                    route_obj.disconnect()
                if sink is not None:
                    sink.stop()  # play スレッドが pw-cat への書き込みで詰まっていても、先に止めれば close が待たされない
                player.close()
                raise
            self._engine, self._engine_name, self._player = engine, name, player
            self._route, self._sink, self._echo = route_obj, sink, echo
            self._topic, self._persona, self._lang = topic, chosen, lang
            self._language, self._workdir = lang.value, resolved
            self._credit, self._error = backend.credit(), ""
            self._filler_sec = float(config.get("talk_filler_sec") or 0)
            self._floor_wait_sec = _float_setting(config, "talk_floor_wait_sec", 10.0, 0.0, 60.0)
            self._stop_re = stop_pattern(config.get("talk_stop_words"))
            self._active = True  # つなぎは [自分] 行のあとだけ。口火の前に挟むと最初の質問より先に話してしまう
            logger.info("talk: 開始 (engine=%s, topic=%r, persona=%s, language=%s)",
                        name, topic, chosen.name if chosen else "-", lang.value)

    def stop(self, player: Any = None) -> None:
        """talk mode を終える。player を渡すと、その再生器の会話のときだけ終える"""
        with self._lock:
            if not self._active or (player is not None and self._player is not player):
                return
            self._active = False
            engine, player = self._engine, self._player
            route, sink = self._route, self._sink
            self._engine = self._player = self._route = self._sink = None
        # engine の後始末（子の終了待ち）と再生の後始末はロックの外で
        engine.stop()
        if route is not None:
            route.disconnect()
        if sink is not None:
            sink.stop()  # player.close の前に止める（play スレッドの書き込み待ちを解く）
        player.close()
        logger.info("talk: 終了")

    def route_targets(self) -> dict:
        """届ける先の候補。同じアプリの録音ストリームは1つにまとめる（つなぐときはアプリ単位）"""
        route = self._route_factory()
        if not route.available():
            return {"available": False, "targets": []}
        seen: dict[str, str] = {}
        for target in route.targets():
            seen.setdefault(target.app, target.label)
        return {"available": True, "targets": [{"app": a, "label": label} for a, label in seen.items()]}

    @property
    def active(self) -> bool:
        return self._active

    @property
    def routed(self) -> bool:
        """届け先ありの talk mode か。会議のほかの参加者に声が届く"""
        return self._active and self._route is not None

    def on_interim(self, source: str) -> None:
        """中間文字起こしに文字が出た。確定行の処理（clear_interim）か SPEAKING_STALE_SEC の無更新で消える"""
        self._heard[source] = time.monotonic()

    def clear_interim(self, source: str) -> None:
        self._heard.pop(source, None)

    def speaking(self) -> list[str]:
        """中間文字起こしに文字が出ている source。transcript の確定行を待つより早く「話している」と分かる"""
        now = time.monotonic()
        return sorted(s for s, at in list(self._heard.items()) if now - at < SPEAKING_STALE_SEC)

    def is_suppressed(self, source: str) -> bool:
        """この source の文字起こしを捨てるか。届け先が無い talk mode の monitor（Claude の声しか来ない）"""
        return self._active and source == "monitor" and self._route is None

    def is_echo(self, source: str, seg_start: float, seg_end: float, text: str) -> bool:
        """届け先ありの talk mode で、monitor の区間が Claude の読み上げ中（終了後 tail まで）か。text は使わない（時間だけで判定）"""
        if not (self._active and source == "monitor" and self._route is not None):
            return False
        return self._echo.overlaps(seg_start, seg_end)

    def hides_interim(self, source: str, seg_start: float, seg_end: float) -> bool:
        """中間文字起こしを出さないか。Claude の声が混ざる monitor の区間（確定行は is_echo で別に判定する）"""
        return self.is_suppressed(source) or (
            self._active and source == "monitor" and self._route is not None
            and self._echo.overlaps(seg_start, seg_end))

    def on_other_line(self, line: TranscriptLine) -> None:
        """[相手] 行が書かれた。発言を待たせている間に届いたかを数えるだけ"""
        with self._lock:
            if self._active:
                self._note_line_locked(line)

    def _note_line_locked(self, line: TranscriptLine) -> None:
        self._lines_seen += 1
        self._recent_lines.append(line)

    def on_self_line(self, line: TranscriptLine) -> None:
        with self._lock:
            if not self._active:
                return
            self._note_line_locked(line)
            engine = self._engine
            if self._stop_re is not None and self._stop_re.search(line.text):
                busy = self._player.is_busy()
                cut = self._player.interrupt() if busy else ""
                self._said += 1  # 止めたあとにつなぎを挟まない
                if busy or engine.wants_idle_interrupt:
                    engine.on_interrupt(cut)
                logger.info("talk: 制止 (busy=%s, cut=%r)", busy, cut)
            else:
                self._arm_filler_locked()
        engine.on_self_line(line.text)

    def api_say(self, text: str, lang: Language | None = None, display: str | None = None) -> dict:
        """/api/say の応答。制止の直後（console engine）なら話さずに止めた文を、
        相手が話し終えるのを待つ間に発言が届いたら話さずにその発言を返す"""
        with self._lock:
            if self._active:
                cut = self._engine.consume_interrupt()
                if cut is not None:
                    return {"status": "interrupted", "cut": cut}
                self._said += 1
        heard = self.say(text, lang, display)
        return {"status": "held", "heard": _line_texts(heard)} if heard else {"status": "ok"}

    def _engine_say(self, text: str) -> None:
        with self._lock:
            if not self._active:
                return
            self._said += 1
            engine = self._engine
        heard = self.say(text)
        if heard:
            engine.on_held(text, _line_texts(heard))

    def end_after_speech(self, timeout: float = 30.0) -> bool:
        """読み上げ中の文を言い終えてから talk mode を終える。待たずに返る。talk mode 外なら False

        talk の skill が自分から会話を終えるときに使う。すぐ止めると締めの言葉が途中で切れ、
        呼んだ子プロセス自身もその場で終了させられて応答を受け取れない
        """
        with self._lock:
            if not self._active:
                return False
            player = self._player
        threading.Thread(target=self._end_when_quiet, args=(player, timeout),
                         name="talk-end", daemon=True).start()
        return True

    def _end_when_quiet(self, player: Any, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while player.is_busy() and time.monotonic() < deadline:
            time.sleep(0.2)
        self.stop(player)  # 待つ間にユーザーが止めて始め直した会話は終えない

    def _engine_ended(self, reason: str) -> None:
        self._report_error(reason)
        self.stop()

    def _arm_filler_locked(self) -> None:
        if self._filler_sec <= 0:
            return
        timer = threading.Timer(self._filler_sec, self._filler, args=(self._said,))
        timer.daemon = True
        timer.start()

    def _filler(self, said: int) -> None:
        with self._lock:
            if (not self._active or self._said != said or self._filler_said == said
                    or time.monotonic() - self._filler_at < FILLER_COOLDOWN_SEC or self.speaking()):
                return
            player, phrase = self._player, filler_phrase(self._lang, self._filler_last)
            self._filler_said, self._filler_at, self._filler_last = said, time.monotonic(), phrase
        player.speak(phrase)

    # --- 出力 ---

    def say(self, text: str, lang: Language | None = None, display: str | None = None) -> list[TranscriptLine]:
        """[Claude] 行を書いて読み上げる。talk mode でなければ一時的な再生器を使う

        display があれば transcript の行にはそれを書く（読むのは text。答えの綴りを見せない語学の練習用）

        lang が読み上げの言語（VOICEVOX）と違えば、その文はダッシュボードのブラウザで読む。届け先ありの talk mode
        （ブラウザの音は会議アプリに届かない）と talk mode の外（一時的な再生器）では lang を見ない
        届け先ありで相手が話し終えるのを待つ間に発言が届いたら、話題が変わったかもしれないので話さずにその発言を返す
        """
        text = one_line(text)
        if not text:
            return []
        if self.routed:
            heard = self._wait_for_floor()
            if heard is None or heard:
                return heard or []
        self._write_line(TranscriptLine(self._clock(), Speaker.CLAUDE, one_line(display or "") or text))
        with self._lock:
            player = self._player
            browser = lang if lang is not None and lang != self._lang and self._route is None else None
        if player is not None:
            player.speak(text, browser)
            return []
        config = self._config_loader()
        self._speak_once(self._backend_factory(config, None), config, text)
        return []

    def _wait_for_floor(self) -> list[TranscriptLine] | None:
        """会議のほかの参加者が話し終えるまで待つ（最長 talk_floor_wait_sec）。待つ間に届いた発言を返す。
        待つ間に talk mode が終われば None"""
        with self._lock:
            seen = self._lines_seen
        deadline = time.monotonic() + self._floor_wait_sec
        while self._active and self.speaking() and time.monotonic() < deadline:
            time.sleep(_FLOOR_POLL_SEC)
        with self._lock:
            if not self._active:
                return None
            n = self._lines_seen - seen
            return list(self._recent_lines)[-n:] if n else []

    def set_broadcaster(self, fn: Callable[[str, str], None]) -> None:
        """SSE の送り口。ダッシュボード（FileWatcher）が立ち上がってから渡される"""
        self._speech.set_broadcaster(fn)

    def speech_ready(self, tab: SpeechTab) -> None:
        self._speech.ready(tab)

    def speech_done(self, utterance_id: str) -> bool:
        return self._speech.done(utterance_id)

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

    def _report_error(self, message: str) -> None:
        self._error = message

    def snapshot(self) -> dict:
        route = self._route
        return {"active": self._active, "engine": self._engine_name, "topic": self._topic,
                "persona": self._persona.name if self._persona else "",
                "persona_instructions": self._persona.instructions if self._persona else "",
                "language": self._language, "workdir": self._workdir,
                "credit": self._credit, "error": self._error,
                "route": route.status() if route is not None else {"app": "", "connected": False}}
