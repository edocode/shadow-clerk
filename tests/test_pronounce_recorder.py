"""お手本の gate と、文字起こしスレッドからワーカーへの受け渡しの検証

実行: uv run python tests/test_pronounce_recorder.py
モデルも音声デバイスも不要。
"""
from __future__ import annotations
import os
import sys
import tempfile
import threading

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["SHADOW_CLERK_DATA_DIR"] = tempfile.mkdtemp(prefix="shadow-clerk-pronounce-rec-")

from shadow_clerk._daemon_talk import _PlaybackSpan  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def test_span_open_while_speaking() -> None:
    span = _PlaybackSpan(tail_sec=0.3)
    check("何も鳴っていなければ素通し", not span.covers(100.0, 101.0))
    span.open(100.0)
    check("読み上げ中に始まったセグメントは捨てる", span.covers(100.5, 101.5))
    # 長い課題文の途中で VAD が閉じると、セグメントは読み上げの終了前に届く。
    # 「終わってから記録」にするとここが素通りする（設計書 §8.1 の本題）
    check("読み上げ中なら、いつ始まったものでも捨てる", span.covers(103.0, 104.0))
    # 物音で VAD が先に開くと、お手本はそのセグメントの中で鳴る。開始だけを見ると素通りする
    check("読み上げをまたぐセグメントは捨てる", span.covers(99.0, 101.5))
    check("読み上げの前に始まり、始まる前に終わったものは残す", not span.covers(98.0, 99.5))
    span.close(101.8)
    check("実終了 + tail までは捨てる", span.covers(102.0, 103.0))
    # 見積もりは 8 文字/秒なので "Turn right at the light." なら 3.0 秒。
    # 実際は 1.8 秒で終わる。ユーザーが 2.3 秒で言い始めた試行を捨ててはいけない
    check("実終了のあとに始まったセグメントは残す", not span.covers(102.3, 104.0),
          "見積もりベースだと 103.0 まで捨ててしまう")


def test_span_reopens() -> None:
    span = _PlaybackSpan(tail_sec=0.3)
    span.open(100.0)
    span.close(101.0)
    span.open(105.0)
    check("次の文で開き直す", span.covers(105.5, 106.5))
    check("前の区間は残らない", not span.covers(102.0, 104.0))


def test_span_keeps_earlier_sentences() -> None:
    # お手本は文ごとに open/close される（TtsPlayer が文単位でキューに積むため）。
    # 文1の最中に VAD が閉じたセグメントは、文字起こしを終えて届く頃には文2が始まっている。
    # 1区間だけ保持して上書きすると、ここで素通りしてお手本を学習者の発話として解析してしまう
    span = _PlaybackSpan(tail_sec=0.3)
    span.open(100.0)
    span.close(101.0)          # 文1
    span.open(101.5)           # 文2が鳴り始めた
    check("文1の最中に始まったセグメントは、文2が始まった後でも捨てる", span.covers(100.5, 100.9))
    check("文2の最中も捨てる", span.covers(101.8, 102.2))
    span.close(102.4)
    check("すべて鳴り終わった後に始まったセグメントは残す", not span.covers(102.9, 104.0))
    check("文1より前に始まり、文1が始まる前に終わったセグメントは残す", not span.covers(99.0, 99.5))


def test_span_prunes_old_entries() -> None:
    # 履歴が無限に伸びないこと
    span = _PlaybackSpan(tail_sec=0.3, keep_sec=1.0)
    for i in range(50):
        span.open(1000.0 + i)
        span.close(1000.3 + i)
    span.open(2000.0)
    check("古い区間は捨てる", not span.covers(1000.1, 1000.5), "1000.1 は 1000 秒前の区間")
    check("直近は残る", span.covers(2000.5, 2001.0))


