"""Shadow-clerk daemon: Claude talk mode の会話言語と system prompt"""
from __future__ import annotations

import logging
import os
import random

from shadow_clerk._daemon_tts import TtsBackend
from shadow_clerk.domain import Language, TalkPersona

logger = logging.getLogger("shadow-clerk")

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "talk_prompts")

# 会話の口火。返答の言語は system prompt 側で決まるので英語で足りる
KICKOFF_MESSAGE = ("Start the session. Ask your first question about the topic, "
                   "or ask what to talk about if no topic is given.")


# 応答が遅いときに daemon が挟むつなぎの一言。transcript には書かず claude にも送らない。
# 「ちょっと考えます」のような宣言より、短い間投詞のほうがうるさくない
# どの発言のあとでも通じる、意味を持たない言葉だけにする（「はい」は同意に聞こえるので入れない）
_FILLERS = {Language.JA: ("うーん。", "えーっと。", "そうですね。", "なるほど。", "ふむ。", "ええと。",
                         "うんうん。", "そうですねえ。", "ふむふむ。", "あー。"),
            Language.EN: ("Hmm.", "Let me see.", "Well.", "I see.", "Right.", "Okay.", "Mm-hm.")}

# 制止で読み上げを止めたときに、ユーザー発言の前に付けて claude に伝える
INTERRUPT_NOTE = ("[The user interrupted you. You were cut off while saying: \"{cut}\". "
                  "Nothing after that was heard.]")


def filler_phrase(lang: Language, previous: str = "") -> str:
    """つなぎを1つ選ぶ。直前と同じものは選ばない"""
    phrases = _FILLERS.get(lang, _FILLERS[Language.JA])
    return random.choice([p for p in phrases if p != previous] or phrases)


def requested_language(config: dict) -> str:
    return str(config.get("talk_language") or config.get("translate_language") or "")


def resolve_talk_language(requested: str, backend: TtsBackend) -> Language:
    """希望言語を TTS が読めればそれを、読めなければ TTS の既定言語を返す"""
    lang = Language.coerce(requested) if requested else None
    if isinstance(lang, Language) and lang in backend.LANGUAGES:
        return lang
    if requested:
        logger.info("talk: %s は TTS が非対応のため %s で話します",
                    requested, backend.DEFAULT_LANGUAGE.value)
    return backend.DEFAULT_LANGUAGE


def build_system_prompt(lang: Language, persona: TalkPersona | None, topic: str) -> str:
    with open(os.path.join(_PROMPT_DIR, f"{lang.value}.md"), encoding="utf-8") as f:
        parts = [f.read().strip()]
    if persona is not None:
        parts.append(f"## Persona\n\n{persona.instructions}")
    if topic.strip():
        parts.append(f"## Topic\n\n{topic.strip()}")
    return "\n\n".join(parts)
