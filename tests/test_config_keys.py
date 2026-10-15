"""config キー・設定モーダル・i18n の整合性チェック

実行: uv run python tests/test_config_keys.py
daemon も音声デバイスも不要。ソースを読むだけで ~/.local/share/shadow-clerk には触れない。
"""
from __future__ import annotations
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-cfgkeys-")

from shadow_clerk._daemon_constants import DEFAULT_CONFIG  # noqa: E402
from shadow_clerk._daemon_dashboard_js_settings import _JS_TEMPLATE_SETTINGS  # noqa: E402
from shadow_clerk._i18n_en import STRINGS_EN  # noqa: E402
from shadow_clerk._i18n_ja import STRINGS_JA  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src" / "shadow_clerk"

# モーダルに出さないのが正しいキー (理由必須)。新キーはまず CFG_FIELDS に足すこと
HIDDEN_KEYS: dict[str, str] = {
    "custom_commands": "edited in its own dialog",
    "skill_install_targets": "internal state of the skill install dialog",
    "skill_update_dismissed_version": "internal state: dismissed update prompt",
    "welcome_dismissed": "internal state: dismissed welcome dialog",
    "talk_personas": "list edited in the talk persona dialog",
    "talk_default_persona": "chosen in the talk panel",
    "talk_model": "chosen in the talk panel",
    "talk_workdir": "chosen in the talk panel",
    "talk_route_app": "chosen in the talk panel",
    "talk_speaker_id": "chosen in the talk voice picker",
}

# 本来モーダルにあるべきだが未対応の既存キー。警告のみ (新規キーをここに足さない)
PENDING_KEYS: dict[str, str] = {
    "auto_summary_via_console": "not yet in modal",
    "claude_cli_model": "not yet in modal",
    "claude_cli_path": "not yet in modal",
    "gcal_token_file": "not yet in modal",
    "kotoba_whisper_model": "not yet in modal",
    "reazonspeech_precision": "not yet in modal",
    "talk_allowed_tools": "not yet in modal",
    "talk_echo_tail_sec": "not yet in modal",
    "talk_engine": "not yet in modal",
    "talk_floor_wait_sec": "not yet in modal",
    "talk_intonation": "not yet in modal",
    "talk_language": "not yet in modal",
    "talk_output_devices": "not yet in modal",
    "talk_pitch": "not yet in modal",
    "talk_speed": "not yet in modal",
    "talk_stop_words": "not yet in modal",
    "talk_voicevox_url": "not yet in modal",
    "talk_volume": "not yet in modal",
}

# config 読み取りに見えるが config ではない `.get("...")` (理由必須)
NOT_CONFIG_KEYS: dict[str, str] = {
    "dashboard_port": "pending: read in clerk_util with a default but absent from DEFAULT_CONFIG",
}

# 変数名が config / cfg / conf の dict への読み取り、または load_config().get(...) を設定読み取りとみなす
READ_RES = [
    re.compile(r"load_config\(\)\s*\.get\(\s*[\"']([a-z_0-9]+)"),
    re.compile(r"\b(?:config|cfg|conf)\.get\(\s*[\"']([a-z_0-9]+)"),
    re.compile(r"\b(?:config|cfg|conf)\[\s*[\"']([a-z_0-9]+)[\"']\s*\]"),
]

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


fields = re.findall(r"\{key:'([a-z_0-9]+)'", _JS_TEMPLATE_SETTINGS)
modal_keys = set(fields)
# type:'forbid' フィールドは config.yaml に保存されない (別の保存先) ので DEFAULT_CONFIG 対象外
non_config = set(re.findall(r"\{key:'([a-z_0-9]+)'[^\n]*type:'forbid'", _JS_TEMPLATE_SETTINGS))
check("CFG_FIELDS parsed", len(fields) > 0, f"({len(fields)} keys)")
check("CFG_FIELDS has no duplicate keys", len(fields) == len(modal_keys),
      str(sorted({k for k in fields if fields.count(k) > 1})))

defaults = set(DEFAULT_CONFIG)
missing = defaults - modal_keys - set(HIDDEN_KEYS) - set(PENDING_KEYS)
check("DEFAULT_CONFIG keys are in the modal or HIDDEN_KEYS", not missing, str(sorted(missing)))
bad_hidden = {k for k in HIDDEN_KEYS if k not in defaults or k in modal_keys}
check("HIDDEN_KEYS entries are real and not in modal", not bad_hidden, str(sorted(bad_hidden)))
bad_pending = {k for k in PENDING_KEYS if k not in defaults or k in modal_keys}
check("PENDING_KEYS entries are real and not in modal", not bad_pending, str(sorted(bad_pending)))
check("modal keys are in DEFAULT_CONFIG", not (modal_keys - non_config - defaults), str(sorted(modal_keys - non_config - defaults)))
for k, why in PENDING_KEYS.items():
    print(f"[WARN] {k}: {why}")

for lang, table in (("ja", STRINGS_JA), ("en", STRINGS_EN)):
    lack = sorted(k for k in modal_keys if f"cfg.{k}" not in table)
    check(f"modal keys have cfg.<key> label in {lang}", not lack, str(lack))

read_keys: dict[str, str] = {}
for path in SRC.rglob("*.py"):
    text = path.read_text(encoding="utf-8")
    for rx in READ_RES:
        for m in rx.finditer(text):
            read_keys.setdefault(m.group(1), path.name)
unknown = {k: f for k, f in read_keys.items() if k not in defaults and k not in NOT_CONFIG_KEYS}
check("config reads use DEFAULT_CONFIG keys", not unknown, str(unknown))
stale = [k for k in NOT_CONFIG_KEYS if k not in read_keys or k in defaults]
check("NOT_CONFIG_KEYS entries are still needed", not stale, str(stale))

sys.exit(0 if all(results) else 1)
