"""Shadow-clerk daemon: ダッシュボード JavaScript"""

from shadow_clerk._daemon_dashboard_js_core import _JS_TEMPLATE_CORE
from shadow_clerk._daemon_dashboard_js_devices import _JS_TEMPLATE_DEVICES
from shadow_clerk._daemon_dashboard_js_modals import _JS_TEMPLATE_MODALS
from shadow_clerk._daemon_dashboard_js_settings import _JS_TEMPLATE_SETTINGS
from shadow_clerk._daemon_dashboard_js_panels import _JS_TEMPLATE_PANELS
from shadow_clerk._daemon_dashboard_js_console import _JS_TEMPLATE_CONSOLE

_JS_TEMPLATE = (_JS_TEMPLATE_CORE + _JS_TEMPLATE_MODALS + _JS_TEMPLATE_DEVICES
                + _JS_TEMPLATE_SETTINGS + _JS_TEMPLATE_PANELS
                + _JS_TEMPLATE_CONSOLE)
