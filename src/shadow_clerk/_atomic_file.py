"""Shadow-clerk: ファイルのアトミックな書き戻し

同じディレクトリの一時ファイル（mkstemp なので 0600）に書いて os.replace する。
`open(path, "w")` の直接書き戻しは truncate 中の読み取りで空/途中のファイルが見えるため使わない。
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from typing import TextIO


def _atomic_write(path: str, prefix: str, write: Callable[[TextIO], None]) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or ".", prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            write(f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_json(path: str, body: dict, prefix: str) -> None:
    _atomic_write(path, prefix, lambda f: json.dump(body, f, ensure_ascii=False))


def atomic_write_lines(path: str, lines: list[str], prefix: str) -> None:
    _atomic_write(path, prefix, lambda f: f.writelines(lines))
