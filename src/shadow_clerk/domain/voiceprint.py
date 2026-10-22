"""shadow-clerk domain: 声紋（話者の埋め込み）と人名のバリューオブジェクト"""
from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from enum import Enum

import numpy as np

from shadow_clerk.domain.speaker import Speaker

_MAX_NAME_LEN = 50


def encode_embedding(embedding: np.ndarray) -> str:
    """埋め込みを float16 の base64 文字列にする（1本 約 700 バイト）"""
    return base64.b64encode(np.asarray(embedding, dtype=np.float16).tobytes()).decode("ascii")


def decode_embedding(text: str) -> np.ndarray:
    """encode_embedding の逆。L2 正規化した float32 を返す。壊れていれば ValueError"""
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, TypeError) as e:
        raise ValueError(f"埋め込みを復号できない: {e}") from e
    if not raw or len(raw) % 2:
        raise ValueError("埋め込みの長さが不正")
    v = np.frombuffer(raw, dtype=np.float16).astype(np.float32)
    norm = float(np.linalg.norm(v))
    if not np.isfinite(norm) or norm < 1e-8:
        raise ValueError("埋め込みがゼロまたは非有限")
    return v / norm


@dataclass(frozen=True)
class PersonName:
    """名前付けで付ける人の名前。transcript の話者ラベルとしてそのまま書かれる。

    `相手` で始まる名前は未命名の会議内ラベルと区別できなくなり、
    `自分` / `Claude` は既存の Speaker と衝突するので受け付けない。
    """

    value: str

    def __post_init__(self) -> None:
        v = self.value.strip() if isinstance(self.value, str) else ""
        if not v:
            raise ValueError("名前が空")
        if len(v) > _MAX_NAME_LEN:
            raise ValueError("名前が長すぎる")
        if "[" in v or "]" in v or any(ord(c) < 32 for c in v):
            raise ValueError("名前に使えない文字がある")
        if v in {s.value for s in Speaker} or v.startswith(Speaker.OTHER.value):
            raise ValueError("既存の話者ラベルと紛らわしい名前")
        object.__setattr__(self, "value", v)


TENTATIVE_MARK = "?"  # 声紋の照合で自信が足りない名前に付ける印（「alice?」）。名前として断定しない


def tentative_name(label: str) -> str | None:
    """「alice?」形式の未確定ラベルなら alice。相手? のような未命名ラベルや名前として不正なものは None"""
    if not label.endswith(TENTATIVE_MARK):
        return None
    try:
        return PersonName(label[:-len(TENTATIVE_MARK)]).value
    except ValueError:
        return None


class SampleStatus(str, Enum):
    NORMAL = "normal"
    OUTLIER = "outlier"
    KEPT = "kept"  # 人が「戻す」した。自動判定で除外しない


@dataclass(frozen=True, eq=False)
class VoiceSample:
    """声紋ストアに保存する1発話分の埋め込み"""

    embedding: np.ndarray
    recorded_at: str
    source: str
    status: SampleStatus = SampleStatus.NORMAL

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.recorded_at)

    def to_dict(self) -> dict[str, str]:
        d = {"emb": encode_embedding(self.embedding), "recorded_at": self.recorded_at,
             "source": self.source}
        if self.status is not SampleStatus.NORMAL:
            d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> VoiceSample:
        try:
            status = SampleStatus(d.get("status", SampleStatus.NORMAL.value))
        except ValueError:  # 未知の status 1件でストア全体を読めなくしない
            status = SampleStatus.NORMAL
        return cls(decode_embedding(d["emb"]), str(d.get("recorded_at", "")), str(d.get("source", "")), status)


@dataclass(frozen=True, eq=False)
class VoiceEntry:
    """voices サイドカーの1行: transcript に書いたラベルと、その発話の埋め込み・発話秒数。

    cluster は話者分離が付けた会議内ラベル（相手A 等）、auto は声紋照合で名前を付けたとき true
    """

    timestamp: str
    label: str
    embedding: np.ndarray
    duration: float | None = None
    no_enroll: bool = False
    cluster: str | None = None
    auto: bool = False

    def to_json_line(self) -> str:
        d: dict = {"ts": self.timestamp, "label": self.label, "emb": encode_embedding(self.embedding)}
        if self.duration is not None:
            d["dur"] = round(self.duration, 2)
        if self.no_enroll:
            d["noenroll"] = True
        if self.cluster is not None:
            d["cluster"] = self.cluster
        if self.auto:
            d["auto"] = True
        return json.dumps(d, ensure_ascii=False) + "\n"

    @classmethod
    def parse(cls, line: str) -> VoiceEntry | None:
        """1行をパースする。書きかけ・壊れた行は None"""
        try:
            d = json.loads(line)
            dur, cluster = d.get("dur"), d.get("cluster")
            return cls(str(d["ts"]), str(d["label"]), decode_embedding(d["emb"]),
                       None if dur is None else float(dur), d.get("noenroll") is True,
                       cluster if isinstance(cluster, str) else None, d.get("auto") is True)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
            return None
