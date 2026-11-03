"""文字起こしの置き場所（区分 / 会議フォルダ）と、フラットな配置からの移行

実行: uv run pytest -q tests/test_transcript_layout.py
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("SHADOW_CLERK_DATA_DIR", tempfile.mkdtemp(prefix="shadow-clerk-layout-"))
os.environ["MEETING_CONFIG"] = os.path.join(os.environ["SHADOW_CLERK_DATA_DIR"], "no-meeting.yaml")

from shadow_clerk._transcript_layout import UNNAMED_DIR, TranscriptLayout, migrate_flat_files, owner  # noqa: E402
from shadow_clerk._transcript_name import TranscriptName  # noqa: E402


def _touch(path: str, text: str = "x\n") -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def test_owner_reads_every_file_of_a_meeting() -> None:
    for name in ("transcript-202610011000@acme.txt", "transcript-202610011000@acme-en.txt",
                 "transcript-202610011000@acme.txt.translate_offset", "summary-202610011000@acme.md",
                 "advice-202610011000@acme.md", "analysis-202610011000@acme.md", "minutes-202610011000@acme.md",
                 "transcript-202610011000@acme.attendees.json", "transcript-202610011000@acme.voices.jsonl",
                 "transcript-202610011000@acme.naming.jsonl", "transcript-202610011000@acme.provisional.json",
                 "shot-202610011000@acme-101500.png"):
        tn = owner(name)
        assert tn is not None and (tn.datetime_str, tn.meeting_name) == ("202610011000", "acme"), name
    assert owner("transcript-202610011000@follow-up.txt").meeting_name == "follow-up"
    assert owner("transcript-202605281500@[a.b]_c.txt").meeting_name == "[a.b]_c"
    assert (owner("shot-20261001-101500.png").datetime_str, owner("shot-20261001-101500.png").meeting_name) \
        == ("20261001", None)
    for name in ("config.yaml", "glossary.txt", "transcript-x.txt", "daemon.log"):
        assert owner(name) is None, name


def test_dir_of_named_and_unnamed(tmp_path: object) -> None:
    root = str(tmp_path)
    layout = TranscriptLayout(root)
    assert layout.dir_of(TranscriptName("202610011000", "acme")) == os.path.join(root, "private", "acme")
    assert layout.dir_of(TranscriptName("20261001")) == os.path.join(root, "private", UNNAMED_DIR, "2026-10")
    assert layout.dir_of(TranscriptName("202610011000")) == os.path.join(root, "private", UNNAMED_DIR, "2026-10")
    # 既にあるフォルダの区分が優先
    os.makedirs(os.path.join(root, "sharable", "weekly"))
    assert layout.path("summary-202610011000@weekly.md") == os.path.join(root, "sharable", "weekly",
                                                                          "summary-202610011000@weekly.md")
    assert layout.category_of("weekly") == "sharable"
    assert layout.path("../transcript-20261001.txt") is None and layout.path(".env") is None


def test_categories_are_validated(tmp_path: object) -> None:
    assert TranscriptLayout(str(tmp_path), ["mine", "../x", "", "mine", "a.b"]).categories == ("mine",)
    assert TranscriptLayout(str(tmp_path), []).categories == ("private", "sharable", "isolated")


def test_files_and_move(tmp_path: object) -> None:
    root = str(tmp_path)
    layout = TranscriptLayout(root)
    a = _touch(layout.path("transcript-202610011000@acme.txt") or "")
    d = _touch(layout.path("transcript-20261002.txt") or "")
    assert layout.files() == {"transcript-202610011000@acme.txt": a, "transcript-20261002.txt": d}
    moved = layout.move_meeting("acme", "isolated")
    assert moved == os.path.join(root, "isolated", "acme") and os.path.isfile(
        os.path.join(moved, "transcript-202610011000@acme.txt"))
    os.makedirs(os.path.join(root, "private", "acme"))
    try:
        TranscriptLayout(root, ["isolated", "private"]).move_meeting("acme", "private")
        raise AssertionError("移す先に同名のフォルダがあれば移さない")
    except ValueError:
        pass


def test_reference_dirs(tmp_path: object) -> None:
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "sharable"))
    layout = TranscriptLayout(root, references=["sharable", "missing", "~"])
    assert layout.reference_dirs("acme", [root + "/sharable/"]) == [os.path.join(root, "sharable")]


def test_migrate_flat_files(tmp_path: object) -> None:
    root = str(tmp_path)
    for name in ("transcript-202610011000@acme.txt", "transcript-202610011000@acme-en.txt",
                 "summary-202610011000@acme.md", "shot-202610011000@acme-101500.png",
                 "transcript-20261002.txt", "transcript-20261002.txt.translate_offset",
                 "transcript-202605281500@[a.b]_c d.txt", "config.yaml", "glossary.txt"):
        _touch(os.path.join(root, name))
    session = os.path.join(root, ".clerk_session")
    layout = TranscriptLayout(root)
    moved = layout.migrate_flat()
    assert sorted(os.listdir(root)) == ["config.yaml", "glossary.txt", "private"]
    assert sorted(os.listdir(os.path.join(root, "private", "acme"))) == [
        "shot-202610011000@acme-101500.png", "summary-202610011000@acme.md",
        "transcript-202610011000@acme-en.txt", "transcript-202610011000@acme.txt"]
    assert sorted(os.listdir(os.path.join(root, "private", UNNAMED_DIR, "2026-10"))) == [
        "transcript-20261002.txt", "transcript-20261002.txt.translate_offset"]
    # 規則より前の名前は同じ規則に通して付け直す
    assert os.path.isfile(os.path.join(root, "private", "[ab]_c_d", "transcript-202605281500@[ab]_c_d.txt"))
    assert len(moved) == 7 and layout.migrate_flat() == {}
    # 会議中に再起動されたら、セッションファイルが指すパスも移した先へ付け替える
    with open(session, "w", encoding="utf-8") as f:
        f.write(os.path.join(root, "transcript-202610031000@b.txt"))
    _touch(os.path.join(root, "transcript-202610031000@b.txt"))
    import shadow_clerk._daemon_config as cfg_mod
    orig = cfg_mod.load_config
    cfg_mod.load_config = lambda: {"output_directory": root}
    try:
        migrate_flat_files(session)
    finally:
        cfg_mod.load_config = orig
    with open(session, encoding="utf-8") as f:
        assert f.read() == os.path.join(root, "private", "b", "transcript-202610031000@b.txt")


def test_carry_shots_moves_only_referenced_shots(tmp_path: object) -> None:
    from shadow_clerk._transcript_layout import carry_shots
    src, dst = os.path.join(str(tmp_path), "a"), os.path.join(str(tmp_path), "b")
    _touch(os.path.join(src, "shot-20261001-101500.png"))
    _touch(os.path.join(src, "shot-20261001-111500.png"))
    lines = ["[2026-10-01 10:15:00] [画面] 画面キャプチャ: shot-20261001-101500.png | t | u\n",
             "[2026-10-01 10:16:00] [自分] shot-20261001-111500.png の話\n"]
    assert carry_shots(lines, src, dst) == 1
    assert os.listdir(dst) == ["shot-20261001-101500.png"]
    assert os.listdir(src) == ["shot-20261001-111500.png"]
