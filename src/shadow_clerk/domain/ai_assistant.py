"""AI アシスタントの起動設定（値オブジェクト）"""
from __future__ import annotations
import logging
import os
import re
import shlex
import sys
from dataclasses import dataclass

from shadow_clerk._daemon_constants import DEFAULT_CONFIG

logger = logging.getLogger("shadow-clerk")

_PLACEHOLDER = re.compile(r"\{(transcript|meeting|lang)\}")


def _split_args(raw: str) -> list[str]:
    """引数文字列をトークンに割る。

    Windows では posix=False で割る。POSIX モードの shlex はバックスラッシュを
    エスケープとして食うので `C:\\Users\\x` が `C:Usersx` に潰れ、末尾が
    バックスラッシュだと ValueError まで出る——Windows のパスを引数に書く手段が
    無くなる。posix=False は引用符をトークンに残すので、外側の対だけ剥がす。
    """
    if sys.platform != "win32":
        return shlex.split(raw)
    return [tok[1:-1] if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'" else tok
            for tok in shlex.split(raw, posix=False)]


@dataclass(frozen=True)
class AiAssistantConfig:
    """config.yaml の ai_assistant_* をまとめた値オブジェクト"""

    command: str
    args: tuple[str, ...]
    init_prompt: str
    workdir: str

    @classmethod
    def from_config(cls, config: dict) -> "AiAssistantConfig":
        def _get(key: str) -> str:
            value = config.get(key, DEFAULT_CONFIG.get(key, ""))
            return "" if value is None else str(value)

        raw_args = _get("ai_assistant_args")
        try:
            args = tuple(_split_args(raw_args))
        except ValueError as e:
            # 引用符の閉じ忘れなど。起動できない方が困るので空にして続ける
            logger.warning("ai_assistant_args を解釈できません (%s): %r", e, raw_args)
            args = ()
        return cls(
            command=_get("ai_assistant_command") or "claude",
            args=args,
            init_prompt=_get("ai_assistant_init_prompt"),
            workdir=_get("ai_assistant_workdir"),
        )

    def argv(self) -> list[str]:
        return [self.command, *self.args]

    def resolve_init_prompt(self, transcript: str, meeting: str, lang: str = "") -> str:
        """{transcript} {meeting} {lang} を展開する。未知のキーは literal のまま残す。

        置換は元のテンプレートに対する 1 回の走査で行う。逐次 replace だと、
        差し込んだ値の中にある `{meeting}` を次のパスが拾って壊す
        （transcript のファイル名は会議名を含み、会議名から `{}` は除去されない）。
        """
        values = {"transcript": transcript, "meeting": meeting, "lang": lang}
        return _PLACEHOLDER.sub(lambda m: values[m.group(1)], self.init_prompt)

    def resolve_workdir(self, override: str = "") -> str:
        """起動ディレクトリを決める。override → 設定 → ホーム の順"""
        home = os.path.expanduser("~")
        for candidate in (override, self.workdir):
            if not candidate:
                continue
            path = os.path.expanduser(candidate)
            if os.path.isdir(path):
                return path
            logger.warning("workdir が存在しません: %s", path)
        return home
