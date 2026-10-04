"""Shadow-clerk daemon: 練習言語の文をダッシュボードのブラウザで読み上げる

VOICEVOX は日本語の声なので、英語などの文はダッシュボードのタブの speechSynthesis で読む。
daemon は最後に名乗ったタブ1つにだけ SSE の talk_speak を送り、タブが done を返すか、見積もりの長さ + 猶予が
過ぎるまで待つ。そのあいだ TtsPlayer は次の文に進まない（is_busy() も真のまま）。
"""
from __future__ import annotations

import itertools
import json
import logging
import threading
import time
from typing import Callable

from shadow_clerk.domain import Language, SpeechTab, estimate_speech_sec

logger = logging.getLogger("shadow-clerk")

READY_TTL_SEC = 60.0   # タブは 30 秒ごとに名乗る。2 回続けて途絶えたら鳴らせるタブは無いとみなす
DONE_GRACE_SEC = 5.0   # 見積もりの長さにこれを足しても done が来なければ、次の文に進む
_POLL_SEC = 0.05


class BrowserSpeech:
    """TtsPlayer の RemoteSpeaker。SSE の送り口は daemon の起動後に set_broadcaster で渡される"""

    def __init__(self, *, grace_sec: float = DONE_GRACE_SEC, ttl_sec: float = READY_TTL_SEC,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._grace, self._ttl, self._clock = grace_sec, ttl_sec, clock
        self._broadcast: Callable[[str, str], None] | None = None
        self._lock = threading.Lock()
        self._tab: SpeechTab | None = None
        self._seen = 0.0
        self._done: dict[str, threading.Event] = {}
        self._ids = itertools.count(1)

    def set_broadcaster(self, fn: Callable[[str, str], None] | None) -> None:
        self._broadcast = fn

    def ready(self, tab: SpeechTab) -> None:
        """タブが名乗った。最後に名乗ったタブだけを使う。langs が空ならそのタブの名乗りを取り下げる（ページを閉じた）"""
        with self._lock:
            if tab.langs:
                self._tab, self._seen = tab, self._clock()
            elif self._tab is not None and self._tab.tab == tab.tab:
                self._tab = None

    def done(self, utterance_id: str) -> bool:
        """タブが読み終えた（onend / onerror）。待っている文でなければ False"""
        with self._lock:
            ev = self._done.get(utterance_id)
        if ev is None:
            return False
        ev.set()
        return True

    def can_speak(self, lang: Language) -> bool:
        return self._live_tab(lang) is not None

    def speak(self, text: str, lang: Language, should_stop: Callable[[], bool]) -> bool:
        """鳴らせるタブに送り、done・タイムアウト・should_stop まで待つ。送れなければ False（呼び手が VOICEVOX で読む）"""
        tab, send = self._live_tab(lang), self._broadcast
        if tab is None or send is None:
            return False
        uid, ev = f"s{next(self._ids)}", threading.Event()
        with self._lock:
            self._done[uid] = ev
        try:
            send("talk_speak", json.dumps({"id": uid, "tab": tab.tab, "text": text, "lang": lang.value},
                                          ensure_ascii=False))
            deadline = self._clock() + estimate_speech_sec(text) + self._grace
            while not ev.wait(_POLL_SEC):
                if should_stop():
                    send("talk_speak_cancel", json.dumps({"id": uid, "tab": tab.tab}))
                    break
                if self._clock() >= deadline:
                    logger.warning("talk: ブラウザの読み上げが終わらない（タブ %s）。次の文に進み、"
                                   "タブが名乗り直すまで VOICEVOX で読みます", tab.tab)
                    self._forget(tab)
                    break
            return True
        finally:
            with self._lock:
                self._done.pop(uid, None)

    def _live_tab(self, lang: Language) -> SpeechTab | None:
        with self._lock:
            tab = self._tab
            if tab is None or self._clock() - self._seen > self._ttl or not tab.speaks(lang):
                return None
            return tab

    def _forget(self, tab: SpeechTab) -> None:
        with self._lock:
            if self._tab is not None and self._tab.tab == tab.tab:
                self._tab = None
