"""ASR モデル共有キャッシュの検証

実行: uv run python tests/test_model_sharing.py

実モデル不要。reazonspeech / sherpa_onnx / faster_whisper を偽モジュールに
差し替え、Transcriber がどのキーで共有し・どこで共有しないかを検査する。

背景: main (_daemon_recorder_capture) と interim (_daemon_recorder_transcribe) が
同一の ReazonSpeech K2 (fp32 重み ~750MB) を二重にロードしていた。並行デコードの
安全性は tests/ 外の実測で確認済み (create_stream() が呼び出しごとの状態を持ち、
8 スレッド x 60 回の並行デコードが単独デコードとバイト一致)。
"""
from __future__ import annotations
import os
import sys
import types
from typing import Any
from unittest.mock import patch

import numpy as np

# --- 偽モジュールの登録 (shadow_clerk の import より前に行う) ---
_FAKE_SO_LIB = "/nonexistent-sherpa/lib"
os.environ["LD_LIBRARY_PATH"] = _FAKE_SO_LIB + ":" + os.environ.get("LD_LIBRARY_PATH", "")

_sherpa = types.ModuleType("sherpa_onnx")
_sherpa.__file__ = "/nonexistent-sherpa/__init__.py"
sys.modules["sherpa_onnx"] = _sherpa


class FakeK2Model:
    """K2 モデルの代役。生成時の (device, precision) を保持する"""

    def __init__(self, device: str, precision: str) -> None:
        self.device = device
        self.precision = precision

    def __repr__(self) -> str:
        return f"FakeK2Model({self.device},{self.precision})"


k2_load_calls: list[tuple[str, str]] = []


def _fake_k2_load_model(device: str = "cpu", precision: str = "fp32") -> FakeK2Model:
    k2_load_calls.append((device, precision))
    return FakeK2Model(device, precision)


class _FakeAudio:
    def __init__(self, wave: np.ndarray) -> None:
        self.waveform = wave


def _fake_audio_from_numpy(wave: np.ndarray, sr: int) -> _FakeAudio:
    return _FakeAudio(wave)


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.text = text


def _fake_k2_transcribe(model: Any, audio: _FakeAudio) -> _FakeResult:
    # どのモデルインスタンスでデコードされたかをテキストに埋めて追跡できるようにする
    return _FakeResult(f"decoded-by-{model!r}")


_rs = types.ModuleType("reazonspeech")
_rs_k2 = types.ModuleType("reazonspeech.k2")
_rs_asr = types.ModuleType("reazonspeech.k2.asr")
_rs_asr.load_model = _fake_k2_load_model  # type: ignore[attr-defined]
_rs_asr.transcribe = _fake_k2_transcribe  # type: ignore[attr-defined]
_rs_asr.audio_from_numpy = _fake_audio_from_numpy  # type: ignore[attr-defined]
_rs_k2.asr = _rs_asr  # type: ignore[attr-defined]
_rs.k2 = _rs_k2  # type: ignore[attr-defined]
sys.modules["reazonspeech"] = _rs
sys.modules["reazonspeech.k2"] = _rs_k2
sys.modules["reazonspeech.k2.asr"] = _rs_asr

whisper_load_calls: list[tuple[str, str, str]] = []


class FakeWhisperModel:
    def __init__(self, model_id: str, device: str = "cpu", compute_type: str = "int8") -> None:
        whisper_load_calls.append((model_id, device, compute_type))
        self.model_id = model_id


_fw = types.ModuleType("faster_whisper")
_fw.WhisperModel = FakeWhisperModel  # type: ignore[attr-defined]
sys.modules["faster_whisper"] = _fw

from shadow_clerk import _daemon_transcriber as tr  # noqa: E402  pylint: disable=wrong-import-position

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


def reset() -> None:
    tr._MODEL_CACHE.clear()
    k2_load_calls.clear()
    whisper_load_calls.clear()


def make(label: str, key: str, device: str = "cpu") -> tr.Transcriber:
    return tr.Transcriber(model_size="tiny", language="ja", device=device,
                          ja_asr_config_key=key, label=label)


K2_CFG = {"japanese_asr_model": "reazonspeech-k2",
          "interim_japanese_asr_model": "reazonspeech-k2",
          "reazonspeech_precision": "fp32"}


# --- 1. 同一設定なら 1 個だけロードして共有する ---
reset()
with patch.object(tr, "load_config", return_value=K2_CFG):
    main = make("main", "japanese_asr_model")
    interim = make("interim", "interim_japanese_asr_model")
    main.load_model()
    interim.load_model()
check("1. 同一設定の 2 つの Transcriber が同じモデルオブジェクトを共有する",
      main.model is interim.model, f"{main.model!r} / {interim.model!r}")
check("2. モデルのロードは 1 回しか起きない", len(k2_load_calls) == 1, f"{k2_load_calls}")
check("3. キャッシュは 1 エントリ・参照数 2",
      len(tr._MODEL_CACHE) == 1 and list(tr._MODEL_CACHE.values())[0][1] == 2,
      f"{tr._MODEL_CACHE}")
check("4. 共有キーは backend/model_id/device/precision を含む",
      main._shared_key == ("reazonspeech-k2", "reazonspeech-k2", "cpu", "fp32"),
      f"{main._shared_key}")

# 共有していても両者が正しくデコードできる
audio = np.zeros(16000, dtype=np.int16)
check("5. 共有モデルで両方とも文字起こしできる",
      main.transcribe(audio) == interim.transcribe(audio) != "",
      f"{main.transcribe(audio)!r}")

# --- 2. device が違えば共有しない ---
reset()
with patch.object(tr, "load_config", return_value=K2_CFG):
    a = make("main", "japanese_asr_model", device="cpu")
    b = make("interim", "interim_japanese_asr_model", device="cuda")
    a.load_model()
    b.load_model()
