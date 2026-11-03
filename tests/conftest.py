"""pytest 全体の共通設定

pytest は複数のテストファイルを1つのプロセスで読み込む。各ファイルが import 時に
SHADOW_CLERK_DATA_DIR を一時フォルダへ向けても、先に読まれたファイルが shadow_clerk を
import していれば、データフォルダはそのとき決まった場所（本物のデータ）のままになる。
conftest.py はどのテストファイルより先に読まれるので、ここで一時フォルダへ向けておく。
"""
from __future__ import annotations

import os
import tempfile

os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-pytest-")
