"""Shadow-clerk daemon: ダッシュボード Claude talk mode エンドポイント"""
from __future__ import annotations

import logging

from shadow_clerk._daemon_dashboard_base import is_localhost_client, read_local_json_body
from shadow_clerk._daemon_talk import TalkStartError

logger = logging.getLogger("shadow-clerk")

_MAX_TOPIC_CHARS = 500
_MAX_SAY_CHARS = 2000


class _DashboardHandlerTalkOps:
    """Claude talk mode の操作（ミックスイン）"""

    def _serve_talk_mode(self) -> None:
        """GET /api/talk-mode"""
        if not is_localhost_client(self.client_address):
            self._send_json({"status": "error", "message": "talk API is localhost only"})
            return
        self._send_json(self.recorder.talk.snapshot())

    def _set_talk_mode(self) -> None:
        """POST /api/talk-mode {on, topic?, persona?} — persona は null で既定、"" で persona なし"""
        data = read_local_json_body(self, "talk")
        if data is None:
            return
        on, topic, persona = data.get("on"), data.get("topic", ""), data.get("persona")
        if not isinstance(on, bool):
            self._send_json({"status": "error", "message": "on must be a boolean"})
            return
        if not isinstance(topic, str) or len(topic) > _MAX_TOPIC_CHARS:
            self._send_json({"status": "error", "message": "topic must be a short string"})
            return
        if persona is not None and not isinstance(persona, str):
            self._send_json({"status": "error", "message": "persona must be a string"})
            return
        talk = self.recorder.talk
        if not on:
            talk.stop()
        else:
            try:
                talk.start(topic.strip(), persona)
            except TalkStartError as e:
                self._send_json({"status": "error", "message": str(e)})
                return
        self._send_json({"status": "ok", "talk": talk.snapshot()})

    def _say(self) -> None:
        """POST /api/say {text} — [Claude] 行を書いて読み上げる（talk mode でなくても使える）"""
        data = read_local_json_body(self, "talk")
        if data is None:
            return
        text = data.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > _MAX_SAY_CHARS:
            self._send_json({"status": "error", "message": "text must be a non-empty short string"})
            return
        self.recorder.talk.say(text)
        self._send_json({"status": "ok"})
