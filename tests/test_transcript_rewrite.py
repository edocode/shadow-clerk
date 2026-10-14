"""TranscriptRewrite（書き換えによるバイト位置の移動）と書き換え履歴の検証

実行: uv run python tests/test_transcript_rewrite.py
daemon も音声デバイスも不要。ファイルにも触らない。
"""
from __future__ import annotations

from shadow_clerk.domain.transcript_rewrite import (
    REWRITE_HISTORY, TranscriptRewrite, TranscriptRewriteJournal,
)

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def _b(lines: list[str]) -> int:
    return len("".join(lines).encode("utf-8"))


A, B, C, D = "aaa\n", "bbbbb\n", "cc\n", "dddd\n"   # 4, 6, 3, 5 bytes


def test_removing_builds_mapping() -> None:
    rw = TranscriptRewrite.removing([A, B, C, D], [1])
    check("removing: 新しい行", list(rw.new_lines) == [A, C, D], repr(rw.new_lines))
    check("removing: 対応表", list(rw.kept) == [0, None, 1, 2], repr(rw.kept))


def test_map_kept_lines() -> None:
    rw = TranscriptRewrite.removing([A, B, C, D], [1])
    check("先頭行の開始は 0", rw.map_offset(0) == 0)
    check("削除行より前の行の途中はそのまま", rw.map_offset(2) == 2)
    check("削除行の後ろの行の開始は削除分だけ前へ", rw.map_offset(_b([A, B])) == _b([A]), str(rw.map_offset(10)))
    check("削除行の後ろの行の途中", rw.map_offset(_b([A, B]) + 1) == _b([A]) + 1)
    check("最後の行の開始", rw.map_offset(_b([A, B, C])) == _b([A, C]))


def test_map_removed_line() -> None:
    rw = TranscriptRewrite.removing([A, B, C, D], [1])
    check("削除行の開始 → 次に残る行の開始", rw.map_offset(_b([A])) == _b([A]))
    check("削除行の途中 → 次に残る行の開始", rw.map_offset(_b([A]) + 3) == _b([A]))


def test_map_end_and_after() -> None:
    rw = TranscriptRewrite.removing([A, B, C, D], [1])
    end_old, end_new = _b([A, B, C, D]), _b([A, C, D])
    check("旧末尾 → 新末尾", rw.map_offset(end_old) == end_new)
    check("旧末尾の先（書き換え後の追記）", rw.map_offset(end_old + 7) == end_new + 7)


def test_removed_run_at_start_and_end() -> None:
    rw = TranscriptRewrite.removing([A, B, C, D], [0, 1])
    check("先頭の削除行群 → 0", rw.map_offset(0) == 0 and rw.map_offset(5) == 0)
    check("先頭削除後の残り行", rw.map_offset(_b([A, B]) + 1) == 1)
    rw = TranscriptRewrite.removing([A, B, C, D], [2, 3])
    check("末尾の削除行群 → 新末尾", rw.map_offset(_b([A, B]) + 1) == _b([A, B])
          and rw.map_offset(_b([A, B, C]) + 2) == _b([A, B]))
    rw = TranscriptRewrite.removing([A, B], [0, 1])
    check("全行削除 → 0", rw.map_offset(3) == 0 and rw.map_offset(_b([A, B]) + 2) == 2)


def test_multibyte() -> None:
    j1, j2, j3 = "[10:00] あいう\n", "[10:01] 漢字だ\n", "[10:02] えお\n"
    rw = TranscriptRewrite.removing([j1, j2, j3], [0])
    check("多バイト: 削除行の後ろの行の開始", rw.map_offset(_b([j1, j2])) == _b([j2]))
    check("多バイト: 途中のバイト位置も削除分だけ前へ",
          rw.map_offset(_b([j1]) + 9) == 9, str(rw.map_offset(_b([j1]) + 9)))
    check("多バイト: 旧末尾 → 新末尾", rw.map_offset(_b([j1, j2, j3])) == _b([j2, j3]))


def test_kept_line_shorter() -> None:
    rw = TranscriptRewrite([A, B], [0, 1], [A, "b\n"])
    check("短くなった行の途中は新しい行の末尾で止める", rw.map_offset(_b([A]) + 4) == _b([A]) + 2)


def test_journal_generations_and_chain() -> None:
    j = TranscriptRewriteJournal()
    p = "/x/transcript-20261004.txt"
    check("未記録のパスは世代 0", j.generation(p) == 0)
    check("未記録なら remap はそのまま", j.remap_since(p, 0, 12) == (12, 0))
    j.record_rewrite(p, TranscriptRewrite.removing([A, B, C, D], [1]))     # B を削除
    j.record_rewrite(p, TranscriptRewrite.removing([A, C, D], [0]))        # A を削除
    check("記録ごとに世代が上がる", j.generation(p) == 2)
    end_old = _b([A, B, C, D])
    check("2 回分を順に当てる", j.remap_since(p, 0, end_old) == (_b([C, D]), 2), repr(j.remap_since(p, 0, end_old)))
    check("途中の世代からは残りだけ当てる", j.remap_since(p, 1, _b([A, C])) == (_b([C]), 2))
    check("最新の世代ならそのまま", j.remap_since(p, 2, 5) == (5, 2))
    check("別のパスには影響しない", j.generation("/x/other.txt") == 0)


def test_journal_bounded_history_resync() -> None:
    j = TranscriptRewriteJournal()
    p = "/x/t.txt"
    for _ in range(REWRITE_HISTORY + 1):
        j.record_rewrite(p, TranscriptRewrite.removing([A, B], [0]))
    gen = REWRITE_HISTORY + 1
    check("古すぎる読み手には resync (None)", j.remap_since(p, 0, 4) == (None, gen), repr(j.remap_since(p, 0, 4)))
    check("最古の残り世代からなら remap できる", j.remap_since(p, 1, 0) == (0, gen), repr(j.remap_since(p, 1, 0)))


def main() -> int:
    test_removing_builds_mapping()
    test_map_kept_lines()
    test_map_removed_line()
    test_map_end_and_after()
    test_removed_run_at_start_and_end()
    test_multibyte()
    test_kept_line_shorter()
    test_journal_generations_and_chain()
    test_journal_bounded_history_resync()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