def test_player_opens_and_closes_span() -> None:
    from shadow_clerk._daemon_tts import TtsPlayer

    spans: list[tuple[float, float | None]] = []
    played: list[int] = []

    class _Backend:
        LANGUAGES = ()
        DEFAULT_LANGUAGE = None

        def check(self) -> None: ...
        def synthesize(self, text: str):
            return np.zeros(1600, dtype=np.float32), 16000
        def credit(self) -> str:
            return ""
        def voices(self) -> list:
            return []

    done = threading.Event()

    def _play(pcm, sr, should_stop) -> None:
        played.append(len(pcm))
        done.set()

    player = TtsPlayer(_Backend(), _play, lambda msg: None)
    player.set_on_span(lambda start, end: spans.append((start, end)))
    player.speak("hello")
    done.wait(5.0)
    player.close(discard_pending=False)
    check("開いて閉じる、の2回呼ばれる", len(spans) == 2, repr(spans))
    check("1回目は未終了", spans and spans[0][1] is None, repr(spans))
    check("2回目は実終了", len(spans) == 2 and spans[1][1] is not None, repr(spans))
    check("開始時刻は同じ", len(spans) == 2 and spans[0][0] == spans[1][0], repr(spans))
    check("実終了は開始より後", len(spans) == 2 and spans[1][1] >= spans[1][0], repr(spans))


from shadow_clerk._daemon_recorder_transcribe import _RecorderTranscribeMixin  # noqa: E402


class _Talk:
    def __init__(self, playback: bool = False, active: bool = True) -> None:
        self.active = active
        self.playback = playback
        self.playback_calls: list[tuple[float, float]] = []

    def is_suppressed(self, source: str) -> bool:
        return False

    def is_echo(self, source: str, s: float, e: float, text: str) -> bool:
        return False

    def in_playback(self, seg_start: float, seg_end: float) -> bool:
        self.playback_calls.append((seg_start, seg_end))
        return self.playback

    def on_self_line(self, line) -> None: ...
    def on_other_line(self, line) -> None: ...
    def clear_interim(self, source: str) -> None: ...


class _Pronounce:
    def __init__(self) -> None:
        self.offers: list[tuple] = []

    def offer(self, pcm, segment_at: str, asr_text: str) -> None:
        self.offers.append((len(pcm), segment_at, asr_text))


class _Rec(_RecorderTranscribeMixin):
    def __init__(self, talk: _Talk, said: str = "turn right at the light") -> None:
        self.mute_mic = self.mute_monitor = False
        self._explicit_output = True
        self.output_path = os.path.join(tempfile.mkdtemp(), "transcript-20261018.txt")
        self.transcript_lock = threading.Lock()
        self.transcriber = type("_T", (), {"language": "en",
                                           "transcribe": staticmethod(lambda seg: said)})()
        # word_replacer のあとのテキストが渡ること。ここで必ず書き換える
        self.word_replacer = type("_W", (), {
            "apply": staticmethod(lambda text, lang: text.replace("rite", "right"))})()
        self.talk = talk
        self.pronounce = _Pronounce()

    def _extract_command_body(self, text: str) -> str | None:
        return None

    def _spell_and_match(self, *args: object) -> None: ...
    def _llm_match_and_execute(self, *args: object) -> None: ...


def _run(rec: _Rec, source: str = "mic", command_mode: bool = False,
         seg_start: float = 1000.25) -> None:
    rec._process_transcribe_item(np.zeros(16000, dtype=np.float32), "2026-10-18 10:00:00",
                                 seg_start, source, command_mode,
                                 {"mic": "自分", "monitor": "相手"}, None)


def test_mic_segment_is_offered() -> None:
    rec = _Rec(_Talk())
    _run(rec)
    check("mic のセグメントをワーカーに渡す", len(rec.pronounce.offers) == 1, repr(rec.pronounce.offers))
    check("segment_at は timestamp 引数そのまま",
          rec.pronounce.offers[0][1] == "2026-10-18 10:00:00", repr(rec.pronounce.offers))
    check("asr_text は確定テキスト",
          rec.pronounce.offers[0][2] == "turn right at the light", repr(rec.pronounce.offers))
    check("セグメントの PCM を渡す", rec.pronounce.offers[0][0] == 16000)


def test_word_replacer_applied_first() -> None:
    rec = _Rec(_Talk(), said="turn rite at the light")
    _run(rec)
    check("word_replacer を通したあとのテキストを渡す",
          rec.pronounce.offers[0][2] == "turn right at the light", repr(rec.pronounce.offers))


def test_playback_segment_is_not_offered() -> None:
    rec = _Rec(_Talk(playback=True))
    _run(rec)
    check("読み上げと重なるセグメントは渡さない", rec.pronounce.offers == [],
          repr(rec.pronounce.offers))
    check("それでも transcript には書く", len(_lines(rec)) == 1, repr(_lines(rec)))


def test_playback_gate_gets_the_segment_end() -> None:
    # 開始だけ渡すと、読み上げをまたぐセグメントが gate を抜ける。終了（開始 + 長さ）も渡すこと
    talk = _Talk()
    rec = _Rec(talk)
    _run(rec)     # _run は 16000 サンプル = 1.0 秒のセグメントを流す
    check("gate に開始と終了を渡す", talk.playback_calls == [(1000.25, 1001.25)],
          repr(talk.playback_calls))


def test_monitor_is_not_offered() -> None:
    rec = _Rec(_Talk())
    _run(rec, source="monitor")
    check("monitor は渡さない（自分の発音だけが対象）", rec.pronounce.offers == [])


def test_command_mode_is_not_offered() -> None:
    rec = _Rec(_Talk())
    _run(rec, command_mode=True)
    check("コマンドモードのセグメントは渡さない", rec.pronounce.offers == [])


def test_noise_text_is_still_offered() -> None:
    # ノイズフィルタより前に渡す。相槌と判定されて transcript に出ない発話も attempt には残す
    rec = _Rec(_Talk(), said="あっ")
    _run(rec)
    check("ノイズフィルタで捨てる行も渡す", len(rec.pronounce.offers) == 1, repr(rec.pronounce.offers))
    check("transcript には書かない", _lines(rec) == [], repr(_lines(rec)))


def test_inactive_talk_is_not_offered() -> None:
    # arm の TTL (5分) の間に talk mode を止めると、/api/say のお手本は gate を通らない。
    # talk.active を見ていないと、お手本を学習者の発話として解析してしまう
    rec = _Rec(_Talk(active=False))
    _run(rec)
    check("talk mode が止まっていたら渡さない", rec.pronounce.offers == [], repr(rec.pronounce.offers))


def test_offer_failure_does_not_break_transcription() -> None:
    # Review Focus 2: キューが満杯でも文字起こしを止めない
    class _Full(_Pronounce):
        def offer(self, pcm, segment_at: str, asr_text: str) -> None:
            raise RuntimeError("queue is full")

    rec = _Rec(_Talk())
    rec.pronounce = _Full()
    _run(rec)
    check("渡すところで落ちても transcript は書ける", len(_lines(rec)) == 1, repr(_lines(rec)))


def _lines(rec: _Rec) -> list[str]:
    if not os.path.exists(rec.output_path):
        return []
    with open(rec.output_path, encoding="utf-8") as f:
        return f.read().splitlines()


if __name__ == "__main__":
    test_span_open_while_speaking()
    test_span_reopens()
    test_span_keeps_earlier_sentences()
    test_span_prunes_old_entries()
    test_player_opens_and_closes_span()
    test_mic_segment_is_offered()
    test_word_replacer_applied_first()
    test_playback_segment_is_not_offered()
    test_playback_gate_gets_the_segment_end()
    test_monitor_is_not_offered()
    test_command_mode_is_not_offered()
    test_noise_text_is_still_offered()
    test_inactive_talk_is_not_offered()
    test_offer_failure_does_not_break_transcription()
    sys.exit(0 if all(results) else 1)
