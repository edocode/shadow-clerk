"""AI アシスタントの起動設定（値オブジェクト）"""
from __future__ import annotations
import logging
import os
import re
import shlex
import sys
from collections.abc import Iterable
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

    def argv(self, add_dirs: Iterable[str] = (), settings_from: str = "") -> list[str]:
        """起動コマンド。add_dirs は作業ディレクトリのほかに読んでよいフォルダ（--add-dir）。
        settings_from に .claude/settings.json があれば --settings で読ませる——会議のフォルダで起動しても、
        従来の作業ディレクトリで許可したスキルのコマンドが承認プロンプトで止まらない。
        どちらも Claude Code にだけ渡す（ほかの CLI は同じ引数を持たない）"""
        if not os.path.basename(self.command).startswith("claude"):
            return [self.command, *self.args]
        # ホームの .claude/settings.json はユーザー設定そのもので、もともと読まれる
        home = settings_from == os.path.expanduser("~")
        settings = os.path.join(settings_from, ".claude", "settings.json") if settings_from and not home else ""
        return [self.command, *self.args, *(a for d in add_dirs for a in ("--add-dir", d)),
                *(("--settings", settings) if os.path.isfile(settings) else ())]

    def resolve_init_prompt(self, transcript: str, meeting: str, lang: str = "") -> str:
        """{transcript} {meeting} {lang} を展開する。未知のキーは literal のまま残す。

        置換は元のテンプレートに対する 1 回の走査で行う。逐次 replace だと、
        差し込んだ値の中にある `{meeting}` を次のパスが拾って壊す
        （transcript のファイル名は会議名を含み、会議名から `{}` は除去されない）。
        """
        values = {"transcript": transcript, "meeting": meeting, "lang": lang}
        return _PLACEHOLDER.sub(lambda m: values[m.group(1)], self.init_prompt)

    def meeting_workdir(self, meeting: str) -> str:
        """会議ごとの作業ディレクトリ設定 → 全体の設定 → ホーム。会議中のアシスタントは会議のフォルダで起動し、
        これは参考フォルダとして足す（Git リポジトリなど）"""
        from shadow_clerk.domain.meeting_config import MeetingConfig
        return self.resolve_workdir(MeetingConfig.load().resolve_workdir(meeting))

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
