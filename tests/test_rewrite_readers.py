"""録音中の transcript をダッシュボードが書き直しても、バイト位置で追う読み手がずれないことの検証

- ダッシュボードの行削除は書き換えを記録し、translate_offset をロック内で写す
- 監視ストリーム（/api/watch）は書き換え後に会議全体を送り直さず、行の断片も送らない
- 翻訳ループは LLM 呼び出し中に書き換えが挟まっても、古い座標の offset で上書きしない

実行: uv run python tests/test_rewrite_readers.py
daemon も音声デバイスも不要。一時ディレクトリ内で完結する。
"""
from __future__ import annotations
import io
import json
import os
import subprocess
import tempfile
import threading
from collections import Counter
import time
import types

# **import より前に差し替えること。** SESSION_FILE は import 時に DATA_DIR から決まる
DATA = tempfile.mkdtemp(prefix="shadow-clerk-rewrite-")
os.environ["SHADOW_CLERK_DATA_DIR"] = DATA

from shadow_clerk._daemon_config import load_config  # noqa: E402
from shadow_clerk._daemon_dashboard_ops import _DashboardHandlerOps  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_meeting import _DashboardHandlerMeetingOps  # noqa: E402
from shadow_clerk._daemon_dashboard_ops_skill import _DashboardHandlerSkillOps  # noqa: E402
from shadow_clerk._daemon_recorder_translate import _RecorderTranslateMixin  # noqa: E402
from shadow_clerk._transcript_name import TranscriptName  # noqa: E402
from shadow_clerk.domain import TranscriptRewrite, TranscriptRewriteJournal  # noqa: E402
from shadow_clerk.domain.transcript_rewrite import REWRITE_HISTORY  # noqa: E402

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


class _Rec(_RecorderTranslateMixin):
    def __init__(self, output: str) -> None:
        self._output_dir = DATA
        self.output_path = output
        self.output_switch_offset: dict[str, int] = {}
        self.transcript_lock = threading.Lock()
        self.rewrite_journal = TranscriptRewriteJournal()
        self.stop_event = threading.Event()
        self._translate_stop_event = threading.Event()
        self.translate_target_path: str | None = None
        self.current_session = None
        self._translating_paths: Counter[str] = Counter()
        self._translating_lock = threading.Lock()


class _Handler(_DashboardHandlerOps, _DashboardHandlerMeetingOps, _DashboardHandlerSkillOps):
    """削除 API と監視ストリームを同じ recorder で回す偽物"""

    def __init__(self, rec: _Rec, body: dict | None = None, query: str = "") -> None:
        raw = json.dumps(body or {}).encode("utf-8")
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)
        self.path = "/api/watch?" + query
        self.client_address = ("127.0.0.1", 1)
        self.wfile = io.BytesIO()
        self.sent: dict = {}
        self.recorder = rec
        self.file_watcher = None

    def _send_json(self, d: dict) -> None:
        self.sent = d

    def send_response(self, code: int) -> None:
        pass

    def send_header(self, k: str, v: str) -> None:
        pass

    def end_headers(self) -> None:
        pass

    def send_error(self, code: int) -> None:
        raise AssertionError(code)


def _write(path: str, body: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)


def _append(path: str, body: str) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(body)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _delete(rec: _Rec, path: str, lines: list[str]) -> dict:
    h = _Handler(rec, {"lines": lines, "file": os.path.basename(path)})
    h._delete_transcript_line()
    return h.sent


def _b(s: str) -> int:
    return len(s.encode("utf-8"))


L = [f"[2026-10-04 10:0{i}:00] [自分] 発言その{i}です\n" for i in range(6)]


def test_delete_records_rewrite_and_remaps_offset() -> None:
    path = os.path.join(DATA, "transcript-20261001.txt")
    _write(path, "".join(L[:4]))
    _write(path + ".translate_offset", str(_b("".join(L[:3]))))
    rec = _Rec(path)
    sent = _delete(rec, path, [L[1]])
    check("削除は成功", sent.get("status") == "ok", repr(sent))
    check("書き換えを記録する", rec.rewrite_journal.generation(path) == 1)
    check("translate_offset は削除分だけ縮む", _read(path + ".translate_offset") == str(_b(L[0] + L[2])),
          _read(path + ".translate_offset"))


