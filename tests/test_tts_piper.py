"""piper バックエンド（英語の読み上げ）の検証。piper 本体の代わりに偽のモジュールを差し込む

実行: uv run python tests/test_tts_piper.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

import numpy as np

from shadow_clerk._daemon_tts import TtsError
from shadow_clerk._daemon_tts_piper import PIPER_MODEL, PiperBackend

results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {label} {detail}")
    results.append(ok)


_SPEAKERS = {"p225": 0, "p226": 1, "p227": 2}
downloads: list[Path] = []
synth: list[int | None] = []


class _Voice:
    config = types.SimpleNamespace(speaker_id_map=_SPEAKERS, sample_rate=22050)

    @staticmethod
    def load(path: str) -> "_Voice":
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        return _Voice()

    def synthesize(self, text: str, cfg: types.SimpleNamespace):
        synth.append(cfg.speaker_id)
        yield types.SimpleNamespace(audio_float_array=np.zeros(len(text), dtype=np.float32))


def _download(voice: str, download_dir: Path) -> None:
    downloads.append(download_dir)
    (download_dir / f"{voice}.onnx").touch()


def _install_fake_piper() -> None:
    piper = types.ModuleType("piper")
    piper.PiperVoice = _Voice  # type: ignore[attr-defined]
    piper.SynthesisConfig = lambda speaker_id=None: types.SimpleNamespace(speaker_id=speaker_id)  # type: ignore[attr-defined]
    dl = types.ModuleType("piper.download_voices")
    dl.download_voice = _download  # type: ignore[attr-defined]
    sys.modules["piper"], sys.modules["piper.download_voices"] = piper, dl


def test_fixed_voice_and_download() -> None:
    with tempfile.TemporaryDirectory() as d:
        b = PiperBackend("p226", model_dir=d)
        pcm, sr = b.synthesize("Hello.")
        check("初回はモデルをダウンロードする", downloads == [Path(d)], repr(downloads))
        check("指定した話者で合成する", b.speaker_name == "p226" and synth[-1] == 1 and sr == 22050 and len(pcm) == 6,
              repr((b.speaker_name, synth, sr)))
        PiperBackend("p225", model_dir=d).synthesize("Hi.")
        check("モデルがあればダウンロードしない", len(downloads) == 1, repr(downloads))


def test_random_voice() -> None:
    with tempfile.TemporaryDirectory() as d:
        Path(d, PIPER_MODEL + ".onnx").touch()
        backends = [PiperBackend("random", model_dir=d) for _ in range(30)]
        for b in backends:
            b.synthesize("Hi.")  # 話者はモデルを読んだスレッドが決める
        names = {b.speaker_name for b in backends}
        check("random は会話ごとに話者を選ぶ", names <= set(_SPEAKERS) and len(names) > 1, repr(names))
        b = PiperBackend("p999", model_dir=d)
        b.synthesize("Hi.")
        check("無い話者ならランダムに選ぶ", b.speaker_name in _SPEAKERS, b.speaker_name)


def test_unavailable() -> None:
    sys.modules["piper.download_voices"].download_voice = lambda *_a: None  # type: ignore[attr-defined]
    with tempfile.TemporaryDirectory() as d:
        try:
            PiperBackend(model_dir=d).synthesize("Hi.")
            ok = False
        except TtsError:
            ok = True
        check("モデルを用意できなければ TtsError（再生器はブラウザに回す）", ok)


if __name__ == "__main__":
    _install_fake_piper()
    test_fixed_voice_and_download()
    test_random_voice()
    test_unavailable()
    sys.exit(0 if all(results) else 1)
