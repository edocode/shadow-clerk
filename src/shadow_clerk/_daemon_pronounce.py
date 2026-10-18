"""Shadow-clerk daemon: 発音フィードバックの突き合わせ（音韻クラス・アライメント・語への帰属）

daemon が持つのは音韻クラスまで。どの差分が意味を持つかの判断と学習者への言い方は
スキル（Claude）の側に置く（設計書 §2）。
"""
from __future__ import annotations

import bisect
import datetime
import logging
import queue
import threading
import time
import uuid
from functools import lru_cache
from typing import Any, Callable, Sequence

from shadow_clerk._daemon_config import load_config
from shadow_clerk._daemon_pronounce_ipa import (
    G2PError, PhonemeRecogniser, expected_ipa, has_espeak, has_torch, split_words, word_key,
)
from shadow_clerk.domain import (
    Attempt, FocusPhoneme, Language, OpKind, PhonemeOp, PronounceState, PronunciationTask,
    WordComparison,
)

logger = logging.getLogger("shadow-clerk")

# 正規化後のアルファベットに対する母音クラス。æ ɑ ɒ ɔ ɪ ə ɐ ʌ ᵻ ɨ ɜ ɚ は
# 正規化で A O @ R になるのでここには現れない（設計書 §4.1）
VOWELS: frozenset[str] = frozenset({
    "@", "R", "O", "A",                                   # 正規化のクラス記号
    "i", "e", "ɛ", "a", "u", "ʊ", "ʉ", "y", "ø", "œ", "ɤ", "ɯ", "ɘ", "ɞ", "ɵ",
    "aɪ", "aʊ", "ɔɪ", "eɪ", "oʊ", "əʊ", "ɪə", "ɛə", "ʊə",  # 二重母音
})
# スパイクでモデルが実際に出した子音。母音表と合わせて「既知の記号」を成す。
# どちらにも無い記号が来たら、表を広げる必要があるという合図なので WARNING を出す
CONSONANTS: frozenset[str] = frozenset({
    "b", "d", "dʒ", "f", "h", "j", "k", "l", "m", "n", "ŋ", "p", "r", "ɹ",
    "s", "ʃ", "t", "tʃ", "θ", "ð", "v", "w", "z", "ʒ", "ɡ",
})
# 結合記号。表に無い記号を基底文字で引き直すときに外す
_COMBINING = "̩̥̪̝̞̠̃̈"


@lru_cache(maxsize=None)
def is_vowel(symbol: str) -> bool:
    """母音クラスか。母音表にも子音表にも無い記号は、子音として扱って WARNING を1行出す"""
    if symbol in VOWELS:
        return True
    if symbol in CONSONANTS:
        return False
    base = symbol.strip(_COMBINING)
    if base in VOWELS:
        return True
    if base in CONSONANTS:
        return False
    logger.warning("pronounce: 音素クラス表に無い記号 %r を子音として扱います", symbol)
    return False


def _sub_cost(expected: str, actual: str) -> int | None:
    """置換のコスト。クラスをまたぐ置換は演算として持たない（None = 不許可）"""
    if expected == actual:
        return 0
    return 1 if is_vowel(expected) == is_vowel(actual) else None


def align(expected: Sequence[str], actual: Sequence[str]) -> tuple[tuple[OpKind, str, str], ...]:
    """音韻クラスで重み付けした編集経路。同コストなら same < sub < del < ins の辞書順最小。

    末尾からのバックトレースでは「先頭から辞書順最小」にならないので、
    先に接尾コスト表を作り、先頭から貪欲に選ぶ（設計書 §4.1）
    """
    n, m = len(expected), len(actual)
    inf = float("inf")
    # rest[i][j] = expected[i:] と actual[j:] を揃える最小コスト
    rest: list[list[float]] = [[inf] * (m + 1) for _ in range(n + 1)]
    rest[n][m] = 0.0
    for i in range(n, -1, -1):
        for j in range(m, -1, -1):
            if i == n and j == m:
                continue
            best = inf
            if i < n and j < m and (cost := _sub_cost(expected[i], actual[j])) is not None:
                best = min(best, cost + rest[i + 1][j + 1])
            if i < n:
                best = min(best, 1 + rest[i + 1][j])
            if j < m:
                best = min(best, 1 + rest[i][j + 1])
            rest[i][j] = best

    ops: list[tuple[OpKind, str, str]] = []
    i = j = 0
    while i < n or j < m:
        if i < n and j < m and expected[i] == actual[j] and rest[i + 1][j + 1] == rest[i][j]:
            ops.append((OpKind.SAME, expected[i], actual[j]))
            i, j = i + 1, j + 1
            continue
        if i < n and j < m:
            cost = _sub_cost(expected[i], actual[j])
            if cost is not None and cost + rest[i + 1][j + 1] == rest[i][j]:
                ops.append((OpKind.SUB, expected[i], actual[j]))
                i, j = i + 1, j + 1
                continue
        if i < n and 1 + rest[i + 1][j] == rest[i][j]:
            ops.append((OpKind.DEL, expected[i], ""))
            i += 1
            continue
        ops.append((OpKind.INS, "", actual[j]))
        j += 1
    return tuple(ops)


