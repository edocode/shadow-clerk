"""Shadow-clerk daemon: 話者分離 (Speaker Diarization)

wespeaker ONNX (ResNet34, VoxCeleb) による話者埋め込み抽出・マッチング。
onnxruntime がインストールされていない場合は無効化され、None を返す。
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from typing import Any

import numpy as np

from shadow_clerk import DATA_DIR
from shadow_clerk._daemon_config import load_config
from shadow_clerk.domain.transcript_line import TranscriptLine

logger = logging.getLogger("shadow-clerk")

_WESPEAKER_REPO = "wespeaker/wespeaker-voxceleb-resnet34-LM"
_ONNX_FILENAME = "voxceleb_resnet34_LM.onnx"
_CACHE_DIR = os.path.join(DATA_DIR, "wespeaker_cache")
_SIMILARITY_THRESHOLD_DEFAULT = 0.70
_MIN_SEGMENT_SEC = 1.0
_MAX_EMBEDDINGS_PER_SPEAKER = 20
_SAMPLE_RATE = 16000

try:
    import onnxruntime as _ort
    _HAS_ORT = True
except ImportError:
    _HAS_ORT = False

try:
    import kaldi_native_fbank as _knf
    _HAS_KNF = True
except ImportError:
    _HAS_KNF = False


def _make_knf_opts(num_mel_bins: int = 80) -> Any:
    opts = _knf.FbankOptions()
    opts.frame_opts.dither = 0.0
    opts.frame_opts.window_type = "hamming"
    opts.frame_opts.remove_dc_offset = False
    opts.frame_opts.frame_shift_ms = 10.0
    opts.frame_opts.frame_length_ms = 25.0
    opts.mel_opts.num_bins = num_mel_bins
    opts.mel_opts.low_freq = 20.0
    opts.mel_opts.high_freq = -400.0
    return opts


def _extract_fbank(audio: np.ndarray, num_mel_bins: int = 80) -> np.ndarray:
    """80次元 Kaldi 互換 log-mel filterbank。入力は int16 スケール float32、16kHz。

    kaldi_native_fbank が利用可能な場合は wespeaker のトレーニングと同一の
    前処理を使う。未インストール時は numpy フォールバック（精度が落ちる）。
    """
    if _HAS_KNF:
        online_fbank = _knf.OnlineFbank(_make_knf_opts(num_mel_bins))
        online_fbank.accept_waveform(_SAMPLE_RATE, audio.tolist())
        online_fbank.input_finished()
        frames = [online_fbank.get_frame(i) for i in range(online_fbank.num_frames_ready)]
        fbank = np.array(frames, dtype=np.float32)
        return fbank - fbank.mean(axis=0, keepdims=True)  # CMN（wespeaker と同じ）

    # --- numpy フォールバック ---
    sr = _SAMPLE_RATE
    frame_len = int(sr * 0.025)
    frame_hop = int(sr * 0.010)
    n_fft = 512
    audio = np.concatenate([[audio[0]], audio[1:] - 0.97 * audio[:-1]])
    num_frames = max(1, 1 + (len(audio) - frame_len) // frame_hop)
    idx = np.arange(frame_len)[None, :] + frame_hop * np.arange(num_frames)[:, None]
    idx = np.clip(idx, 0, len(audio) - 1)
    frames = audio[idx] * np.hamming(frame_len)
    power = np.abs(np.fft.rfft(frames, n=n_fft)) ** 2
    fmin, fmax = 20.0, sr / 2.0
    mel_min = 2595.0 * np.log10(1.0 + fmin / 700.0)
    mel_max = 2595.0 * np.log10(1.0 + fmax / 700.0)
    mel_pts = np.linspace(mel_min, mel_max, num_mel_bins + 2)
    hz_pts = 700.0 * (10.0 ** (mel_pts / 2595.0) - 1.0)
    bins = np.clip(np.floor((n_fft + 1) * hz_pts / sr).astype(int), 0, n_fft // 2)
    fbank = np.zeros((num_frames, num_mel_bins), dtype=np.float32)
    for m in range(1, num_mel_bins + 1):
        lo, mid, hi = bins[m - 1], bins[m], bins[m + 1]
        up = np.arange(lo, mid)
        dn = np.arange(mid, hi)
        if len(up):
            fbank[:, m - 1] += power[:, up] @ ((up - lo) / max(mid - lo, 1)).astype(np.float32)
        if len(dn):
            fbank[:, m - 1] += power[:, dn] @ ((hi - dn) / max(hi - mid, 1)).astype(np.float32)
    fbank = np.log(np.maximum(fbank, 1e-10))
    fbank -= fbank.mean(axis=0, keepdims=True)
    return fbank


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """コサイン類似度。"""
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-8 or nb < 1e-8:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _generate_label(idx: int) -> str:
    """話者インデックスからラベルを生成: 相手A, 相手B, ..., 相手Z, 相手27, ..."""
    if idx <= 26:
        return f"相手{chr(64 + idx)}"
    return f"相手{idx}"


_LABEL_RE = re.compile(r"^相手([A-Z]|[0-9]+)$")


def label_index(label: str) -> int | None:
    """_generate_label の逆。会議内ラベルでなければ None"""
    m = _LABEL_RE.match(label)
    if not m:
        return None
    g = m.group(1)
    return ord(g) - 64 if g.isalpha() else int(g)


def max_label_index(transcript_path: str) -> int:
    """transcript に既にある会議内ラベルの最大番号。ファイルが無ければ 0"""
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return 0
    return max((i for line in lines
                if (tl := TranscriptLine.parse(line)) and tl.speaker_label
                and (i := label_index(tl.speaker_label)) is not None), default=0)


class SpeakerDiarizer:
    """wespeaker ONNX による話者分離エンジン（セッションスコープ）。

    onnxruntime が未インストールの場合は available=False となり、
    identify_speaker() は None を返す。
    """

    def __init__(self) -> None:
        self._session: Any | None = None
        self._model_lock = threading.Lock()
        self._load_failed = False
        self._session_speakers: dict[str, list[np.ndarray]] = {}
        self._next_idx = 0
        self._session_lock = threading.Lock()
        self._bound_path: str | None = None

    def _load_model(self) -> bool:
        """モデルを遅延ロード。成功したら True。失敗後はラッチして再試行しない。"""
        if self._session is not None:
            return True
        if self._load_failed:
            return False
        if not _HAS_ORT:
            logger.warning("話者分離: onnxruntime が見つかりません。"
                           "'uv sync --extra diarization' でインストールしてください")
            self._load_failed = True
            return False
        with self._model_lock:
            if self._session is not None:
                return True
            if self._load_failed:
                return False
            try:
                import huggingface_hub as hf
                onnx_path = hf.hf_hub_download(
                    _WESPEAKER_REPO, _ONNX_FILENAME, cache_dir=_CACHE_DIR)
                opts = _ort.SessionOptions()
                opts.inter_op_num_threads = 1
                opts.intra_op_num_threads = 2
                self._session = _ort.InferenceSession(
                    onnx_path, sess_options=opts,
                    providers=["CPUExecutionProvider"])
                logger.info("話者分離モデル読み込み完了: %s", onnx_path)
                return True
            except Exception as e:
                logger.error("話者分離モデル読み込みエラー: %s — 話者分離を無効化します", e)
                self._load_failed = True
                return False

    def extract_embedding(self, audio: np.ndarray) -> np.ndarray | None:
        """int16 音声セグメントから L2 正規化済み embedding を返す。失敗時は None。"""
        if not self._load_model():
            return None
        assert self._session is not None
        try:
            audio_f32 = audio.astype(np.float32)  # int16 スケール維持（wespeaker と同じ前処理）
            feats = _extract_fbank(audio_f32)      # (T, 80)
            feats = feats[np.newaxis, ...]              # (1, T, 80)
            input_name = self._session.get_inputs()[0].name
            outputs = self._session.run(None, {input_name: feats})
            emb = outputs[0].squeeze()                  # (D,)
            norm = np.linalg.norm(emb)
            return emb / norm if norm > 1e-8 else None
        except Exception as e:
            logger.debug("embedding 抽出エラー: %s", e)
            return None

    def _threshold(self) -> float:
        return float(load_config().get("diarization_threshold", _SIMILARITY_THRESHOLD_DEFAULT))

    def _best_match(self, emb: np.ndarray,
                    pool: dict[str, list[np.ndarray]]) -> tuple[str | None, float]:
        best_name: str | None = None
        best_score = -math.inf
        for name, embeddings in pool.items():
            for stored in embeddings:
                score = _cosine_similarity(emb, stored)
                if score > best_score:
                    best_score, best_name = score, name
        return best_name, best_score

    def _min_sec(self) -> float:
        return float(load_config().get("diarization_min_sec", _MIN_SEGMENT_SEC))

    def bind_output(self, transcript_path: str) -> None:
        """出力先が変わったら会議内クラスタを捨て、ラベル番号はそのファイルの続きから振る。

        名前付けはラベル単位なので、1つの transcript 内で同じラベルが別人を指してはいけない。
        デーモン再起動や会議の開始・終了で同じ日次ファイルに戻ってきても衝突しないよう、
        既存の最大番号を引き継ぐ
        """
        if transcript_path == self._bound_path:
            return
        next_idx = max_label_index(transcript_path)
        with self._session_lock:
            self._session_speakers.clear()
            self._next_idx = next_idx
            self._bound_path = transcript_path

    def identify_speaker(self, audio: np.ndarray) -> tuple[str, np.ndarray] | None:
        """音声セグメントから (会議内ラベル, 埋め込み) を返す。分離不能・短すぎる場合は None。"""
        duration = len(audio) / _SAMPLE_RATE
        min_sec = self._min_sec()
        if duration < min_sec:
            logger.debug("話者分離: %.2f秒 < %.1f秒、スキップ", duration, min_sec)
            return None

        emb = self.extract_embedding(audio)
        if emb is None:
            return None

        thr = self._threshold()
        with self._session_lock:
            label, score = self._best_match(emb, self._session_speakers)
            if label and score >= thr:
                pool = self._session_speakers[label]
                pool.append(emb)
                if len(pool) > _MAX_EMBEDDINGS_PER_SPEAKER:
                    self._session_speakers[label] = pool[-_MAX_EMBEDDINGS_PER_SPEAKER:]
                logger.info("話者分離: %s (類似度 %.3f, 閾値 %.2f)", label, score, thr)
                return label, emb

            self._next_idx += 1
            new_label = _generate_label(self._next_idx)
            self._session_speakers[new_label] = [emb]
        best_str = f"最高類似度 {label}:{score:.3f}" if label else "既存話者なし"
        logger.info("話者分離: 新規話者 %s (%s, 閾値 %.2f)", new_label, best_str, thr)
        return new_label, emb
