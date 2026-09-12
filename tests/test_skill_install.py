"""skill_install の検証

実行: uv run python tests/test_skill_install.py
"""
from __future__ import annotations
import os
import pathlib
import shutil
import tempfile

# **import より前に差し替えること。** DATA_DIR と CONFIG_FILE は import 時に
# 確定するので、あとから環境変数を変えても遅い。install() は配布先を
# config.yaml に覚えるため、隔離しないと利用者の設定に一時パスが残る
_DATA = tempfile.mkdtemp(prefix="skill-install-test-")
os.environ["SHADOW_CLERK_DATA_DIR"] = _DATA

from shadow_clerk import skill_install       # noqa: E402

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


def _fake_installed(d: pathlib.Path, version: str | None) -> None:
    d.mkdir(parents=True, exist_ok=True)
    meta = f"metadata:\n  version: \"{version}\"\n" if version else ""
    (d / "SKILL.md").write_text(f"---\ndescription: x\n{meta}---\n\nbody\n", encoding="utf-8")


def test_resolve_builtin_target() -> None:
    name, path = skill_install.resolve_target("claude")
    check("claude は組み込み", name == "claude", name)
    check("~ が展開される", "~" not in str(path), str(path))
    check("スキル名で終わる", path.name == skill_install.SKILL_NAME, str(path))


def test_resolve_agents_target() -> None:
    name, path = skill_install.resolve_target("agents")
    check("agents は組み込み", name == "agents", name)
    check("agents は .agents/skills の下", ".agents" in str(path), str(path))


def test_resolve_custom_path() -> None:
    name, path = skill_install.resolve_target("/tmp/whatever")
    check("任意パスはそのまま名前になる", name == "/tmp/whatever", name)
    check("スキル名を足す", path.name == skill_install.SKILL_NAME, str(path))


def test_install_copies() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        r = skill_install.install(tmp)
        dest = pathlib.Path(tmp) / skill_install.SKILL_NAME
        check("SKILL.md が配られた", (dest / "SKILL.md").is_file())
        check("references も配られた", (dest / "references").is_dir())
        check("before は None", r["before"] is None, repr(r["before"]))
        check("after はバージョン", r["after"] is not None, repr(r["after"]))


def test_install_refuses_unknown_dest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _fake_installed(pathlib.Path(tmp) / skill_install.SKILL_NAME, None)
        try:
            skill_install.install(tmp)
            check("素性不明の配布先を拒否する", False, "例外が出なかった")
        except skill_install.InstallRefused:
            check("素性不明の配布先を拒否する", True)


def test_install_force_overwrites_unknown_dest() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _fake_installed(pathlib.Path(tmp) / skill_install.SKILL_NAME, None)
        r = skill_install.install(tmp, force=True)
        check("--force なら上書きする", r["after"] is not None, repr(r))


def test_install_overwrites_own_dest_without_force() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _fake_installed(pathlib.Path(tmp) / skill_install.SKILL_NAME, "0.0.1")
        r = skill_install.install(tmp)
        check("自分の配布物は force 無しで上書き", r["before"] == "0.0.1", repr(r))


def test_status_reports_each_target() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        skill_install.install(tmp)
        st = skill_install.skill_status([tmp])
        names = [t["name"] for t in st["targets"]]
        check("組み込み2つが常に出る", "claude" in names and "agents" in names, repr(names))
        check("記憶した配布先も出る", tmp in names, repr(names))
        cur = [t for t in st["targets"] if t["name"] == tmp][0]
        check("配り立ては current", cur["state"] == "current", repr(cur))


def test_status_missing_and_outdated() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        st = skill_install.skill_status([tmp])
        cur = [t for t in st["targets"] if t["name"] == tmp][0]
        check("未配布は missing", cur["state"] == "missing", repr(cur))
        _fake_installed(pathlib.Path(tmp) / skill_install.SKILL_NAME, "0.0.1")
        cur = [t for t in skill_install.skill_status([tmp])["targets"]
               if t["name"] == tmp][0]
        check("古ければ outdated", cur["state"] == "outdated", repr(cur))


def main() -> int:
    test_bundled_dir_exists()
    test_read_version_from_bundled()
    test_read_version_missing_metadata()
    test_read_version_no_frontmatter()
    test_read_version_absent_dir()
    test_resolve_builtin_target()
    test_resolve_agents_target()
    test_resolve_custom_path()
    test_install_copies()
    test_install_refuses_unknown_dest()
    test_install_force_overwrites_unknown_dest()
    test_install_overwrites_own_dest_without_force()
    test_status_reports_each_target()
    test_status_missing_and_outdated()
    shutil.rmtree(_DATA, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