def compare(words: Sequence[str], per_word: Sequence[Sequence[str]],
            actual: Sequence[str], focus: Sequence[FocusPhoneme]) -> tuple[WordComparison, ...]:
    """語ごとの期待列と発話全体の実測列を突き合わせ、語ごとの対応に切り分ける。

    アライメントは連結した期待列に対して1回だけ掛け、期待側の index で語に帰属させる。
    ins は直前に消費した期待音素の語に付く。同名の語が複数あっても境界の位置で引くので混ざらない
    """
    expected = [p for seq in per_word for p in seq]
    # bounds[i] = i 語目の期待列が始まる位置。語の長さが 0 でも破綻しないよう右端で引く
    bounds: list[int] = []
    total = 0
    for seq in per_word:
        bounds.append(total)
        total += len(seq)
    focused = _focus_positions(words, per_word, focus)

    def word_at(position: int) -> int:
        if not words:
            return 0
        return max(0, min(bisect.bisect_right(bounds, min(position, total - 1 if total else 0)) - 1,
                          len(words) - 1))

    ops_of: list[list[PhonemeOp]] = [[] for _ in words]
    actual_of: list[list[str]] = [[] for _ in words]
    consumed = 0
    for kind, exp_sym, act_sym in align(expected, actual):
        index = word_at(consumed - 1 if kind is OpKind.INS else consumed)
        ops_of[index].append(
            PhonemeOp(kind, exp_sym, act_sym, kind is not OpKind.INS and consumed in focused))
        if act_sym:
            actual_of[index].append(act_sym)
        if kind is not OpKind.INS:
            consumed += 1
    return tuple(WordComparison(words[i], tuple(per_word[i]), tuple(actual_of[i]), tuple(ops_of[i]))
                 for i in range(len(words)))


def _focus_positions(words: Sequence[str], per_word: Sequence[Sequence[str]],
                     focus: Sequence[FocusPhoneme]) -> set[int]:
    """focus が指す音素が、連結した期待列の何番目かを集める。見つからないものは黙って捨てる
    （POST の時点で検証済み。ここは防御的な処理）"""
    keys = [word_key(w) for w in words]
    starts: list[int] = []
    total = 0
    for seq in per_word:
        starts.append(total)
        total += len(seq)
    out: set[int] = set()
    for item in focus:
        hits = [i for i, key in enumerate(keys) if key == word_key(item.word)]
        if item.index >= len(hits):
            continue
        at = hits[item.index]
        inside = [i for i, sym in enumerate(per_word[at]) if sym == item.phoneme]
        if item.phoneme_index < len(inside):
            out.add(starts[at] + inside[item.phoneme_index])
    return out


_ARM_TTL_SEC = 300.0
_MAX_ATTEMPTS = 3
_QUEUE_SIZE = 4
_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
# pronounce_idle_unload_sec が 0（解放しない）のときの、キュー待ちの刻み
_IDLE_POLL_SEC = 60.0


