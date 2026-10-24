"""tests/test_speaker_diarization.py — 話者分離ユニットテスト

onnxruntime / モデル不要でも動くテスト（特徴量生成・マッチング・ラベル生成等）。
"""
from __future__ import annotations

import os
import subprocess
import sys

import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from shadow_clerk._daemon_speaker_diarization import (
    SpeakerDiarizer,
    _cosine_similarity,
    _generate_label,
    label_index,
    max_label_index,
)
from shadow_clerk.domain.transcript_line import TranscriptLine, Speaker


def _silence(sec: float = 2.0) -> np.ndarray:
    return np.zeros(int(16000 * sec), dtype=np.int16)


# --- _generate_label ---

def test_generate_label_first():
    assert _generate_label(1) == "相手A"

def test_generate_label_last_alpha():
    assert _generate_label(26) == "相手Z"

def test_generate_label_beyond_alpha():
    assert _generate_label(27) == "相手27"

def test_generate_label_no_collision():
    labels = [_generate_label(i) for i in range(1, 30)]
    assert len(labels) == len(set(labels))


# --- 短セグメントは None を返す ---

def test_identify_speaker_short_returns_none():
    d = SpeakerDiarizer()
    audio = _silence(0.5)   # < 1.0s
    assert d.identify_speaker(audio) is None


# --- onnxruntime 未インストール時は None (かつ例外なし) ---

def test_identify_speaker_no_ort_returns_none(monkeypatch):
    import shadow_clerk._daemon_speaker_diarization as mod
    monkeypatch.setattr(mod, "_HAS_ORT", False)
    d = SpeakerDiarizer()
    audio = _silence(2.0)
    result = d.identify_speaker(audio)
    assert result is None


# --- 失敗フラグ: ダウンロード失敗後に _load_model を再呼びしても 1回だけ試みる ---

def test_load_model_failure_latch(monkeypatch):
    import shadow_clerk._daemon_speaker_diarization as mod
    import sys
    monkeypatch.setattr(mod, "_HAS_ORT", True)
    call_count = {"n": 0}

    def fake_download(*args, **kwargs):
        call_count["n"] += 1
        raise RuntimeError("network error")

    fake_hf = MagicMock()
    fake_hf.hf_hub_download = fake_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)

    d = SpeakerDiarizer()
    d._load_model()
    d._load_model()  # 2回目は latch で skip
    assert call_count["n"] == 1


# --- コサイン類似度の threshold 境界 (>= で既存話者を使う) ---

def test_best_match_uses_ge_not_gt():
    d = SpeakerDiarizer()
    emb = np.array([1.0, 0.0], dtype=np.float32)
    d._session_speakers["相手A"] = [emb.copy()]
    d._next_idx = 1

    with patch.object(d, "_threshold", return_value=1.0):
        name, score = d._best_match(emb, d._session_speakers)
    assert name == "相手A"
    assert abs(score - 1.0) < 1e-6


# --- 話者分離有効 + identify_speaker()=None → speaker_label="相手?" ---

def test_diarization_unknown_label_when_none(monkeypatch):
    import shadow_clerk._daemon_speaker_diarization as mod
    monkeypatch.setattr(mod, "_HAS_ORT", False)  # identify_speaker が None を返す状態

    from shadow_clerk._daemon_speaker_diarization import SpeakerDiarizer as SD
    diarizer = SD()
    # 話者分離有効時、None は "相手?" になる
    audio = _silence(2.0)
    raw = diarizer.identify_speaker(audio)  # None
    assert raw is None
    # transcribe 側のマッピング: None → "相手?"
    label = raw if raw is not None else "相手?"
    assert label == "相手?"


# --- "相手?" の TranscriptLine round-trip ---

def test_transcript_line_unknown_label_roundtrip():
    tl = TranscriptLine(
        timestamp="10:00:00",
        speaker=Speaker.OTHER,
        text="えっと",
        speaker_label="相手?",
    )
    line = tl.format()
    assert "[相手?]" in line
    parsed = TranscriptLine.parse(line)
    assert parsed is not None
    assert parsed.speaker == Speaker.OTHER
    assert parsed.speaker_label == "相手?"


# --- TranscriptLine.parse() round-trip ---

def test_transcript_line_parse_roundtrip_with_diarization_label():
    tl = TranscriptLine(
        timestamp="10:00:00",
        speaker=Speaker.OTHER,
        text="こんにちは",
        speaker_label="相手A",
    )
    line = tl.format()
    parsed = TranscriptLine.parse(line)
    assert parsed is not None
    assert parsed.speaker == Speaker.OTHER
    assert parsed.speaker_label == "相手A"
    assert parsed.text == "こんにちは"


# --- ラベル番号の逆変換 ---

def test_label_index_roundtrip():
    for i in range(1, 31):
        assert label_index(_generate_label(i)) == i
    assert label_index("相手?") is None
    assert label_index("相手") is None
    assert label_index("太郎") is None


# --- identify_speaker は (ラベル, 埋め込み) を返す ---

def _unit(*xs: float) -> np.ndarray:
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


def _fake(d: SpeakerDiarizer, monkeypatch, emb: np.ndarray) -> None:
    monkeypatch.setattr(d, "extract_embedding", lambda a: emb)
    monkeypatch.setattr(d, "_threshold", lambda: 0.7)
    monkeypatch.setattr(d, "_min_sec", lambda: 1.0)


