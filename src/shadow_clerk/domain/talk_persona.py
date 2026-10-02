"""shadow-clerk domain: Claude talk mode の persona バリューオブジェクト"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("shadow-clerk")


@dataclass(frozen=True)
class TalkPersona:
    """会話役 Claude の性格・応答の仕方。name は config の key、instructions は自由記述。"""

    name: str
    instructions: str

    @classmethod
    def all_from_config(cls, raw: object) -> dict[str, TalkPersona]:
        """config の talk_personas（name → 記述）から作る。空や文字列以外の記述は捨てる。"""
        if not isinstance(raw, dict):
            return {}
        return {str(k): cls(str(k), v.strip()) for k, v in raw.items()
                if isinstance(v, str) and v.strip()}

    @classmethod
    def resolve(cls, personas: dict[str, TalkPersona], requested: str | None,
                default: str | None) -> TalkPersona | None:
        """None → 既定、"" → persona なし、名前 → その persona（無ければ既定）。"""
        if requested == "":
            return None
        if requested is not None:
            if requested in personas:
                return personas[requested]
            logger.warning("talk: persona %r が見つからないため既定を使います", requested)
        return personas.get(default or "")
