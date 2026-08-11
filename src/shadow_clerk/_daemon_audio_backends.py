"""Shadow-clerk daemon: 音声バックエンド実装 (PipeWire/PulseAudio/WASAPI)

デバイス列挙・解決は _daemon_audio.py に残し、ここには「モニターを実際に
キャプチャする」ロジックだけを置く。ファイルサイズ上限 (700 行) に近づいた
_daemon_audio.py から、device リスト分離 (_daemon_audio_devices.py) と
同じパターンで切り出した。
"""
from __future__ import annotations
import collections
import logging
import queue
import shutil
import subprocess
import sys
import threading
from typing import Any, Protocol
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import (
    SAMPLE_RATE, CHANNELS, FRAME_SIZE, IPC_TIMEOUT_SEC,
)
from shadow_clerk._daemon_audio_level import CaptureLevel

logger = logging.getLogger("shadow-clerk")


class StopSignal(Protocol):
    """停止要求の読み取りインターフェース（threading.Event が構造的に満たす）。

    バックエンドのモニターキャプチャは、デーモン全体の停止だけでなく
    monitor_device の設定変更による再起動要求でも止める必要があるため、
    複数のイベントを束ねたビューも渡せるようにしてある。
    """

    def is_set(self) -> bool:
        ...


def _wpctl_prop(stdout: str, key: str) -> str | None:
    """`wpctl inspect` の出力から `key = "value"` の値を取り出す。"""
    for raw_line in stdout.splitlines():
        line = raw_line.strip().lstrip("* ")
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip().strip('"')
    return None


def _wpctl_inspect_default_sink() -> str:
    """`wpctl inspect @DEFAULT_AUDIO_SINK@` の stdout を返す。

    get_default_sink_name (node.name を読む) と PipeWireBackend.detect_monitor_source
    (object.serial を読む) の両方が同じ呼び出しを必要とするため、subprocess 呼び出し
    自体だけをここに共通化する。TimeoutExpired/FileNotFoundError の扱いは呼び出し元
    ごとに異なるため、例外はここでは捕まえず素通しする。
    """
    return subprocess.run(
        ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
        capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC,
    ).stdout


