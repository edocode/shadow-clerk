"""Shadow-clerk daemon: 音声バックエンド"""
from __future__ import annotations
import collections
import logging
import queue
import shutil
import subprocess
import sys
import threading
from typing import Any
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import SAMPLE_RATE, CHANNELS, FRAME_SIZE

logger = logging.getLogger("shadow-clerk")


def _capture_pcm_stream(cmd: list[str], name: str, audio_queue: queue.Queue,
                        stop_event: threading.Event) -> None:
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


class PipeWireBackend(AudioBackend):
    """PipeWire バックエンド"""

    @staticmethod
    def is_available() -> bool:
        return shutil.which("pw-record") is not None

    def detect_monitor_source(self) -> str | None:
        # wpctl でデフォルト Sink のノード ID を取得
        if shutil.which("wpctl"):
            try:
                result = subprocess.run(
                    ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                    capture_output=True, text=True, timeout=5,
                )
                # 1行目: "id 74, type PipeWire:Interface:Node"
                first = result.stdout.split("\n", 1)[0]
                if first.startswith("id "):
                    node_id = first.split(",")[0].split()[1]
                    logger.info("PipeWire デフォルト Sink ノード ID: %s (wpctl)", node_id)
                    return node_id
            except (subprocess.TimeoutExpired, FileNotFoundError, IndexError, ValueError):
                pass
        # wpctl でノード ID が取れなかった場合は pw-record では使えないため None を返す。
        # 呼び出し側が PulseAudio バックエンドへフォールバックする。
        logger.debug("PipeWire: wpctl からノード ID を取得できませんでした。PulseAudio にフォールバックします。")
        return None

    def list_devices(self) -> None:
        print(t("rec.pipewire_devices"))
        if shutil.which("wpctl"):
            try:
                result = subprocess.run(
                    ["wpctl", "status"],
                    capture_output=True, text=True, timeout=5,
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
                    capture_output=True, text=True, timeout=5,
                )
                if result.stdout.strip():
                    print(result.stdout)
                else:
                    print(t("rec.no_devices"))
                return
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass
        print(t("rec.pw_unavailable"))

    def start_monitor_capture(self, target: str, audio_queue: queue.Queue,
                              stop_event: threading.Event) -> None:
        """pw-record でモニターソースをキャプチャ"""
        cmd = [
            "pw-record", "--target", target,
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--format", "s16",
            "-",
        ]
        _capture_pcm_stream(cmd, "PipeWire", audio_queue, stop_event)


class PulseAudioBackend(AudioBackend):
    """PulseAudio バックエンド"""

    @staticmethod
    def is_available() -> bool:
        return shutil.which("pactl") is not None

    def detect_monitor_source(self) -> str | None:
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=5,
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
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print(t("rec.no_sources"))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print(t("rec.pa_unavailable"))

    def start_monitor_capture(self, source: str, audio_queue: queue.Queue,
                              stop_event: threading.Event) -> None:
        """parec でモニターソースをキャプチャ"""
        cmd = [
            "parec",
            f"--device={source}",
            f"--rate={SAMPLE_RATE}",
            "--channels=1",
            "--format=s16le",
        ]
        _capture_pcm_stream(cmd, "PulseAudio", audio_queue, stop_event)


def detect_backend(preferred: str = "auto") -> tuple[str, AudioBackend | None]:
    """音声バックエンドを検出"""
    if preferred == "pipewire":
        if PipeWireBackend.is_available():
            return "pipewire", PipeWireBackend()
        logger.warning("PipeWire が利用できません、sounddevice にフォールバック")
        return "sounddevice", None

    if preferred == "pulseaudio":
        if PulseAudioBackend.is_available():
            return "pulseaudio", PulseAudioBackend()
        logger.warning("PulseAudio が利用できません、sounddevice にフォールバック")
        return "sounddevice", None

    if preferred == "wasapi":
        if WasapiBackend.is_available():
            return "wasapi", WasapiBackend()
        logger.warning("PyAudioWPatch が利用できません、sounddevice にフォールバック")
        return "sounddevice", None

    if preferred == "sounddevice":
        return "sounddevice", None

    # auto: Windows → WasapiBackend / Linux → PipeWire → PulseAudio → sounddevice
    if sys.platform == "win32":
        if WasapiBackend.is_available():
            return "wasapi", WasapiBackend()
        return "sounddevice", None
    if PipeWireBackend.is_available():
        return "pipewire", PipeWireBackend()
    if PulseAudioBackend.is_available():
        return "pulseaudio", PulseAudioBackend()
    return "sounddevice", None


