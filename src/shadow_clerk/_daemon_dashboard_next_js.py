"""Shadow-clerk daemon: /next ダッシュボード JavaScript（各 _NEXT_JS_* の連結。起動は最後）"""
from __future__ import annotations

from shadow_clerk._daemon_dashboard_js_console import _JS_TEMPLATE_CONSOLE
from shadow_clerk._daemon_dashboard_js_console_role import _JS_TEMPLATE_CONSOLE_ROLE
from shadow_clerk._daemon_dashboard_js_devices import _JS_TEMPLATE_DEVICES
from shadow_clerk._daemon_dashboard_js_modals import _JS_TEMPLATE_MODALS
from shadow_clerk._daemon_dashboard_js_panels import _JS_TEMPLATE_CUSTOM_CMDS, _JS_TEMPLATE_GLOSSARY, _JS_TEMPLATE_HELP_GCAL
from shadow_clerk._daemon_dashboard_js_settings import _JS_TEMPLATE_SETTINGS
from shadow_clerk._daemon_dashboard_js_speakers import _JS_TEMPLATE_SPEAKERS
from shadow_clerk._daemon_dashboard_js_speech import _JS_TEMPLATE_SPEECH
from shadow_clerk._daemon_dashboard_js_talk import _JS_TEMPLATE_TALK
from shadow_clerk._daemon_dashboard_js_voiceprints import _JS_TEMPLATE_VOICEPRINTS
from shadow_clerk._daemon_dashboard_next_js_core import _NEXT_JS_CORE
from shadow_clerk._daemon_dashboard_next_js_extract import _NEXT_JS_EXTRACT
from shadow_clerk._daemon_dashboard_next_js_list import _NEXT_JS_LIST
from shadow_clerk._daemon_dashboard_next_js_more import _NEXT_JS_MORE
from shadow_clerk._daemon_dashboard_next_js_mtgcfg import _NEXT_JS_MTGCFG
from shadow_clerk._daemon_dashboard_next_js_right import _NEXT_JS_RIGHT
from shadow_clerk._daemon_dashboard_next_js_search import _NEXT_JS_SEARCH
from shadow_clerk._daemon_dashboard_next_js_shims import _NEXT_JS_SHIMS
from shadow_clerk._daemon_dashboard_next_js_speakers import _NEXT_JS_SPEAKERS
from shadow_clerk._daemon_dashboard_next_js_start import _NEXT_JS_START
from shadow_clerk._daemon_dashboard_next_js_talk import _NEXT_JS_TALK
from shadow_clerk._daemon_dashboard_next_js_transcript import _NEXT_JS_TRANSCRIPT
from shadow_clerk._daemon_dashboard_next_js_view import _NEXT_JS_VIEW

_NEXT_JS_MODULES = (_NEXT_JS_CORE + _NEXT_JS_LIST + _NEXT_JS_TRANSCRIPT + _NEXT_JS_EXTRACT + _NEXT_JS_RIGHT
                    + _NEXT_JS_VIEW + _NEXT_JS_START + _NEXT_JS_MTGCFG + _NEXT_JS_TALK + _NEXT_JS_SEARCH + _NEXT_JS_MORE
                    + _NEXT_JS_SPEAKERS)
# 流用する現行モジュール（コンソールの描画・ブラウザの読み上げ・Claude と会議・ようこそ / スキル更新・設定・用語集・
# 音声コマンド・使い方・今日の予定・話者の名前付けと覚えている声）。読み込み時に es などの shim を使うので shim の後ろ。
# 用語集は読み込み時に設定の LANG_OPTS を使うので設定の後ろ（現行と同じ順）
_NEXT_JS_REUSED = (_JS_TEMPLATE_CONSOLE_ROLE + _JS_TEMPLATE_CONSOLE + _JS_TEMPLATE_SPEECH + _JS_TEMPLATE_TALK
                   + _JS_TEMPLATE_MODALS + _JS_TEMPLATE_DEVICES + _JS_TEMPLATE_SETTINGS
                   + _JS_TEMPLATE_GLOSSARY + _JS_TEMPLATE_CUSTOM_CMDS + _JS_TEMPLATE_HELP_GCAL
                   + _JS_TEMPLATE_SPEAKERS + _JS_TEMPLATE_VOICEPRINTS)
_NEXT_JS_BOOT = "nxInit();\n"

_NEXT_JS = _NEXT_JS_MODULES + _NEXT_JS_SHIMS + _NEXT_JS_REUSED + _NEXT_JS_BOOT