class ArmError(Exception):
    """課題を受け付けられない。expected を添えると、正しい記号で再 POST させられる"""

    def __init__(self, message: str, expected: list[dict] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.expected = expected


class PronounceDriver:
    """課題のアーム、解析ワーカー、結果の保持。

    daemon は判定しない。期待IPAと実測IPAの語ごとの対応を返して終わり（設計書 §2）
    """

    def __init__(self, recogniser_factory: Callable[[], Any] | None = None,
                 clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._factory = recogniser_factory or self._default_recogniser
        self._recogniser: Any = None
        self._lock = threading.Lock()
        self._queue: queue.Queue[tuple[str, Any, str, str] | None] = queue.Queue(maxsize=_QUEUE_SIZE)
        self._pending = 0
        self._arm_id = ""
        self._task: PronunciationTask | None = None
        self._words: tuple[str, ...] = ()
        self._per_word: tuple[tuple[str, ...], ...] = ()
        self._expires = 0.0
        self._attempts: list[Attempt] = []
        self._loading = False
        self._worker = threading.Thread(target=self._run, name="pronounce", daemon=True)
        self._worker.start()

    # --- 設定と依存 -----------------------------------------------------

    @staticmethod
    def _default_recogniser() -> Any:
        config = load_config()
        return PhonemeRecogniser(str(config.get("pronounce_model") or ""),
                                 str(config.get("pronounce_device") or "cpu"),
                                 int(config.get("pronounce_threads") or 0))

    @staticmethod
    def _enabled() -> bool:
        return bool(load_config().get("pronounce_enabled"))

    def _expected_of(self, word: str, language: Language) -> tuple[str, ...]:
        """1語の正規化後の期待IPA。テストで差し替えられるようメソッドにしてある"""
        return expected_ipa(word, language)

    def _unavailable(self) -> str | None:
        """使えない理由。使えるなら None"""
        if not has_torch() or not has_espeak():
            return "not_installed"
        return None if self._enabled() else "disabled"

    # --- アーム ---------------------------------------------------------

    def arm(self, task: PronunciationTask) -> dict:
        """課題を受け付ける。拒否は ArmError（呼び手が status: error にする）"""
        if (reason := self._unavailable()) is not None:
            raise ArmError(reason)
        words = split_words(task.text)
        if not words:
            raise ArmError("text has no words")
        if any(ch.isdigit() for ch in task.text):
            raise ArmError("text must not contain digits; spell numbers out")
        try:
            per_word = tuple(self._expected_of(w, task.language) for w in words)
        except G2PError as e:
            raise ArmError(str(e)) from e
        self._check_focus(task, words, per_word)
        expected = [{"word": w, "ipa": list(ipa)} for w, ipa in zip(words, per_word)]
        with self._lock:
            self._arm_id = uuid.uuid4().hex
            self._task, self._words, self._per_word = task, words, per_word
            self._expires = self._clock() + _ARM_TTL_SEC
            self._attempts = []
            arm_id, expires = self._arm_id, self._expires
        self._start_loading()
        logger.info("pronounce: アームしました (%d 語)", len(words))
        with self._lock:
            state = self._state_locked()
        return {"status": "ok", "id": arm_id, "state": state.value,
                "expires_at": _format_time(expires), "expected": expected}

    def _start_loading(self) -> None:
        """最初の POST でモデルの取得を始める。初回は 1.2GB のダウンロードがある（設計書 §9）。
        読み込みが終わるまで state は loading。API スレッドは塞がない"""
        with self._lock:
            if self._recogniser is not None and self._recogniser.loaded:
                return
            if self._loading:
                return
            self._loading = True
        threading.Thread(target=self._load, name="pronounce-load", daemon=True).start()

    def _load(self) -> None:
        try:
            if self._recogniser is None:
                self._recogniser = self._factory()
            self._recogniser.load()
        except Exception as e:
            logger.warning("pronounce: モデルを読み込めませんでした: %s", e)
        finally:
            with self._lock:
                self._loading = False

    @staticmethod
    def _check_focus(task: PronunciationTask, words: tuple[str, ...],
                     per_word: tuple[tuple[str, ...], ...]) -> None:
        keys = [word_key(w) for w in words]
        for item in task.focus:
            hits = [i for i, key in enumerate(keys) if key == word_key(item.word)]
            if item.index >= len(hits):
                raise ArmError(f"focus word {item.word!r} is not in the text")
            ipa = per_word[hits[item.index]]
            if ipa.count(item.phoneme) <= item.phoneme_index:
                # 正しい記号で再 POST させるために、その語の期待IPAを添える
                raise ArmError(
                    f"focus phoneme {item.phoneme!r} is not in the expected IPA of {item.word!r}",
                    [{"word": words[hits[item.index]], "ipa": list(ipa)}])

    def clear(self) -> None:
        with self._lock:
            self._arm_id, self._task, self._words, self._per_word = "", None, (), ()
            self._expires, self._attempts = 0.0, []

    # --- 状態 -----------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            expired = self._task is not None and self._clock() >= self._expires
            if expired:
                self._arm_id, self._task, self._words, self._per_word = "", None, (), ()
                self._expires, self._attempts = 0.0, []
            state = self._state_locked()
            out = {"state": state.value, "pending": self._pending,
                   "expires_at": _format_time(self._expires) if self._task else "",
                   "task": None if self._task is None else dict(self._task.to_json(), id=self._arm_id),
                   "attempts": [a.to_json() for a in self._attempts]}
            if state is PronounceState.UNAVAILABLE:
                # not_installed なら導入コマンドを、disabled なら設定を案内できるようにする
                out["reason"] = self._unavailable()
            return out

    def _state_locked(self) -> PronounceState:
        if self._unavailable() is not None:
            return PronounceState.UNAVAILABLE
        if self._loading:
            return PronounceState.LOADING
        return PronounceState.ARMED if self._task is not None else PronounceState.IDLE

    def unavailable_reason(self) -> str | None:
        return self._unavailable()

    # --- 解析 -----------------------------------------------------------

    def offer(self, pcm: Any, segment_at: str, asr_text: str) -> None:
        """armed ならワーカーに渡す。文字起こしのクリティカルパスに載るのはここだけ"""
        with self._lock:
            if self._task is None or self._clock() >= self._expires:
                return
            arm_id = self._arm_id
            self._pending += 1
        try:
            self._queue.put_nowait((arm_id, pcm, segment_at, asr_text))
        except queue.Full:
            # Review Focus 2: 詰まったら捨てる。文字起こしを止めてはいけない
            with self._lock:
                self._pending -= 1
            logger.warning("pronounce: 解析が追いつかないのでセグメントを捨てました")

    def _run(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=self._idle_unload_sec())
            except queue.Empty:
                self._unload_if_idle()   # 一定時間使われなければモデルを解放する（設計書 §9）
                continue
            if item is None:
                return
            arm_id, pcm, segment_at, asr_text = item
            try:
                self._analyse(arm_id, pcm, segment_at, asr_text)
            except Exception as e:       # どの失敗も文字起こしに波及させない（設計書 §10）
                logger.warning("pronounce: 解析に失敗しました: %s", e)
            finally:
                with self._lock:
                    self._pending -= 1

    @staticmethod
    def _idle_unload_sec() -> float:
        """この秒数だけキューが空ならモデルを解放する。0 以下なら解放しない"""
        value = float(load_config().get("pronounce_idle_unload_sec") or 0)
        return value if value > 0 else _IDLE_POLL_SEC

    def _unload_if_idle(self) -> None:
        """アイドルでモデルを解放する。import torch 自体のメモリは残る（設計書 §9）"""
        if float(load_config().get("pronounce_idle_unload_sec") or 0) <= 0:
            return
        with self._lock:
            if self._pending or self._loading:
                return
        if self._recogniser is not None and self._recogniser.loaded:
            self._recogniser.unload()

    def _analyse(self, arm_id: str, pcm: Any, segment_at: str, asr_text: str) -> None:
        with self._lock:
            if arm_id != self._arm_id:
                return                    # 差し替えられた古い解析
            words, per_word = self._words, self._per_word
            focus = self._task.focus if self._task else ()
        if self._recogniser is None:
            self._recogniser = self._factory()
        self._recogniser.load()           # 読み込み済みなら即 return する
        actual = self._recogniser.actual_ipa(pcm)
        attempt = Attempt(_format_time(self._clock()), segment_at, asr_text,
                          compare(words, per_word, actual, focus))
        with self._lock:
            if arm_id != self._arm_id:
                return
            # 積んでから pending を減らす。逆だと pending==0 で attempt が見えない瞬間ができる
            self._attempts.insert(0, attempt)
            del self._attempts[_MAX_ATTEMPTS:]


def _format_time(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch).strftime(_TIME_FORMAT)
