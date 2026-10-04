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


def test_install_copies_every_bundled_skill() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        r = skill_install.install(tmp)
        talk = pathlib.Path(tmp) / skill_install.TALK_SKILL_NAME / "SKILL.md"
        check("clerk-talk も配られた", talk.is_file())
        check("戻り値に skill ごとの記録", [s["skill"] for s in r["skills"]] == list(skill_install.BUNDLED_SKILLS), repr(r))


def test_install_refuses_before_touching_anything() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _fake_installed(pathlib.Path(tmp) / skill_install.TALK_SKILL_NAME, None)
        try:
            skill_install.install(tmp)
            check("どれかが素性不明なら拒否", False, "例外が出なかった")
        except skill_install.InstallRefused:
            check("どれかが素性不明なら拒否", not (pathlib.Path(tmp) / skill_install.SKILL_NAME).exists())


def test_status_outdated_when_talk_skill_missing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        main_ver = skill_install.read_skill_version(skill_install.bundled_skill_dir())
        _fake_installed(pathlib.Path(tmp) / skill_install.SKILL_NAME, main_ver)
        cur = [t for t in skill_install.skill_status([tmp])["targets"] if t["name"] == tmp][0]
        check("clerk-talk が無ければ outdated", cur["state"] == "outdated", repr(cur))


def test_skill_installed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        skill_install.install(tmp)
        check("配布済みなら True", skill_install.skill_installed(skill_install.TALK_SKILL_NAME, [tmp]))
        check("無い skill は False", not skill_install.skill_installed("no-such-skill", [tmp]))


def test_talk_skill_check_looks_at_claude_only() -> None:
    """talk コンソールは Claude Code なので ~/.claude/skills を読む。~/.agents/skills にだけあっても動かない"""
    from shadow_clerk._daemon_talk_console import _talk_skill_installed
    talk = skill_install.TALK_SKILL_NAME
    orig = dict(skill_install.BUILTIN_TARGETS)
    with tempfile.TemporaryDirectory() as claude, tempfile.TemporaryDirectory() as agents:
        skill_install.BUILTIN_TARGETS.update(claude=claude, agents=agents)
        try:
            skill_install.install("agents")
            check("targets 省略は組み込みすべてを見る", skill_install.skill_installed(talk, []))
            check("targets=claude なら agents にあっても False",
                  not skill_install.skill_installed(talk, [], targets=("claude",)))
            check("talk の skill 確認は agents を見ない", not _talk_skill_installed())
            skill_install.install("claude")
            check("claude にあれば True", skill_install.skill_installed(talk, [], targets=("claude",))
                  and _talk_skill_installed())
        finally:
            skill_install.BUILTIN_TARGETS.clear()
            skill_install.BUILTIN_TARGETS.update(orig)


_TALK_CURL_PREFIXES = ('curl -s "http://localhost:', 'curl -s -X POST "http://localhost:',
                       'curl -sN "http://localhost:')


def _skill_parts(skill: str) -> tuple[dict, str]:
    import yaml
    text = (skill_install.bundled_skill_dir(skill) / "SKILL.md").read_text(encoding="utf-8")
    front, _, body = text[3:].partition("\n---")
    return yaml.safe_load(front), body


def _check_curl_forms(skill: str) -> None:
    """初回の talk で Bash の許可確認に止まらないよう、skill が自分の curl だけを事前に許可する。

    Bash の規則はコマンド文字列の前方一致なので、本文のコマンドも同じ形でなければ効かない
    """
    import re
    front, body = _skill_parts(skill)
    rules = re.findall(r"Bash\([^)]*\)|\w+", str(front.get("allowed-tools") or ""))
    for prefix in _TALK_CURL_PREFIXES:
        check(f"{skill}: allowed-tools に Bash({prefix}*)", f"Bash({prefix}*)" in rules, repr(rules))
    check(f"{skill}: allowed-tools に Monitor", "Monitor" in rules, repr(rules))
    calls = [body[m.start():].split("\n", 1)[0] for m in re.finditer(r"curl\s", body)]
    check(f"{skill}: 本文に curl の呼び出しがある", len(calls) >= 3, repr(calls))
    for call in calls:
        check(f"{skill}: 許可した形で呼ぶ: {call[:40]}", call.startswith(_TALK_CURL_PREFIXES), call)


def test_talk_skill_pre_approves_its_curl_calls() -> None:
    _check_curl_forms(skill_install.TALK_SKILL_NAME)


