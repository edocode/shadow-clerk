"""Shadow-clerk: 文字起こしの置き場所（区分 / 会議フォルダ）

  <root>/<区分>/<会議名>/                 会議名の付いた回のファイル一式
  <root>/<既定の区分>/@dates/YYYY-MM/     会議名のない記録（日次・名前なしの会議）

区分は置き場所にすぎず、振る舞いを持たない。一覧の先頭が既定（非公開側）で、
会議名のない記録と、区分を決めていない会議はそこに入る。ファイル名は従来どおり
`@会議名` を含む——ファイル名だけで会議が分かり、外へコピーしてもそのまま使える。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
from collections.abc import Iterable, Iterator

from shadow_clerk import DATA_DIR
from shadow_clerk._transcript_name import KNOWN_LANGUAGE_CODES, TranscriptName, sanitize_meeting_name

logger = logging.getLogger("shadow-clerk")

DEFAULT_CATEGORIES: tuple[str, ...] = ("private", "sharable", "isolated")
# `@` は sanitize_meeting_name が落とすので、会議名のフォルダと衝突しない
UNNAMED_DIR = "@dates"

# 会議の回に属するファイル。移行前の会議名は `.` を含みうる（規則より前の名前）ので
# 最短一致で取り、後ろの拡張子側を列挙して確定させる
_OWNED_RE = re.compile(
    r'^(transcript|summary|advice|analysis|minutes|shot)-(\d{8,12})(?:@(.+?))?'
    rf'(-\d{{6}}\.png|(?:-(?:{"|".join(KNOWN_LANGUAGE_CODES)}))?\.txt(?:\.[\w-]+)?'
    r'|\.(?:attendees|provisional)\.json|\.(?:voices|naming)\.jsonl|\.md)$')


# transcript の [画面] 行が指すスクショ。transcript からの相対パス（同じフォルダなのでファイル名）
_SHOT_REF_RE = re.compile(r"画面キャプチャ: (shot-[^\s|/\\]+\.png)")


def carry_shots(lines: Iterable[str], src_dir: str, dst_dir: str) -> int:
    """行が参照するスクショを src_dir から dst_dir へ移し、移した数を返す。

    スクショは参照する transcript と同じフォルダに置く（transcript には相対パス＝ファイル名で書く）。
    行を別の会議へ動かすとき（リネーム・切り出し・日次へ戻す）に一緒に移さないと参照が切れる。
    ファイル名は変えない——本文がその名前で参照している
    """
    moved = 0
    for name in dict.fromkeys(m[1] for line in lines if (m := _SHOT_REF_RE.search(line))):
        src, dst = os.path.join(src_dir, name), os.path.join(dst_dir, name)
        if src_dir != dst_dir and os.path.isfile(src) and not os.path.exists(dst):
            os.makedirs(dst_dir, exist_ok=True)
            shutil.move(src, dst)
            moved += 1
    return moved


def owner(filename: str) -> TranscriptName | None:
    """会議の回に属するファイル名（transcript・翻訳・offset・summary・advice・analysis・
    minutes・attendees・voices・naming・provisional・shot）から、その回を引く。属さなければ None"""
    m = _OWNED_RE.match(filename)
    return TranscriptName(m[2], m[3]) if m else None


def valid_category(name: object) -> bool:
    return isinstance(name, str) and bool(name) and sanitize_meeting_name(name) == name


class TranscriptLayout:
    """データフォルダの中の、会議の回ごとの置き場所"""

    def __init__(self, root: str, categories: Iterable[str] = DEFAULT_CATEGORIES,
                 references: Iterable[str] = ()) -> None:
        self.root = root
        self.categories = tuple(c for c in dict.fromkeys(categories) if valid_category(c)) or DEFAULT_CATEGORIES
        self.references = tuple(r for r in references if isinstance(r, str) and r.strip())

    @classmethod
    def from_config(cls, config: dict | None = None, root: str | None = None) -> "TranscriptLayout":
        if config is None:
            from shadow_clerk._daemon_config import load_config
            config = load_config()
        if root is None:
            out = config.get("output_directory")
            root = os.path.expanduser(out) if out else DATA_DIR
        cats, refs = config.get("transcript_categories"), config.get("ai_reference_dirs")
        return cls(root, cats if isinstance(cats, list) else DEFAULT_CATEGORIES,
                   refs if isinstance(refs, list) else ())

    @property
    def default_category(self) -> str:
        return self.categories[0]

    # --- 会議フォルダ ---

    def meeting_dir(self, name: str) -> str | None:
        """既にある会議フォルダ。どの区分にも無ければ None"""
        folder = sanitize_meeting_name(name)
        for category in self.categories if folder else ():
            if os.path.isdir(path := os.path.join(self.root, category, folder)):
                return path
        return None

    def category_of(self, name: str) -> str:
        """会議の区分。フォルダがあればその場所、無ければ会議設定、それも無ければ既定"""
        if d := self.meeting_dir(name):
            return os.path.basename(os.path.dirname(d))
        from shadow_clerk.domain.meeting_config import MeetingConfig
        category = MeetingConfig.load().resolve(name).get("category") or ""
        return category if category in self.categories else self.default_category

    def meeting_folder(self, name: str) -> str:
        """会議のフォルダ（無ければ作る）"""
        folder = sanitize_meeting_name(name)
        d = self.meeting_dir(folder) or os.path.join(self.root, self.category_of(folder), folder)
        os.makedirs(d, exist_ok=True)
        return d

    def dir_of(self, tn: TranscriptName) -> str:
        """その回のファイルを置くフォルダ（無ければ作る）"""
        if tn.meeting_name and sanitize_meeting_name(tn.meeting_name):
            return self.meeting_folder(tn.meeting_name)
        dt = tn.datetime_str
        d = os.path.join(self.root, self.default_category, UNNAMED_DIR, f"{dt[:4]}-{dt[4:6]}")
        os.makedirs(d, exist_ok=True)
        return d

    def reference_dirs(self, meeting: str, extra: Iterable[str] = ()) -> list[str]:
        """会議中の AI が、その会議のフォルダのほかに参考にしてよいフォルダ（全体の設定 + 会議ごとの設定 + extra）。

        相対パスはデータフォルダから数える（`sharable` や `private/1on1` と書ける）。実在するものだけ返す。
        会議のフォルダ自身とホーム（全部が読めてしまう）は入れない
        """
        from shadow_clerk.domain.meeting_config import MeetingConfig
        skip = {self.meeting_dir(meeting) if meeting else None, os.path.expanduser("~")}
        out: list[str] = []
        for entry in (*self.references, *MeetingConfig.load().resolve(meeting)["reference_dirs"], *extra):
            path = os.path.normpath(os.path.join(self.root, os.path.expanduser(entry.strip())))
            if os.path.isdir(path) and path not in out and path not in skip:
                out.append(path)
        return out

    def path(self, filename: str) -> str | None:
        """回に属するファイル名をフルパスにする。属さない名前・ディレクトリを跨ぐ名前は None"""
        if os.path.basename(filename) != filename or (tn := owner(filename)) is None:
            return None
        return os.path.join(self.dir_of(tn), filename)

    # --- 一覧 ---

    def meeting_dirs(self) -> Iterator[tuple[str, str, str]]:
        """(区分, 会議名, パス) を返す。会議名のない記録のフォルダは含まない"""
        for category in self.categories:
            base = os.path.join(self.root, category)
            for name in sorted(_listdir(base)):
                if name != UNNAMED_DIR and os.path.isdir(path := os.path.join(base, name)):
                    yield category, name, path

    def dirs(self) -> Iterator[str]:
        """回のファイルが入りうるフォルダをすべて返す"""
        for category in self.categories:
            unnamed = os.path.join(self.root, category, UNNAMED_DIR)
            for month in sorted(_listdir(unnamed)):
                if os.path.isdir(path := os.path.join(unnamed, month)):
                    yield path
        for _, _, path in self.meeting_dirs():
            yield path

    def files(self) -> dict[str, str]:
        """ファイル名 → フルパス（すべてのフォルダ）"""
        return {f: os.path.join(d, f) for d in self.dirs() for f in _listdir(d)}

    # --- 移動 ---

    def move_meeting(self, name: str, category: str) -> str:
        """会議フォルダを別の区分へ移し、移した先を返す。移す先に同名のフォルダがあれば ValueError"""
        if category not in self.categories:
            raise ValueError(f"unknown category: {category}")
        src = self.meeting_dir(name)
        dst = os.path.join(self.root, category, sanitize_meeting_name(name))
        if src is None or src == dst:
            return dst
        if os.path.exists(dst):
            raise ValueError(f"already exists: {dst}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        logger.info("会議フォルダを移動: %s -> %s", src, dst)
        return dst

    def migrate_flat(self) -> dict[str, str]:
        """データフォルダ直下に残るフラットなファイルを新しい構成へ移す。{旧パス: 新パス} を返す。

        残っているファイルで判定するので、何度呼んでも同じ結果になる。会議名は
        sanitize_meeting_name に通して付け直す（規則より前に作られた名前がある）
        """
        moved: dict[str, str] = {}
        for fname in sorted(_listdir(self.root)):
            src = os.path.join(self.root, fname)
            if not os.path.isfile(src) or (m := _OWNED_RE.match(fname)) is None:
                continue
            prefix, dt, name, suffix = m.groups()
            clean = sanitize_meeting_name(name) if name else ""
            dst = os.path.join(self.dir_of(TranscriptName(dt, clean or None)),
                               f"{prefix}-{dt}{'@' + clean if clean else ''}{suffix}")
            if os.path.exists(dst):
                logger.warning("移行先に同名のファイルがあるため残します: %s", src)
                continue
            shutil.move(src, dst)
            moved[src] = dst
        if moved:
            logger.info("文字起こしを新しいフォルダ構成へ移しました: %d 件", len(moved))
        return moved


def migrate_flat_files(session_file: str) -> None:
    """起動時の移行。会議中に再起動されたときのため、セッションファイルが指すパスも付け替える"""
    moved = TranscriptLayout.from_config().migrate_flat()
    try:
        with open(session_file, "r", encoding="utf-8") as f:
            session = f.read().strip()
        if session in moved:
            with open(session_file, "w", encoding="utf-8") as f:
                f.write(moved[session])
    except OSError:
        pass


def _listdir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []
