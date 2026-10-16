"""Shadow-clerk daemon: ダッシュボード HTTP ハンドラー"""
from __future__ import annotations

from shadow_clerk._daemon_dashboard_base import _DashboardHandlerBase
from shadow_clerk._daemon_dashboard_ops import _DashboardHandlerOps
from shadow_clerk._daemon_dashboard_ops_meeting import _DashboardHandlerMeetingOps
from shadow_clerk._daemon_dashboard_ops_config import _DashboardHandlerConfigOps
from shadow_clerk._daemon_dashboard_ops_screenshot import _DashboardHandlerScreenshotOps
from shadow_clerk._daemon_dashboard_ops_console import _DashboardHandlerConsoleOps
from shadow_clerk._daemon_dashboard_ops_skill import _DashboardHandlerSkillOps
from shadow_clerk._daemon_dashboard_ops_talk import _DashboardHandlerTalkOps
from shadow_clerk._daemon_dashboard_ops_speakers import _DashboardHandlerSpeakerOps
from shadow_clerk._daemon_dashboard_ops_speaker_groups import _DashboardHandlerSpeakerGroupOps


class DashboardHandler(_DashboardHandlerOps, _DashboardHandlerMeetingOps,
                       _DashboardHandlerConfigOps, _DashboardHandlerScreenshotOps,
                       _DashboardHandlerConsoleOps, _DashboardHandlerSkillOps,
                       _DashboardHandlerTalkOps, _DashboardHandlerSpeakerOps,
                       _DashboardHandlerSpeakerGroupOps,
                       _DashboardHandlerBase):
    """ダッシュボード HTTP リクエストハンドラー"""
