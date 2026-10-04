"""Shadow-clerk daemon: ダッシュボード Claude talk mode エンドポイント"""
from __future__ import annotations

import logging

from shadow_clerk._daemon_dashboard_base import is_localhost_client, read_local_json_body
from shadow_clerk._daemon_talk import TalkStartError
from shadow_clerk._daemon_tts import TtsError
from shadow_clerk.domain import Language, SpeechTab, TalkVoice
from shadow_clerk.i18n import t

logger = logging.getLogger("shadow-clerk")

_MAX_TOPIC_CHARS = 500
_MAX_SAY_CHARS = 2000
_MAX_WORKDIR_CHARS = 1000
_MAX_ROUTE_CHARS = 200
_MAX_SPEECH_ID_CHARS = 64


class _DashboardHandlerTalkOps:
    """Claude talk mode の操作（ミックスイン）"""

    def _reject_remote(self) -> bool:
        if is_localhost_client(self.client_address):
            return False
        self._send_json({"status": "error", "message": "talk API is localhost only"})
        return True

    def _serve_talk_mode(self) -> None:
        """GET /api/talk-mode"""
        if not self._reject_remote():
            self._send_json(self.recorder.talk.snapshot())

    def _serve_talk_voices(self) -> None:
        """GET /api/talk-voices — TTS の話者一覧"""
        if self._reject_remote():
            return
        try:
            self._send_json({"status": "ok", "voices": self.recorder.talk.voices()})
        except TtsError as e:
            self._send_json({"status": "error", "message": str(e)})

    def _serve_talk_route_targets(self) -> None:
        """GET /api/talk-route-targets — Claude の声を届ける先の候補"""
        if not self._reject_remote():
            self._send_json(self.recorder.talk.route_targets())

    def _talk_preview(self) -> None:
        """POST /api/talk-preview {text?, voice?} — 保存前の声で試し読みする。transcript には書かない"""
        data = read_local_json_body(self, "talk")
        if data is None:
            return
        text, raw = data.get("text") or t("talk.preview_text"), data.get("voice", {})
        if not isinstance(text, str) or len(text) > _MAX_SAY_CHARS or not isinstance(raw, dict):
            self._send_json({"status": "error", "message": "text must be a short string and voice an object"})
            return
        try:
            self.recorder.talk.preview(TalkVoice.parse(raw), text)
        except (ValueError, TtsError) as e:
            self._send_json({"status": "error", "message": str(e)})
            return
        self._send_json({"status": "ok"})

    def _set_talk_mode(self) -> None:
        """POST /api/talk-mode {on, topic?, persona?, workdir?, route?} — persona は null で既定、"" で persona なし"""
        data = read_local_json_body(self, "talk")
        if data is None:
            return
        on, topic, persona = data.get("on"), data.get("topic", ""), data.get("persona")
        workdir, route = data.get("workdir"), data.get("route")
        if not isinstance(on, bool):
            self._send_json({"status": "error", "message": "on must be a boolean"})
            return
        if not isinstance(topic, str) or len(topic) > _MAX_TOPIC_CHARS:
            self._send_json({"status": "error", "message": "topic must be a short string"})
            return
        if persona is not None and not isinstance(persona, str):
            self._send_json({"status": "error", "message": "persona must be a string"})
            return
        if workdir is not None and (not isinstance(workdir, str) or len(workdir) > _MAX_WORKDIR_CHARS):
            self._send_json({"status": "error", "message": "workdir must be a short string"})
            return
        if route is not None and (not isinstance(route, str) or len(route) > _MAX_ROUTE_CHARS):
            self._send_json({"status": "error", "message": "route must be a short string"})
            return
        talk = self.recorder.talk
        if not on:
            talk.stop()
        else:
            try:
                talk.start(topic.strip(), persona, workdir, route or None)
            except TalkStartError as e:
                self._send_json({"status": "error", "message": str(e)})
                return
        self._send_json({"status": "ok", "talk": talk.snapshot()})

    def _end_talk(self) -> None:
        """POST /api/talk-end — 読み上げ中の文を言い終えてから talk mode を終える（talk の skill 用）"""
        if read_local_json_body(self, "talk") is None:
            return
        self._send_json({"status": "ok", "ending": self.recorder.talk.end_after_speech()})

    def _say(self) -> None:
        """POST /api/say {text, lang?} — [Claude] 行を書いて読み上げる（talk mode でなくても使える）

        lang（例: "en"）が読み上げの言語と違えば、その文はダッシュボードのブラウザの声で読む（語学の練習用）。
        文の言語は話す本人（skill）が知っているので、daemon は推測しない
        """
        data = read_local_json_body(self, "talk")
        if data is None:
            return
        text, lang = data.get("text"), data.get("lang")
        if not isinstance(text, str) or not text.strip() or len(text) > _MAX_SAY_CHARS:
            self._send_json({"status": "error", "message": "text must be a non-empty short string"})
            return
        if lang is not None and (not isinstance(lang, str) or lang not in {v.value for v in Language}):
            self._send_json({"status": "error", "message": "lang must be a known language code"})
            return
        cut = self.recorder.talk.api_say(text, Language(lang) if lang is not None else None)
        self._send_json({"status": "ok"} if cut is None else {"status": "interrupted", "cut": cut})

    def _talk_speech_ready(self) -> None:
        """POST /api/talk-speech/ready {tab, langs} — 練習言語の文を読めるダッシュボードのタブが名乗る（30 秒ごと）"""
        data = read_local_json_body(self, "talk")
        if data is None:
            return
        try:
            tab = SpeechTab.parse(data)
        except ValueError as e:
            self._send_json({"status": "error", "message": str(e)})
            return
        self.recorder.talk.speech_ready(tab)
        self._send_json({"status": "ok"})

    def _talk_speech_done(self) -> None:
        """POST /api/talk-speech/done {id} — タブが talk_speak の文を読み終えた（onend / onerror）"""
        data = read_local_json_body(self, "talk")
        if data is None:
            return
        uid = data.get("id")
        if not isinstance(uid, str) or not uid or len(uid) > _MAX_SPEECH_ID_CHARS:
            self._send_json({"status": "error", "message": "id must be a short string"})
            return
        self._send_json({"status": "ok", "known": self.recorder.talk.speech_done(uid)})
