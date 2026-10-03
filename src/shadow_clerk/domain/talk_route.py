"""shadow-clerk domain: Claude の声を届ける先（会議アプリの録音ストリーム）"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RouteTarget:
    """届ける先の録音ストリーム。同一性は app（application.name）で判定する。node_id は開き直すたびに変わる"""

    app: str
    node_id: int
    label: str