check("6. device が異なれば別インスタンスをロードする",
      a.model is not b.model and len(k2_load_calls) == 2, f"{k2_load_calls}")

# --- 3. precision が違えば共有しない ---
reset()
with patch.object(tr, "load_config", return_value=dict(K2_CFG, reazonspeech_precision="fp32")):
    a = make("main", "japanese_asr_model")
    a.load_model()
with patch.object(tr, "load_config", return_value=dict(K2_CFG, reazonspeech_precision="int8")):
    b = make("interim", "interim_japanese_asr_model")
    b.load_model()
check("7. precision が異なれば別インスタンスをロードする",
      a.model is not b.model and len(k2_load_calls) == 2, f"{k2_load_calls}")
check("8. precision 違いはキャッシュ上も別エントリ", len(tr._MODEL_CACHE) == 2,
      f"{list(tr._MODEL_CACHE)}")

# --- 4. main と interim を別モデルに設定できる (共有が設定を上書きしない) ---
reset()
mixed = {"japanese_asr_model": "reazonspeech-k2",
         "interim_japanese_asr_model": "kotoba-whisper",
         "kotoba_whisper_model": "kotoba-tech/kotoba-whisper-v2.0-faster",
         "reazonspeech_precision": "fp32"}
with patch.object(tr, "load_config", return_value=mixed):
    main = make("main", "japanese_asr_model")
    interim = make("interim", "interim_japanese_asr_model")
    main.load_model()
    interim.load_model()
check("9. main=K2 / interim=kotoba-whisper の設定が共有で潰されない",
      main._backend == "reazonspeech-k2" and interim._backend == "whisper",
      f"{main._backend} / {interim._backend}")
check("10. それぞれのバックエンドが 1 回ずつロードされる",
      len(k2_load_calls) == 1 and len(whisper_load_calls) == 1,
      f"k2={k2_load_calls} whisper={whisper_load_calls}")
check("11. Whisper はキャッシュに載せない (共有安全性を未検証のため)",
      len(tr._MODEL_CACHE) == 1 and interim._shared_key is None,
      f"{list(tr._MODEL_CACHE)} interim_key={interim._shared_key}")

# --- 5. 実行時のモデル切り替えが相手を壊さない ---
# reload_model() は音声コマンドから main にだけ掛かる。interim が同じ K2 を
# 借りたままでも、モデルオブジェクトを引き抜かれてはならない。
reset()
cfg: dict[str, Any] = dict(K2_CFG)
with patch.object(tr, "load_config", side_effect=lambda: cfg):
    main = make("main", "japanese_asr_model")
    interim = make("interim", "interim_japanese_asr_model")
    main.load_model()
    interim.load_model()
    shared_before = interim.model
    entry_before = tr._MODEL_CACHE[("reazonspeech-k2", "reazonspeech-k2", "cpu", "fp32")]
    # main だけ Whisper に切り替える
    cfg["japanese_asr_model"] = "default"
    main.reload_model("small")
    after_main_switch = dict(tr._MODEL_CACHE)
    check("12. main の切り替え後も interim のモデルオブジェクトは同一",
          interim.model is shared_before, f"{interim.model!r}")
    check("13. main は Whisper に切り替わっている",
          main._backend == "whisper" and isinstance(main.model, FakeWhisperModel),
          f"{main._backend} {main.model!r}")
    check("14. main は共有参照を返しており参照数は 1 に減る",
          main._shared_key is None and entry_before[1] == 1, f"refs={entry_before[1]}")
    check("15. interim がまだ借りているのでエントリは残る",
          len(after_main_switch) == 1, f"{list(after_main_switch)}")
    check("16. 切り替え後も interim は文字起こしできる",
          interim.transcribe(audio) == f"decoded-by-{shared_before!r}",
          f"{interim.transcribe(audio)!r}")
    # interim も手放したらキャッシュから消える (750MB を抱え続けない)
    interim.release()
    check("17. 最後の利用者が release すればキャッシュから外れる",
          len(tr._MODEL_CACHE) == 0, f"{list(tr._MODEL_CACHE)}")
    # 再度必要になれば読み直せる
    k2_load_calls.clear()
    interim2 = make("interim", "interim_japanese_asr_model")
    interim2.load_model()
    check("18. 解放後に再取得すると新しくロードされる",
          len(k2_load_calls) == 1 and isinstance(interim2.model, FakeK2Model),
          f"{k2_load_calls}")

# --- 6. interim 側のモデル差し替えで参照が漏れない ---
# _interim_transcribe_thread は設定変更時に Transcriber を作り直すため、
# 旧インスタンスの参照を返さないとエントリが永久に残る。
reset()
with patch.object(tr, "load_config", return_value=K2_CFG):
    main = make("main", "japanese_asr_model")
    main.load_model()
    old = make("interim", "interim_japanese_asr_model")
    old.load_model()
    refs_with_two = list(tr._MODEL_CACHE.values())[0][1]
    old.release()
    refs_after_release = list(tr._MODEL_CACHE.values())[0][1]
    new = make("interim", "interim_japanese_asr_model")
    new.load_model()
    refs_after_new = list(tr._MODEL_CACHE.values())[0][1]
check("19. interim の作り直しで参照数が増え続けない",
      (refs_with_two, refs_after_release, refs_after_new) == (2, 1, 2),
      f"{(refs_with_two, refs_after_release, refs_after_new)}")
check("20. 作り直した interim も main と同じモデルを共有する",
      new.model is main.model, f"{new.model!r} / {main.model!r}")

print(f"\n=== {sum(results)}/{len(results)} PASS ===")
raise SystemExit(0 if all(results) else 1)