def test_extract_meeting_records_rewrite() -> None:
    path = os.path.join(DATA, "transcript-20261004.txt")
    _write(path, "".join(L[:4]))
    _write(path + ".translate_offset", str(_b("".join(L[:3]))))
    rec = _Rec(path)
    h = _Handler(rec, {"file": os.path.basename(path), "start_ts": "2026-10-04 10:01:00",
                       "end_ts": "2026-10-04 10:02:00"})
    h._extract_meeting()
    check("切り出しは成功", h.sent.get("status") == "ok", repr(h.sent))
    check("切り出しも書き換えを記録する", rec.rewrite_journal.generation(path) == 1)
    check("切り出しの translate_offset は抜いた分だけ縮む",
          _read(path + ".translate_offset") == str(_b(L[0])), _read(path + ".translate_offset"))


def _run_watch(rec: _Rec, during: callable) -> str:
    h = _Handler(rec, query="interval=1")
    th = threading.Thread(target=h._serve_watch, daemon=True)
    th.start()
    time.sleep(0.3)
    during()
    time.sleep(1.3)
    rec.stop_event.set()
    th.join(timeout=3)
    return h.wfile.getvalue().decode()


def test_watch_after_shrinking_delete_no_resend() -> None:
    """消した分が大きく、ファイルが読み位置より短くなっても全体を送り直さない"""
    path = os.path.join(DATA, "transcript-20261002.txt")
    _write(path, "".join(L[:5]))
    rec = _Rec(path)
    new = "[2026-10-04 10:09:00] [自分] 新しい\n"
    out = _run_watch(rec, lambda: (_delete(rec, path, L[:4]), _append(path, new)))
    check("縮む削除: 新しい行を流す", "新しい" in out, repr(out))
    check("縮む削除: 既存行を送り直さない", "発言その" not in out, repr(out))


def test_watch_after_small_delete_no_partial() -> None:
    """消した分が小さく、読み位置がずれた中身を指しても断片を送らない"""
    path = os.path.join(DATA, "transcript-20261003.txt")
    _write(path, "".join(L[:5]))
    rec = _Rec(path)
    new = "[2026-10-04 10:09:00] [自分] 新しい長めの発言がここに入ります\n"
    out = _run_watch(rec, lambda: (_delete(rec, path, [L[0]]), _append(path, new)))
    body = out.split("\n", 1)[1].rsplit("</transcript>", 1)[0] if "<transcript" in out else out
    check("小さい削除: ちょうど新しい行だけを流す", body == new, repr(out))


def _translate_env(name: str, lines: list[str], done: int) -> tuple[_Rec, str, str]:
    path = os.path.join(DATA, name)
    _write(path, "".join(lines))
    _write(path + ".translate_offset", str(done))
    lang = load_config().get("translate_language", "ja")
    tr_path = os.path.join(DATA, TranscriptName.parse(name).translation_filename(lang))
    _write(tr_path, "訳0\n")
    return _Rec(path), path, tr_path


def _with_fake_llm(fake: callable, rec: _Rec, path: str) -> None:
    real = subprocess.run
    subprocess.run = fake
    try:
        rec._translate_loop(path, threading.Event())
    finally:
        subprocess.run = real


def test_translate_commit_remaps_offset() -> None:
    rec, path, tr_path = _translate_env("transcript-20261005.txt", L[:3], _b(L[0]))
    seen: list[str] = []

    def fake(cmd: list[str], **kw: object) -> types.SimpleNamespace:
        seen.append(str(kw.get("input")))
        _delete(rec, path, [L[0]])          # LLM 待ちの間にダッシュボードが翻訳済みの行を消す
        return types.SimpleNamespace(returncode=0, stdout="訳1\n訳2\n", stderr="")

    _with_fake_llm(fake, rec, path)
    check("翻訳はスナップショットした未翻訳分を渡す", seen == [L[1] + L[2]], repr(seen))
    check("offset は書き換え後の座標で書く", _read(path + ".translate_offset") == str(_b(L[1] + L[2])),
          _read(path + ".translate_offset"))
    check("翻訳は 1 回だけ追記", _read(tr_path) == "訳0\n訳1\n訳2\n", repr(_read(tr_path)))


