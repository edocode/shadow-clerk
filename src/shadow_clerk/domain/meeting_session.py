"""shadow-clerk domain: MeetingSession バリューオブジェクト"""
from __future__ import annotations

import datetime
import os
from dataclasses import dataclass

from shadow_clerk._transcript_name import TranscriptName


@dataclass(frozen=True)
class MeetingSession:
    """進行中または完了した会議セッションを表すバリューオブジェクト。

    現在のコードでは output_path (str) + SESSION_FILE の有無で会議状態を管理しているが、
    このオブジェクトはその状態を型安全に表現する。
    """

    transcript_name: TranscriptName
    file_path: str
    started_at: datetime.datetime
    ended_at: datetime.datetime | None = None

    @property
    def is_active(self) -> bool:
        """会議が進行中かどうか。"""
        return self.ended_at is None

    @classmethod
    def start(cls, file_path: str, started_at: datetime.datetime | None = None) -> MeetingSession:
        """ファイルパスから MeetingSession（開始状態）を生成する。"""
        name = TranscriptName.parse(os.path.basename(file_path))
        if name is None:
            raise ValueError(f"transcript ファイル名として解釈できません: {file_path!r}")
        return cls(
            transcript_name=name,
            file_path=file_path,
            started_at=started_at or datetime.datetime.now(),
        )

    def end(self, ended_at: datetime.datetime | None = None) -> MeetingSession:
        """終了した MeetingSession を返す（イミュータブルなので新しいオブジェクトを返す）。"""
        return MeetingSession(
            transcript_name=self.transcript_name,
            file_path=self.file_path,
            started_at=self.started_at,
            ended_at=ended_at or datetime.datetime.now(),
        )