def _get_default_sink_name() -> str | None:
    """wpctl/pactl でデフォルト Sink の名前を取得"""
    # wpctl (PipeWire)
    if shutil.which("wpctl"):
        try:
            result = subprocess.run(
                ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                line = line.strip().lstrip("* ")
                if line.startswith("node.name"):
                    # node.name = "alsa_output.usb-Shokz..."
                    parts = line.split("=", 1)
                    if len(parts) == 2:
                        name = parts[1].strip().strip('"')
                        logger.debug("デフォルト Sink (wpctl): %s", name)
                        return name
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    # pactl (PulseAudio)
    if shutil.which("pactl"):
        try:
            result = subprocess.run(
                ["pactl", "get-default-sink"],
                capture_output=True, text=True, timeout=5,
            )
            name = result.stdout.strip()
            if name:
                logger.debug("デフォルト Sink (pactl): %s", name)
                return name
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return None


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
                              stop_event: threading.Event) -> None:
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


def find_monitor_device_sd() -> tuple[int, dict[str, Any]] | None:
    """sounddevice でモニターデバイスを検索 (Linux のみ)

    戻り値: (デバイスID, sd.InputStream に追加で渡す kwargs) または None。
    Windows は WasapiBackend を使うため None を返す。
    """
    if sys.platform == "win32":
        return None
    return _find_monitor_device_linux()


def _find_monitor_device_linux() -> tuple[int, dict[str, Any]] | None:
    """Linux (PipeWire/PulseAudio) でモニターデバイスを検索

    PipeWire: `.monitor` サフィックスを持つ入力デバイス
    PulseAudio: "Monitor of " プレフィックスを持つ入力デバイス
    デフォルト Sink に対応するモニターを優先する。
    """
    import sounddevice as sd
    devices = sd.query_devices()
    candidates = []
    for i, dev in enumerate(devices):
        name = dev["name"]
        is_monitor = (
            name.endswith(".monitor")
            or name.lower().startswith("monitor of ")
        )
        if is_monitor and dev["max_input_channels"] > 0:
            candidates.append((i, name))
            logger.debug("monitor 候補: #%d %s", i, name)

    if not candidates:
        logger.debug("monitor 候補なし")
        return None

    # デフォルト Sink に対応するモニターを優先
    default_sink = _get_default_sink_name()
    if default_sink:
        expected_monitor = default_sink + ".monitor"
        for idx, name in candidates:
            if name == expected_monitor:
                logger.debug("デフォルト Sink のモニター選択: #%d %s", idx, name)
                return idx, {}

    # 見つからなければ最初の候補
    logger.debug("デフォルト Sink 不明、最初の候補を選択: #%d %s", *candidates[0])
    return candidates[0][0], {}


def list_all_devices(backend_name: str, backend: AudioBackend | None) -> None:
    """全デバイス一覧表示"""
    import sounddevice as sd
    print(t("rec.sounddevice_devices"))
    print(sd.query_devices())

    if backend:
        backend.list_devices()

    monitor_sd = find_monitor_device_sd()
    if monitor_sd is not None:
        device_idx, _ = monitor_sd
        print(t("rec.auto_detect_sd", device=device_idx))

    if backend:
        monitor = backend.detect_monitor_source()
        if monitor:
            print(t("rec.auto_detect_backend", backend=backend_name, source=monitor))
