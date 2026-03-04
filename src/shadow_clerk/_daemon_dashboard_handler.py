"""Shadow-clerk daemon: ダッシュボード HTTP ハンドラー"""

from shadow_clerk._daemon_dashboard_base import _DashboardHandlerBase
from shadow_clerk._daemon_dashboard_ops import _DashboardHandlerOps


class DashboardHandler(_DashboardHandlerOps, _DashboardHandlerBase):
    """ダッシュボード HTTP リクエストハンドラー"""
