"""Shadow-clerk daemon: ダッシュボード Claude talk mode エンドポイント"""
from __future__ import annotations

import logging

from shadow_clerk._daemon_dashboard_base import is_localhost_client, read_local_json_body
from shadow_clerk._daemon_pronounce import ArmError
from shadow_clerk._daemon_talk import TalkStartError
from shadow_clerk._daemon_tts import TtsError
from shadow_clerk.domain import Language, PronunciationTask, SpeechTab, TalkVoice
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

    def _serve_speaking(self) -> None:
        """GET /api/speaking — 中間文字起こしに文字が出ている（誰かが話している）か"""
        if not self._reject_remote():
            sources = self.recorder.talk.speaking()
            self._send_json({"speaking": bool(sources), "sources": sources})

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
        """POST /api/talk-mode {on, topic?, persona?, workdir?, route?, glossary?} — persona は null で既定、"" で persona なし"""
        data = read_local_json_body(self, "talk")
        if data is None:
            return
        on, topic, persona = data.get("on"), data.get("topic", ""), data.get("persona")
        workdir, route, glossary = data.get("workdir"), data.get("route"), data.get("glossary", True)
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
        if not isinstance(glossary, bool):
            self._send_json({"status": "error", "message": "glossary must be a boolean"})
            return
        talk = self.recorder.talk
        if not on:
            talk.stop()
        else:
            try:
                talk.start(topic.strip(), persona, workdir, route or None, glossary)
            except TalkStartError as e:
                self._send_json({"status": "error", "message": str(e)})
                return
            except Exception as e:  # pw-dump の形が想定外 (KeyError) など。応答を返さずに落とすとダッシュボードに理由が出ない
                logger.exception("talk: 開始に失敗")
                self._send_json({"status": "error", "message": f"{type(e).__name__}: {e}"})
                return
        self._send_json({"status": "ok", "talk": talk.snapshot()})

    def _end_talk(self) -> None:
        """POST /api/talk-end — 読み上げ中の文を言い終えてから talk mode を終える（talk の skill 用）"""
        if read_local_json_body(self, "talk") is None:
            return
        self._send_json({"status": "ok", "ending": self.recorder.talk.end_after_speech()})

    def _say(self) -> None:
        """POST /api/say {text, lang?, display?} — [Claude] 行を書いて読み上げる（talk mode でなくても使える）

        lang（例: "en"）が読み上げの言語と違えば、その文はダッシュボードのブラウザの声で読む（語学の練習用）。
        文の言語は話す本人（skill）が知っているので、daemon は推測しない
        display があれば transcript の [Claude] 行にはそれを書き、声は text を読む（答えの綴りを見せない練習用）
        """
        data = read_local_json_body(self, "talk")
        if data is None:
            return
        text, lang, display = data.get("text"), data.get("lang"), data.get("display")
        for name, value in (("text", text), ("display", display)):
            if (value is not None or name == "text") and (
                    not isinstance(value, str) or not value.strip() or len(value) > _MAX_SAY_CHARS):
                self._send_json({"status": "error", "message": f"{name} must be a non-empty short string"})
                return
        if lang is not None and (not isinstance(lang, str) or lang not in {v.value for v in Language}):
            self._send_json({"status": "error", "message": "lang must be a known language code"})
            return
        self._send_json(self.recorder.talk.api_say(text, Language(lang) if lang is not None else None, display))

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

    def _serve_pronounce(self) -> None:
        """GET /api/pronounce — アームの状態と直近の解析結果"""
        if not self._reject_remote():
            self._send_json(self.recorder.pronounce.snapshot())

    def _set_pronounce(self) -> None:
        """POST /api/pronounce {text, lang, focus} / {clear: true} — 課題をアームする・解除する"""
        data = read_local_json_body(self, "pronounce")
        if data is None:
            return
        if data.get("clear"):
            self.recorder.pronounce.clear()
            self._send_json({"status": "ok", "state": "idle"})
            return
        # お手本の gate は talk mode の読み上げにしか付かない。止まっていたら受け付けない
        if not self.recorder.talk.active:
            self._send_json({"status": "error",
                             "message": "talk mode must be running to arm pronunciation feedback"})
            return
        try:
            task = PronunciationTask.parse(data)
        except ValueError as e:
            self._send_json({"status": "error", "message": str(e)})
            return
        try:
            self._send_json(self.recorder.pronounce.arm(task))
        except ArmError as e:
            out = {"status": "error", "message": e.message}
            if e.expected is not None:
                out["expected"] = e.expected
            self._send_json(out)