def _capture_pcm_stream(cmd: list[str], name: str, audio_queue: queue.Queue,
                        stop_event: StopSignal,
                        level: CaptureLevel | None = None) -> None:
    """コマンドの stdout から PCM フレームを読み続けて audio_queue に流す。

    stderr は別スレッドで読み捨てつつ末尾のみ保持する。読まずに放置すると
    子プロセスが警告を大量出力した際に OS パイプバッファが充満して
    stdout への音声出力ごとブロックし、キャプチャが無音停止する。
    """
    import numpy as np
    logger.info("%s monitor capture: %s", name, " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None and proc.stderr is not None
    stderr_tail: collections.deque[bytes] = collections.deque(maxlen=50)

    def _drain() -> None:
        for line in proc.stderr:
            stderr_tail.append(line)

    drain_thread = threading.Thread(target=_drain, name=f"{cmd[0]}-stderr", daemon=True)
    drain_thread.start()
    try:
        while not stop_event.is_set():
            data = proc.stdout.read(FRAME_SIZE * 2)
            if not data:
                break
            if len(data) == FRAME_SIZE * 2:
                samples = np.frombuffer(data, dtype=np.int16)
                if level is not None:
                    level.add(samples)
                audio_queue.put(samples)
    finally:
        proc.terminate()
        proc.wait()
        drain_thread.join(timeout=2)
        err = b"".join(stderr_tail)
        if err:
            logger.warning("%s stderr: %s", cmd[0], err.decode("utf-8", errors="replace").strip())


class AudioBackend:
    """音声バックエンド基底クラス"""

    def detect_monitor_source(self) -> str | None:
        raise NotImplementedError

    def list_devices(self) -> None:
        raise NotImplementedError

    def start_monitor_capture(self, source: str, audio_queue: queue.Queue,
                              stop_event: StopSignal,
                              level: CaptureLevel | None = None) -> None:
        """モニター音声を audio_queue に流し続ける。stop_event が立つまで戻らない。

        source が何を指すかはバックエンドごとに違う（PipeWire は Sink の
        object.serial、PulseAudio はモニターソース名、WASAPI は loopback
        デバイス名の部分一致）。何を渡すかは呼び出し側が決める。level が渡されれば
        取り込んだフレームで更新する。
        """
        raise NotImplementedError


class PipeWireBackend(AudioBackend):
    """PipeWire バックエンド"""

    @staticmethod
    def is_available() -> bool:
        return shutil.which("pw-record") is not None

    def detect_monitor_source(self) -> str | None:
        """デフォルト Sink の object.serial を返す（pw-record --target 用）。

        以前はここで 1 行目の "id NN" ＝ object.id を返していたが、--target が
        数値として解釈するのは object.serial であり、両者は別番号（この機材では
        既定 Sink が id 44 / serial 64）。object.id を渡すと一致するノードが無く、
        pw-record は警告も非ゼロ終了も出さずに既定の Source ＝ マイクへ
        フォールバックする（pw-link で実測確認済み）。自動検出のフォールバック
        経路は、この取り違えのせいで常にマイクを録っていた。
        """
        if shutil.which("wpctl"):
            try:
                stdout = _wpctl_inspect_default_sink()
                if (serial := _wpctl_prop(stdout, "object.serial")):
                    logger.info("PipeWire デフォルト Sink の object.serial: %s (wpctl)", serial)
                    return serial
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        # serial が取れなかった場合は pw-record では安全に指定できないため None を
        # 返す。呼び出し側が PulseAudio バックエンドへフォールバックする。
        logger.debug("PipeWire: wpctl から object.serial を取得できませんでした。"
                     "PulseAudio にフォールバックします。")
        return None

    def list_devices(self) -> None:
        print(t("rec.pipewire_devices"))
        if shutil.which("wpctl"):
            try:
                result = subprocess.run(
                    ["wpctl", "status"],
                    capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC,
                )
                if result.stdout.strip():
                    print(result.stdout)
                else:
                    print(t("rec.no_devices"))
                return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        if shutil.which("pactl"):
            try:
                result = subprocess.run(
                    ["pactl", "list", "short", "sinks"],
                    capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC,
                )
                if result.stdout.strip():
                    print(result.stdout)
                else:
                    print(t("rec.no_devices"))
                return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        print(t("rec.pw_unavailable"))

    def start_monitor_capture(self, source: str, audio_queue: queue.Queue,
                              stop_event: StopSignal,
                              level: CaptureLevel | None = None) -> None:
        """pw-record でモニターをキャプチャ。

        source は Sink の object.serial（数値文字列）であること。ノード名を渡すと
        pw-record は Source としか照合せず、一致しないまま既定の Source ＝ マイクに
        フォールバックする（sink_serial の docstring 参照）。
        """
        cmd = [
            "pw-record", "--target", source,
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--format", "s16",
            "-",
        ]
        _capture_pcm_stream(cmd, "PipeWire", audio_queue, stop_event, level)


class PulseAudioBackend(AudioBackend):
    """PulseAudio バックエンド"""

    @staticmethod
    def is_available() -> bool:
        return shutil.which("pactl") is not None

    def detect_monitor_source(self) -> str | None:
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC,
            )
            for line in result.stdout.splitlines():
                if ".monitor" in line:
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        return parts[1]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def list_devices(self) -> None:
        print(t("rec.pulseaudio_sources"))
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC,
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print(t("rec.no_sources"))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print(t("rec.pa_unavailable"))

    def start_monitor_capture(self, source: str, audio_queue: queue.Queue,
                              stop_event: StopSignal,
                              level: CaptureLevel | None = None) -> None:
        """parec でモニターソースをキャプチャ"""
        cmd = [
            "parec",
            f"--device={source}",
            f"--rate={SAMPLE_RATE}",
            "--channels=1",
            "--format=s16le",
        ]
        _capture_pcm_stream(cmd, "PulseAudio", audio_queue, stop_event, level)


def _is_rdp_audio(name: str) -> bool:
    """RDP の virtual audio device か判定。loopback 候補から除外する。"""
    if not name:
        return False
    n = name.lower()
    return (
        "リモート オーディオ" in name      # ja (full-width space)
        or "リモート デスクトップ" in name  # ja (RDP redirected device)
        or "remote audio" in n             # en
        or "remote desktop" in n           # en
    )


