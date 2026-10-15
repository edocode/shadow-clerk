"""Windows (cp932 既定) でも config.yaml 等を UTF-8 で読み書きできることの回帰テスト

実行: uv run python tests/test_utf8_open.py
1. src/shadow_clerk の AST を走査し、encoding 無しのテキストモード open() /
   Path.read_text/write_text / text=True の subprocess を検出する
2. builtins.open を「encoding 未指定なら cp932」に差し替えて Windows を再現し、
   日本語入りの config.yaml を clerk_util 経由で読み書きする
~/.local/share/shadow-clerk には触れない (SHADOW_CLERK_DATA_DIR は一時ディレクトリ)。
"""
from __future__ import annotations
import ast
import builtins
import contextlib
import io
import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

DATA = tempfile.mkdtemp(prefix="shadow-clerk-utf8-")
os.environ["SHADOW_CLERK_DATA_DIR"] = DATA

from shadow_clerk import clerk_util  # noqa: E402

SRC = Path(__file__).resolve().parent.parent / "src" / "shadow_clerk"
SUBPROCESS_FUNCS = {"run", "Popen", "check_output", "check_call", "call"}


def _mode_is_binary(call: ast.Call) -> bool:
    mode = call.args[1] if len(call.args) > 1 else None
    mode = next((k.value for k in call.keywords if k.arg == "mode"), mode)
    return isinstance(mode, ast.Constant) and "b" in str(mode.value)


def find_violations() -> list[str]:
    out: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            kws = {k.arg for k in n.keywords}
            f = n.func
            where = f"{path.relative_to(SRC)}:{n.lineno}"
            if isinstance(f, ast.Name) and f.id == "open":
                if not _mode_is_binary(n) and "encoding" not in kws:
                    out.append(f"{where} open() without encoding")
            elif isinstance(f, ast.Attribute):
                if f.attr in ("read_text", "write_text") and "encoding" not in kws:
                    out.append(f"{where} {f.attr}() without encoding")
                is_sub = isinstance(f.value, ast.Name) and f.value.id == "subprocess"
                if is_sub and f.attr in SUBPROCESS_FUNCS and kws & {"text", "universal_newlines"} \
                        and "encoding" not in kws:
                    out.append(f"{where} subprocess.{f.attr}(text=True) without encoding")
    return out


@contextlib.contextmanager
def cp932_default_open() -> Iterator[None]:
    """encoding 未指定のテキストモード open() を cp932 にする (Windows の既定の再現)"""
    real = builtins.open

    def fake(file, mode="r", *a, **kw):  # type: ignore[no-untyped-def]
        if "b" not in str(mode) and len(a) < 2 and kw.get("encoding") is None:
            kw["encoding"] = "cp932"
        return real(file, mode, *a, **kw)

    builtins.open = fake
    try:
        yield
    finally:
        builtins.open = real


def test_no_text_open_without_encoding() -> None:
    v = find_violations()
    assert not v, "missing encoding=:\n" + "\n".join(v)


def test_config_roundtrip_under_cp932_default() -> None:
    cfg = Path(clerk_util.CONFIG_FILE)
    cfg.write_text('persona: "会議の書記"\noutput_directory: "C:/会議/記録"\n', encoding="utf-8")
    with cp932_default_open():
        clerk_util._read_output_directory()
        assert clerk_util.OUTPUT_DIR == "C:/会議/記録", clerk_util.OUTPUT_DIR
        clerk_util.cmd_write_config_value(["wake_word", "シェルク"])
        buf = io.StringIO()
        old, sys.stdout = sys.stdout, buf
        try:
            clerk_util.cmd_read_config([])
        finally:
            sys.stdout = old
        assert "C:/会議/記録" in buf.getvalue() and "wake_word: シェルク" in buf.getvalue()
    assert "wake_word: シェルク" in cfg.read_text(encoding="utf-8")


if __name__ == "__main__":
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
