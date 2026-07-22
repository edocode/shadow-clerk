"""Shadow-clerk daemon: ダッシュボード HTTP ハンドラー"""

from shadow_clerk._daemon_dashboard_base import _DashboardHandlerBase
from shadow_clerk._daemon_dashboard_ops import _DashboardHandlerOps
from shadow_clerk._daemon_dashboard_ops_meeting import _DashboardHandlerMeetingOps


class DashboardHandler(_DashboardHandlerOps, _DashboardHandlerMeetingOps, _DashboardHandlerBase):
    """ダッシュボード HTTP リクエストハンドラー"""