def test_practice_skill() -> None:
    """語学の練習の skill が同梱・配布され、talk と同じ許可だけで動くこと"""
    practice = skill_install.PRACTICE_SKILL_NAME
    check("clerk-practice を同梱する", practice in skill_install.BUNDLED_SKILLS, repr(skill_install.BUNDLED_SKILLS))
    check("clerk-practice の版が 1.1.0", skill_install.read_skill_version(skill_install.bundled_skill_dir(practice)) == "1.1.0")
    with tempfile.TemporaryDirectory() as tmp:
        skill_install.install(tmp)
        check("clerk-practice も配られた", (pathlib.Path(tmp) / practice / "SKILL.md").is_file())
    front, body = _skill_parts(practice)
    talk_front, talk_body = _skill_parts(skill_install.TALK_SKILL_NAME)
    check("allowed-tools は clerk-talk と同じ", front.get("allowed-tools") == talk_front.get("allowed-tools"),
          repr(front.get("allowed-tools")))
    _check_curl_forms(practice)
    for needle in ('/api/meeting"', '"analyze":false', '/api/language"', '/api/mute"', '`previous`',
                   '/api/meeting-history?meeting=', "tail=15", '/api/generated"', '"kind":"advice","mode":"replace"',
                   '"kind":"analysis","mode":"append"', '"lang":"en"', "🔊 ", "今日の練習のまとめ: ", '/api/talk-end"',
                   '"display":"ライト（右）"'):
        check(f"clerk-practice が {needle} を使う", needle in body)
    check("clerk-talk が clerk-practice に切り替える", "/clerk-practice" in talk_body)
    check("clerk-talk が /api/say の lang を知っている", '"lang":"en"' in talk_body)
    check("clerk-talk が /api/say の display を知っている", "`display`" in talk_body)
    check("clerk-practice が display を説明している", "`display`" in body)
    check("聞き取る言語の切り替えは練習が始まってから（提案までは母語のまま）",
          0 <= body.index("## 3. 練習する") < body.index('/api/language"') and "では、始めましょう" in body)


def test_talk_skill_reads_glossary_and_misheard() -> None:
    """声の聞き取りの崩れを読み解けるよう、talk skill が用語集と聞き間違いの対を読み、対を足せること"""
    text = (skill_install.bundled_skill_dir(skill_install.TALK_SKILL_NAME) / "SKILL.md").read_text(encoding="utf-8")
    for needle in ('/api/glossary"', '/api/misheard"', "POST"):
        check(f"talk skill が {needle} を使う", needle in text)
    check("talk skill の版が 1.7.2", skill_install.read_skill_version(
        skill_install.bundled_skill_dir(skill_install.TALK_SKILL_NAME)) == "1.7.2")
    quirks = skill_install.bundled_skill_dir(skill_install.TALK_SKILL_NAME) / "../clerk-meeting-helper/references/transcript-quirks.md"
    check("参照している崩れ方の説明が同梱されている", "../clerk-meeting-helper/references/transcript-quirks.md" in text
          and quirks.resolve().is_file(), str(quirks))


def test_talk_skill_watches_advice() -> None:
    """会議アシスタントの advice を見張り、誰も話していないときだけ自分から切り出すこと"""
    text = (skill_install.bundled_skill_dir(skill_install.TALK_SKILL_NAME) / "SKILL.md").read_text(encoding="utf-8")
    check("advice を Monitor で見張る", '/api/watch?kind=advice' in text)
    check("[相手] の発言も切り出す条件に入る", "[相手]" in text and "[自分]" in text)


def test_skills_read_screen_captures_via_subagent() -> None:
    """[画面] 行は自分で Read せず、背景のサブエージェントに読ませる（画像1枚で context を食うため）"""
    for skill in (skill_install.TALK_SKILL_NAME, skill_install.PRACTICE_SKILL_NAME):
        front, body = _skill_parts(skill)
        check(f"{skill}: allowed-tools に Agent", "Agent" in str(front.get("allowed-tools")), repr(front.get("allowed-tools")))
        check(f"{skill}: [画面] 行を扱う", "[画面]" in body)
        check(f"{skill}: サブエージェントに読ませる", "サブエージェント" in body and "バックグラウンド" in body)
        check(f"{skill}: 画像を自分で Read しない", "Read しない" in body)


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
    test_install_copies_every_bundled_skill()
    test_install_refuses_before_touching_anything()
    test_status_outdated_when_talk_skill_missing()
    test_skill_installed()
    test_talk_skill_check_looks_at_claude_only()
    test_talk_skill_pre_approves_its_curl_calls()
    test_talk_skill_reads_glossary_and_misheard()
    test_talk_skill_watches_advice()
    test_practice_skill()
    test_skills_read_screen_captures_via_subagent()
    shutil.rmtree(_DATA, ignore_errors=True)
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
