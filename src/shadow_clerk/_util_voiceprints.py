"""clerk-util: 声紋の書き出し・取り込み（voiceprints-export / voiceprints-import）

処理は _daemon_voiceprint_share が持つ。ここは引数の解釈と表示だけ
"""
from __future__ import annotations

import json
import sys

_EXPORT_USAGE = "Usage: clerk-util voiceprints-export <out.json> [name ...]   (名前を省くと声紋のある全員)"
_IMPORT_USAGE = "Usage: clerk-util voiceprints-import <file.json> [name | name=取り込み先 ...]   (省くと全員を同じ名前で)"


def _fail(message: str) -> None:
    print(message, file=sys.stderr)
    sys.exit(1)


def cmd_voiceprints_export(args: list[str]) -> None:
    if not args or args[0].startswith("-"):
        _fail(_EXPORT_USAGE)
    from shadow_clerk._daemon_voiceprint_share import build_export
    from shadow_clerk._daemon_voiceprint_store import VoiceprintStore
    out, names = args[0], args[1:]
    try:
        exp = build_export(names or list(VoiceprintStore().people()))
    except Exception as e:
        _fail(f"書き出せませんでした: {e}")
    if not exp.people:
        _fail("声紋のある人がいません")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(exp.to_dict(), f, ensure_ascii=False)
    print(f"{out}: {', '.join(p.name.value for p in exp.people)}")
    print("声紋は生体情報です。本人の同意を得てから渡してください")


def cmd_voiceprints_import(args: list[str]) -> None:
    if not args or args[0].startswith("-"):
        _fail(_IMPORT_USAGE)
    from shadow_clerk._daemon_voiceprint_share import ModelMismatchError, import_export
    from shadow_clerk.domain.voiceprint_export import VoiceprintExport
    try:
        with open(args[0], encoding="utf-8") as f:
            exp = VoiceprintExport.parse(json.load(f))
    except (OSError, ValueError) as e:
        _fail(f"声紋の書き出しファイルとして読めません: {e}")
    pairs = [a.split("=", 1) if "=" in a else [a, a] for a in args[1:]]
    mapping = {k: v for k, v in pairs} or {p.name.value: p.name.value for p in exp.people}
    if missing := set(mapping) - {p.name.value for p in exp.people}:
        _fail(f"ファイルにいない人: {', '.join(sorted(missing))}")
    try:
        added = import_export(exp, mapping)
    except ModelMismatchError as e:
        _fail(f"声紋を作ったモデルが違うため取り込めません: {e}")
    except Exception as e:
        _fail(f"取り込めませんでした: {e}")
    for name, n in added.items():
        print(f"{name}: +{n}")
