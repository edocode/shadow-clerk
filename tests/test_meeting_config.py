"""MeetingConfig の検証

実行: uv run python tests/test_meeting_config.py
"""
from __future__ import annotations
import os
import tempfile

import yaml

from shadow_clerk.domain import meeting_config
from shadow_clerk.domain.meeting_config import MeetingConfig, MeetingRule

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def write_cfg(data: dict) -> str:
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True)
    return path


SAMPLE = {
    "defaults": {"workdir": "~/meeting-analysis", "verbosity": "normal"},
    "meetings": [
        {"pattern": "1[ _-]?on[ _-]?1", "publish": False, "note": "keep me"},
        {"pattern": "acme|shopsite", "workdir": "/tmp"},
    ],
}


def test_first_match_wins() -> None:
    c = MeetingConfig.load(write_cfg(SAMPLE))
    check("最初に一致したルールを使う",
          c.resolve_workdir("acme_定例") == "/tmp", c.resolve_workdir("acme_定例"))


def test_case_insensitive() -> None:
    c = MeetingConfig.load(write_cfg({"meetings": [{"pattern": "board", "workdir": "/tmp"}]}))
    check("大文字小文字を区別しない",
          c.resolve_workdir("Board_Meeting") == "/tmp", c.resolve_workdir("Board_Meeting"))


def test_rule_without_workdir_falls_to_defaults() -> None:
    c = MeetingConfig.load(write_cfg(SAMPLE))
    # 1on1 のルールには workdir が無いので defaults.workdir を使う
    check("ルールに workdir が無ければ defaults",
          c.resolve_workdir("1_on_1_alice") == "~/meeting-analysis",
          c.resolve_workdir("1_on_1_alice"))


def test_no_match_returns_empty() -> None:
    c = MeetingConfig.load(write_cfg({"meetings": [{"pattern": "zzz", "workdir": "/tmp"}]}))
    check("どこにも一致しなければ空文字", c.resolve_workdir("Nothing") == "",
          repr(c.resolve_workdir("Nothing")))


def test_invalid_pattern_is_skipped() -> None:
    c = MeetingConfig.load(write_cfg({"meetings": [
        {"pattern": "[", "workdir": "/bad"},
        {"pattern": "ok", "workdir": "/tmp"},
    ]}))
    check("不正な正規表現は飛ばして続ける", c.resolve_workdir("ok") == "/tmp",
          c.resolve_workdir("ok"))


def test_missing_file() -> None:
    c = MeetingConfig.load("/nonexistent/mtg.yaml")
    check("ファイルが無くても空で動く", c.resolve_workdir("x") == "")
    check("rules は空", c.rules() == [])


def test_rules() -> None:
    c = MeetingConfig.load(write_cfg(SAMPLE))
    check("rules は pattern と workdir を返す",
          c.rules() == [MeetingRule("1[ _-]?on[ _-]?1", ""), MeetingRule("acme|shopsite", "/tmp")],
          repr(c.rules()))


def test_upsert_preserves_other_keys() -> None:
    path = write_cfg(SAMPLE)
    c = MeetingConfig.load(path)
    c.upsert("1[ _-]?on[ _-]?1", "/new")
    c.save()
    reloaded = yaml.safe_load(open(path, encoding="utf-8"))
    rule = reloaded["meetings"][0]
    check("workdir を更新する", rule["workdir"] == "/new", repr(rule))
    check("他のキーを保持する", rule.get("note") == "keep me" and rule.get("publish") is False,
          repr(rule))
    check("defaults を保持する", reloaded["defaults"]["verbosity"] == "normal")


def test_upsert_appends_new_rule() -> None:
    path = write_cfg(SAMPLE)
    c = MeetingConfig.load(path)
    c.upsert("NewPat", "/n")
    c.save()
    reloaded = yaml.safe_load(open(path, encoding="utf-8"))
    check("新しいルールは末尾に足す", reloaded["meetings"][-1]["pattern"] == "NewPat",
          repr(reloaded["meetings"][-1]))


def test_remove() -> None:
    path = write_cfg(SAMPLE)
    c = MeetingConfig.load(path)
    c.remove("acme|shopsite")
    c.save()
    reloaded = yaml.safe_load(open(path, encoding="utf-8"))
    check("ルールを削除できる",
          all(r["pattern"] != "acme|shopsite" for r in reloaded["meetings"]),
          repr(reloaded["meetings"]))


