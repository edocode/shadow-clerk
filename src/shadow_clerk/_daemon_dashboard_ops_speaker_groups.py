"""Shadow-clerk daemon: ダッシュボード — 話者のグループと、スキル向けの話者一覧"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from shadow_clerk.i18n import t
from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_dashboard_base import is_localhost_client, read_local_json_body
from shadow_clerk._daemon_speaker_names import SpeakerNameBook, SpeakerNameBookError
from shadow_clerk._daemon_speaker_roster import load_roster
from shadow_clerk.domain.speaker_group import GroupName

logger = logging.getLogger("shadow-clerk")


def _self_group() -> str:
    return str(load_config().get("self_group") or "").strip()


class _DashboardHandlerSpeakerGroupOps:
    """GET /api/speaker-groups, POST /api/speaker-groups/set, GET /api/speaker-roster"""

    def _serve_speaker_groups(self) -> None:
        """GET /api/speaker-groups — 色分け用。ラベル→グループ、グループ→色、自分の所属"""
        self_group = _self_group()
        try:
            book = SpeakerNameBook()
            if self_group:
                try:
                    book.ensure_group(GroupName(self_group))
                except ValueError:
                    self_group = ""
            entries, groups = book.entries(), book.groups()
        except (SpeakerNameBookError, OSError) as e:
            logger.warning("名前帳を読めない: %s", e)
            self._send_json({"status": "error", "message": t("dash.speaker_book_error")})
            return
        self._send_json({"status": "ok", "names": {n: e.group for n, e in entries.items()},
                         "persons": {n: e.person for n, e in entries.items()},
                         "groups": groups, "self_group": self_group})

    def _set_speaker_group(self) -> None:
        """POST /api/speaker-groups/set {name, group} — 台帳の人のグループだけ変える（"" で外す）"""
        data = read_local_json_body(self, "speaker-groups")
        if data is None:
            return
        name, group = data.get("name"), data.get("group", "")
        if not isinstance(name, str) or not isinstance(group, str):
            self._send_json({"status": "error", "message": t("dash.speakers_invalid")})
            return
        try:
            g = GroupName(group) if group.strip() else None
        except ValueError:
            self._send_json({"status": "error", "message": t("dash.speakers_group_invalid")})
            return
        try:
            ok = SpeakerNameBook().set_group(name, g)
        except (SpeakerNameBookError, OSError):
            self._send_json({"status": "error", "message": t("dash.speaker_book_error")})
            return
        self._send_json({"status": "ok"} if ok else {"status": "error", "message": t("dash.speakers_invalid")})

    def _serve_speaker_roster(self) -> None:
        """GET /api/speaker-roster?file= — スキル向け: transcript の話者と所属グループ。localhost 限定"""
        if not is_localhost_client(self.client_address):
            self._send_json({"status": "error", "message": "skill API is localhost only"})
            return
        t_path = self._speaker_transcript_path(parse_qs(urlparse(self.path).query).get("file", [None])[0])
        if t_path is None:
            self._send_json({"status": "error", "message": t("dash.transcript_not_found")})
            return
        self_group = _self_group()
        roster = load_roster(self._read_lines(t_path), self_group)
        self._send_json({"status": "ok", "self_group": self_group, "speakers": [e.to_dict() for e in roster]})
