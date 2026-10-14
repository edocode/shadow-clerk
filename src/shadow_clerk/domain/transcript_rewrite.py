"""TranscriptRewrite: transcript の書き換え（行削除など）でバイト位置がどう動いたか

録音中の transcript をバイトオフセットで追う読み手（監視ストリーム・翻訳ループ）は、
ダッシュボードが行を消して書き直すと位置がずれる。書き換えごとに旧→新の対応を記録し、
読み手が自分の位置を新しい座標へ写せるようにする。バイト長は UTF-8 で数える。
"""
from __future__ import annotations

import bisect
import collections
import threading
from collections.abc import Sequence
from dataclasses import dataclass

REWRITE_HISTORY = 16  # パスごとに覚えておく書き換えの数


def _starts(lines: Sequence[str]) -> list[int]:
    """各行の開始バイト位置と、末尾に全体のバイト長を付けたリスト"""
    pos = [0]
    for line in lines:
        pos.append(pos[-1] + len(line.encode("utf-8")))
    return pos


@dataclass(frozen=True)
class TranscriptRewrite:
    """1 回の書き換え。kept[i] は旧 i 行目に対応する新しい行の index（消えたら None）"""
    old_lines: tuple[str, ...]
    kept: tuple[int | None, ...]
    new_lines: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("old_lines", "kept", "new_lines"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if len(self.kept) != len(self.old_lines):
            raise ValueError("kept must have one entry per old line")

    @classmethod
    def removing(cls, old_lines: Sequence[str], removed: Sequence[int]) -> TranscriptRewrite:
        """old_lines から removed の行を除いた書き換え"""
        gone = set(removed)
        kept: list[int | None] = []
        new_lines: list[str] = []
        for i, line in enumerate(old_lines):
            if i in gone:
                kept.append(None)
            else:
                kept.append(len(new_lines))
                new_lines.append(line)
        return cls(tuple(old_lines), tuple(kept), tuple(new_lines))

    def map_offset(self, old_offset: int) -> int:
        """旧ファイルのバイト位置を新ファイルのバイト位置へ写す。

        残った行の中 → 新しい行の開始 + 行内の位置（新しい行の長さで頭打ち）。
        消えた行の中 → 次に残る行の開始（無ければ新しい末尾）。
        旧末尾以降 → 新しい末尾 + はみ出し分（書き換え後に追記された分）。
        """
        old_pos, new_pos = _starts(self.old_lines), _starts(self.new_lines)
        if old_offset >= old_pos[-1]:
            return new_pos[-1] + (old_offset - old_pos[-1])
        i = bisect.bisect_right(old_pos, old_offset) - 1
        if (j := self.kept[i]) is not None:
            return new_pos[j] + min(old_offset - old_pos[i], new_pos[j + 1] - new_pos[j])
        nxt = next((k for k in self.kept[i + 1:] if k is not None), None)
        return new_pos[-1] if nxt is None else new_pos[nxt]


class TranscriptRewriteJournal:
    """パスごとの書き換え履歴。世代番号で「どこまで写したか」を読み手が覚える"""

    def __init__(self, history: int = REWRITE_HISTORY) -> None:
        self._lock = threading.Lock()
        self._generation: dict[str, int] = {}
        self._rewrites: dict[str, collections.deque[TranscriptRewrite]] = {}
        self._history = history

    def generation(self, path: str) -> int:
        with self._lock:
            return self._generation.get(path, 0)

    def record_rewrite(self, path: str, rewrite: TranscriptRewrite) -> int:
        """書き換えを記録し、新しい世代を返す"""
        with self._lock:
            self._rewrites.setdefault(path, collections.deque(maxlen=self._history)).append(rewrite)
            gen = self._generation[path] = self._generation.get(path, 0) + 1
            return gen

    def remap_since(self, path: str, generation: int, offset: int) -> tuple[int | None, int]:
        """generation より後の書き換えを順に当てて (新しい offset, 現在の世代) を返す。

        読み手が履歴に残っているより古ければ offset は None（写せないので読み手が立て直す）。
        """
        with self._lock:
            current = self._generation.get(path, 0)
            pending = current - generation
            if pending <= 0:
                return offset, current
            rewrites = self._rewrites.get(path, ())
            if pending > len(rewrites):
                return None, current
            for rw in list(rewrites)[len(rewrites) - pending:]:
                offset = rw.map_offset(offset)
            return offset, current