def _check_translate_discards(name: str, label: str, disrupt: callable) -> None:
    """LLM 待ちの間に disrupt(rec, path) で写せない書き直しが起きたら、結果を捨てて取り直す"""
    rec, path, tr_path = _translate_env(name, L[:3], _b(L[0]))
    calls: list[str] = []

    def fake(cmd: list[str], **kw: object) -> types.SimpleNamespace:
        calls.append(str(kw.get("input")))
        if len(calls) == 1:
            disrupt(rec, path)
            return types.SimpleNamespace(returncode=0, stdout="捨てる訳\n", stderr="")
        return types.SimpleNamespace(returncode=0, stdout="訳1\n訳2\n", stderr="")

    _with_fake_llm(fake, rec, path)
    check(f"{label}: 結果は捨てて取り直す", len(calls) == 2 and "捨てる訳" not in _read(tr_path),
          repr((calls, _read(tr_path))))
    check(f"{label}: 取り直した結果で offset を進める",
          _read(path + ".translate_offset") == str(_b("".join(L[:3]))))


def _overflow(rec: _Rec, path: str) -> None:
    for _ in range(REWRITE_HISTORY + 1):   # 追いきれないほど書き換えが重なった
        rec.rewrite_journal.record_rewrite(path, TranscriptRewrite.removing([], []))


def test_translate_discards_when_history_overflows() -> None:
    _check_translate_discards("transcript-20261006.txt", "履歴あふれ", _overflow)


def test_translate_discards_after_invalidate() -> None:
    _check_translate_discards("transcript-20261008.txt", "invalidate",
                              lambda rec, path: rec.rewrite_journal.invalidate(path))


def test_merge_to_daily_records_invalidate() -> None:
    """録音先の日次ファイルへ会議をマージしても、監視ストリームは会議を送り直さない"""
    daily = os.path.join(DATA, "transcript-20261009.txt")
    mtg = os.path.join(DATA, "transcript-202610090900@acme.txt")
    _write(daily, "[2026-10-09 08:00:00] [自分] 朝の行\n[2026-10-09 10:00:00] [自分] 後の行\n")
    _write(mtg, "--- 会議開始 ---\n[2026-10-09 09:00:00] [相手] 会議の発言です\n--- 会議終了 ---\n")
    rec = _Rec(daily)
    h = _Handler(rec, query="interval=1")
    th = threading.Thread(target=h._serve_watch, daemon=True)
    th.start()
    time.sleep(0.3)
    m = _Handler(rec, {"file": os.path.basename(mtg)})
    m._merge_meeting_to_daily()
    check("マージは成功", m.sent.get("status") == "ok", repr(m.sent))
    check("マージは書き換えを無効化として記録する", rec.rewrite_journal.generation(daily) == 1)
    time.sleep(1.0)
    _append(daily, "[2026-10-09 10:05:00] [自分] マージ後の発言\n")
    time.sleep(1.2)
    rec.stop_event.set()
    th.join(timeout=3)
    out = h.wfile.getvalue().decode()
    check("マージ後: 新しい行を流す", "マージ後の発言" in out, repr(out))
    check("マージ後: 会議や既存の行を送り直さない",
          "会議の発言" not in out and "後の行" not in out and "朝の行" not in out, repr(out))


def main() -> int:
    test_delete_records_rewrite_and_remaps_offset()
    test_extract_meeting_records_rewrite()
    test_watch_after_shrinking_delete_no_resend()
    test_watch_after_small_delete_no_partial()
    test_translate_commit_remaps_offset()
    test_translate_discards_when_history_overflows()
    test_translate_discards_after_invalidate()
    test_merge_to_daily_records_invalidate()
    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