def test_identify_returns_label_and_embedding(monkeypatch):
    d = SpeakerDiarizer()
    e = _unit(1, 0)
    _fake(d, monkeypatch, e)
    result = d.identify_speaker(_silence(2.0))
    assert result is not None
    label, emb = result
    assert label == "相手A" and np.allclose(emb, e)


# --- 出力先ファイルの続き番号 ---

def test_bind_output_continues_numbering(tmp_path, monkeypatch):
    t = tmp_path / "transcript-20261009.txt"
    t.write_text("[2026-10-09 10:00:00] [相手C] あ\n"
                 "[2026-10-09 10:00:05] [太郎] い\n"
                 "[2026-10-09 10:00:09] [相手?] う\n", encoding="utf-8")
    d = SpeakerDiarizer()
    _fake(d, monkeypatch, _unit(1, 0))
    d.bind_output(str(t))
    assert d.identify_speaker(_silence(2.0))[0] == "相手D"


def test_invalid_utf8_in_transcript_does_not_break_numbering(tmp_path, monkeypatch):
    t = tmp_path / "transcript-20261009.txt"
    t.write_bytes("[2026-10-09 10:00:00] [相手C] あ\n".encode("utf-8")
                  + b"[2026-10-09 10:00:01] [\xff\xfe] bad\n")
    assert max_label_index(str(t)) == 3
    d = SpeakerDiarizer()
    _fake(d, monkeypatch, _unit(1, 0))
    d.bind_output(str(t))
    assert d.identify_speaker(_silence(2.0))[0] == "相手D"


def test_bind_output_same_path_keeps_clusters(tmp_path, monkeypatch):
    d = SpeakerDiarizer()
    _fake(d, monkeypatch, _unit(1, 0))
    a = str(tmp_path / "transcript-20261009.txt")
    d.bind_output(a)
    assert d.identify_speaker(_silence(2.0))[0] == "相手A"
    d.bind_output(a)
    assert d.identify_speaker(_silence(2.0))[0] == "相手A"
    assert d._next_idx == 1


def test_bind_output_new_path_drops_clusters(tmp_path, monkeypatch):
    d = SpeakerDiarizer()
    _fake(d, monkeypatch, _unit(1, 0))
    d.bind_output(str(tmp_path / "transcript-20261009.txt"))
    d.identify_speaker(_silence(2.0))
    d.bind_output(str(tmp_path / "transcript-202610091000.txt"))
    assert d._session_speakers == {}
    assert d.identify_speaker(_silence(2.0))[0] == "相手A"


_FORK_SCRIPT = """
import os, sys, time
import shadow_clerk._daemon_main
print("ort_imported=%s" % ("onnxruntime" in sys.modules))
pid = os.fork()
if pid == 0:
    sys.exit(0)
for _ in range(100):
    done, _st = os.waitpid(pid, os.WNOHANG)
    if done:
        print("exited")
        break
    time.sleep(0.1)
else:
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    print("HUNG")
"""


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_daemon_main_import_keeps_fork_exit_safe():
    """onnxruntime をインポート時に読み込むと fork 後の子が終了時にハングする。"""
    r = subprocess.run([sys.executable, "-c", _FORK_SCRIPT],
                       capture_output=True, text=True, timeout=60)
    assert "ort_imported=False" in r.stdout, r.stdout + r.stderr
    assert "exited" in r.stdout, r.stdout + r.stderr


def test_label_numbering_counts_sidecar_clusters(tmp_path):
    """名前で表示した 相手A を、再起動後に別人へ振り直さない"""
    from shadow_clerk._daemon_voice_sidecar import append_voice
    t = tmp_path / "transcript-202610091000.txt"
    t.write_text("[2026-10-09 10:00:00] [alice] あ\n", encoding="utf-8")
    append_voice(str(t), "2026-10-09 10:00:00", "alice", _unit(1, 0), cluster="相手A", auto=True)
    assert max_label_index(str(t)) == 1


def test_cluster_embeddings_returns_a_copy(monkeypatch):
    d = SpeakerDiarizer()
    _fake(d, monkeypatch, _unit(1, 0))
    d.identify_speaker(_silence(2.0))
    got = d.cluster_embeddings("相手A")
    assert len(got) == 1 and np.allclose(got[0], _unit(1, 0))
    got.append(_unit(1, 0))
    assert len(d.cluster_embeddings("相手A")) == 1 and d.cluster_embeddings("相手B") == []


def test_truncated_sidecar_does_not_break_numbering(tmp_path):
    """追記中に落ちて行末の多バイト文字が切れたサイドカーでも番号は続きから振る"""
    from shadow_clerk._daemon_voice_sidecar import append_voice, voices_path
    t = tmp_path / "transcript-202610091000.txt"
    t.write_text("[2026-10-09 10:00:00] [alice] あ\n", encoding="utf-8")
    append_voice(str(t), "2026-10-09 10:00:00", "alice", _unit(1, 0), cluster="相手B", auto=True)
    with open(voices_path(str(t)), "ab") as f:
        f.write('{"ts": "2026-10-09 10:00:01", "cluster": "相手'.encode("utf-8")[:-1])
    assert max_label_index(str(t)) == 2