class WasapiBackend(AudioBackend):
    """Windows WASAPI ループバックバックエンド (PyAudioWPatch)"""

    @staticmethod
    def is_available() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import pyaudiowpatch as pyaudio
        except ImportError as e:
            logger.warning("pyaudiowpatch のインポート失敗: %s", e)
            return False
        if not hasattr(pyaudio, "paWASAPI"):
            logger.warning("pyaudiowpatch に paWASAPI が無い")
            return False
        if not hasattr(pyaudio.PyAudio, "get_loopback_device_info_generator"):
            logger.warning("pyaudiowpatch に get_loopback_device_info_generator が無い")
            return False
        return True

    @staticmethod
    def _find_loopback_info(p: Any, prefer_name: str = "") -> dict | None:
        """RDP 以外の WASAPI loopback デバイス情報を返す。

        prefer_name が指定されていれば部分一致で優先する。
        指定がなければ既定の出力デバイスに対応する loopback を優先する。
        """
        import pyaudiowpatch as pyaudio
        try:
            host_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        except OSError:
            return None
        default_idx = host_info.get("defaultOutputDevice")
        default_name = ""
        if default_idx is not None and default_idx >= 0:
            try:
                default_name = p.get_device_info_by_index(default_idx)["name"]
            except OSError:
                pass
            if _is_rdp_audio(default_name):
                logger.info("既定の WASAPI 出力 (%s) は RDP デバイス、別を探す",
                            default_name)
                default_name = ""

        target = None
        fallback = None
        for info in p.get_loopback_device_info_generator():
            name = info["name"]
            if _is_rdp_audio(name):
                logger.debug("RDP デバイススキップ: %s", name)
                continue
            if prefer_name and prefer_name in name:
                return info
            if default_name and (default_name in name or name in default_name):
                if target is None:
                    target = info
            if fallback is None:
                fallback = info
        return target or fallback

    def detect_monitor_source(self) -> str | None:
        try:
            import pyaudiowpatch as pyaudio
            p = pyaudio.PyAudio()
            try:
                info = self._find_loopback_info(p)
                return info["name"] if info else None
            finally:
                p.terminate()
        except Exception as e:
            logger.warning("PyAudio loopback デバイス取得失敗: %s", e)
            return None

    def list_devices(self) -> None:
        try:
            import pyaudiowpatch as pyaudio
            p = pyaudio.PyAudio()
            try:
                print(t("rec.wasapi_loopback_mics"))
                for info in p.get_loopback_device_info_generator():
                    name = info["name"]
                    marker = " (RDP — skipped)" if _is_rdp_audio(name) else ""
                    print(f"  {name}{marker}")
            finally:
                p.terminate()
        except ImportError:
            print(t("rec.wasapi_soundcard_unavailable"))

    def start_monitor_capture(self, source: str, audio_queue: queue.Queue,
                              stop_event: StopSignal,
                              level: CaptureLevel | None = None) -> None:
        """PyAudioWPatch の WASAPI loopback でキャプチャ (polling)。

        デバイスの native rate / channels で開き、Python 側で 16kHz mono に
        間引き + ミックスダウンしてから既存パイプラインに流す。
        """
        import pyaudiowpatch as pyaudio
        import numpy as np
        p = pyaudio.PyAudio()
        stream = None
        try:
            info = self._find_loopback_info(p, prefer_name=source or "")
            if info is None:
                logger.error("WASAPI loopback デバイスが見つかりません(RDP 除外後)")
                return
            if _is_rdp_audio(info["name"]):
                logger.error("RDP デバイス (%s) ではキャプチャしない", info["name"])
                return
            native_rate = int(info["defaultSampleRate"])
            channels = int(info["maxInputChannels"]) or 1
            decimate = max(1, native_rate // SAMPLE_RATE)
            native_block = FRAME_SIZE * decimate
            logger.info("WASAPI loopback キャプチャ開始: %s "
                        "(index=%d, native=%dHz/%dch → %dHz mono)",
                        info["name"], info["index"], native_rate, channels, SAMPLE_RATE)
            stream = p.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=native_rate,
                input=True,
                input_device_index=info["index"],
                frames_per_buffer=native_block,
            )
            while not stop_event.is_set():
                raw = stream.read(native_block, exception_on_overflow=False)
                arr = np.frombuffer(raw, dtype=np.int16)
                if channels > 1:
                    # ステレオ以上 → モノラルにミックスダウン
                    arr = arr.reshape(-1, channels).mean(axis=1).astype(np.int16)
                # native_rate → SAMPLE_RATE に間引き(整数比のみ、エイリアスは
                # 音声認識帯域には影響しない)
                if decimate > 1:
                    arr = arr[::decimate]
                if level is not None:
                    level.add(arr)
                audio_queue.put(arr.copy())
        except Exception as e:
            logger.error("WASAPI loopback キャプチャエラー: %s", e)
        finally:
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            p.terminate()