def test_save_to_new_path() -> None:
    c = MeetingConfig.load("/nonexistent/mtg.yaml")
    c.upsert("P", "/p")
    dest = os.path.join(tempfile.mkdtemp(), "mtg.yaml")
    written = c.save(dest)
    check("新規パスに保存できる", written == dest and os.path.exists(dest), written)


def test_research_destinations() -> None:
    """調べものの当て先。**既定は空** — 外へ出すものは明示的に許可されたものだけ"""
    c = MeetingConfig("x", {})
    check("未設定なら空", c.resolve("X")["research"] == [], str(c.resolve("X")["research"]))

    c = MeetingConfig("x", {"defaults": {"research": [
        {"name": "bigquery", "allow_private": True, "note": "社内DWH"},
        "web",
        {"name": "  "},
        {"name": "wiki"},
        "not-a-dict-but-a-string",
        42,
    ]}})
    got = c.resolve("X")["research"]
    names = [r["name"] for r in got]
    check("文字列だけでも当て先になる", "web" in names, str(names))
    check("名前が空のものは落とす", "" not in names and "  " not in names, str(names))
    check("dict でも文字列でもないものは落とす", 42 not in names, str(names))
    check("社内の当て先はそのまま聞ける",
          got[names.index("bigquery")]["allow_private"] is True)
    check("備考を持てる", got[names.index("bigquery")]["note"] == "社内DWH")

    # **書き忘れは社外側に倒す。** 逆だと社内の固有名詞をそのまま外へ出す
    check("allow_private の既定は False",
          got[names.index("wiki")]["allow_private"] is False)
    check("文字列指定も既定は False", got[names.index("web")]["allow_private"] is False)

    # 会議ごとに上書きできる
    c = MeetingConfig("x", {"defaults": {"research": ["web"]},
                        "meetings": [{"pattern": "Board", "research": []}]})
    check("会議ごとに外部を止められる", c.resolve("Board_MTG")["research"] == [],
          str(c.resolve("Board_MTG")["research"]))
    check("一致しない会議は defaults のまま",
          [r["name"] for r in c.resolve("Other")["research"]] == ["web"])


def test_migrates_legacy_config() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        legacy = os.path.join(tmp, "legacy", "config.yaml")
        os.makedirs(os.path.dirname(legacy))
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("meetings:\n  - pattern: acme\n    workdir: /tmp\n")
        new = os.path.join(tmp, "meeting.yaml")
        moved = meeting_config.migrate_legacy(legacy_paths=[legacy], target=new)
        check("移行したと報告する", moved is True)
        check("新パスに複製された", os.path.isfile(new))
        check("旧ファイルは残る", os.path.isfile(legacy))


def test_does_not_migrate_when_target_exists() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        legacy = os.path.join(tmp, "config.yaml")
        with open(legacy, "w", encoding="utf-8") as f:
            f.write("meetings: []\n")
        new = os.path.join(tmp, "meeting.yaml")
        with open(new, "w", encoding="utf-8") as f:
            f.write("meetings: [{pattern: keep, workdir: /keep}]\n")
        moved = meeting_config.migrate_legacy(legacy_paths=[legacy], target=new)
        check("新パスがあれば移行しない", moved is False)
        with open(new, encoding="utf-8") as f:
            check("新パスは書き換わらない", "keep" in f.read())


def test_no_legacy_is_not_an_error() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        moved = meeting_config.migrate_legacy(
            legacy_paths=[os.path.join(tmp, "nope.yaml")],
            target=os.path.join(tmp, "meeting.yaml"))
        check("旧ファイルが無ければ何もしない", moved is False)


def main() -> int:
    test_research_destinations()
    test_first_match_wins()
    test_case_insensitive()
    test_rule_without_workdir_falls_to_defaults()
    test_no_match_returns_empty()
    test_invalid_pattern_is_skipped()
    test_missing_file()
    test_rules()
    test_upsert_preserves_other_keys()
    test_upsert_appends_new_rule()
    test_remove()
    test_save_to_new_path()
    test_migrates_legacy_config()
    test_does_not_migrate_when_target_exists()
    test_no_legacy_is_not_an_error()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
