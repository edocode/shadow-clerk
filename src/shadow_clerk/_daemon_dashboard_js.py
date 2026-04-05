"""Shadow-clerk daemon: ダッシュボード JavaScript"""

from shadow_clerk._daemon_dashboard_js_core import _JS_TEMPLATE_CORE
from shadow_clerk._daemon_dashboard_js_panels import _JS_TEMPLATE_PANELS

_JS_TEMPLATE = _JS_TEMPLATE_CORE + _JS_TEMPLATE_PANELS
