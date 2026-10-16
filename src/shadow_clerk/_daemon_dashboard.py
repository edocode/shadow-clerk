"""Shadow-clerk daemon: Web ダッシュボード（後方互換シム）"""
from __future__ import annotations

from shadow_clerk._daemon_log_buffer import LogBuffer, FileWatcher  # noqa: F401
from shadow_clerk._daemon_dashboard_handler import DashboardHandler  # noqa: F401
from shadow_clerk._daemon_dashboard_html import _HTML_TEMPLATE  # noqa: F401
