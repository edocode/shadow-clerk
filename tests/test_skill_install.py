"""skill_install の検証

実行: uv run python tests/test_skill_install.py
"""
from __future__ import annotations
import pathlib
import tempfile

from shadow_clerk import skill_install

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_bundled_dir_exists() -> None:
    d = skill_install.bundled_skill_dir()
    check("同梱スキルのディレクトリが実在する", d.is_dir(), str(d))
    check("SKILL.md がある", (d / "SKILL.md").is_file(), str(d))


def test_read_version_from_bundled() -> None:
    v = skill_install.read_skill_version(skill_install.bundled_skill_dir())
    check("同梱スキルのバージョンが読める", v is not None, repr(v))


def test_read_version_missing_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "SKILL.md").write_text("---\ndescription: x\n---\n\nbody\n", encoding="utf-8")
        check("metadata が無ければ None", skill_install.read_skill_version(d) is None)


def test_read_version_no_frontmatter() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        d = pathlib.Path(tmp)
        (d / "SKILL.md").write_text("# 素の markdown\n", encoding="utf-8")
        check("frontmatter が無ければ None", skill_install.read_skill_version(d) is None)


def test_read_version_absent_dir() -> None:
    check("ディレクトリが無ければ None",
          skill_install.read_skill_version(pathlib.Path("/no/such/dir")) is None)


def main() -> int:
    test_bundled_dir_exists()
    test_read_version_from_bundled()
    test_read_version_missing_metadata()
    test_read_version_no_frontmatter()
    test_read_version_absent_dir()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
