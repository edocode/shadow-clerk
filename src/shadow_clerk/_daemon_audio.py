"""Shadow-clerk daemon: 音声バックエンド"""
from __future__ import annotations
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
        logger.info("PipeWire monitor capture: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None and proc.stderr is not None
        try:
            while not stop_event.is_set():
                data = proc.stdout.read(FRAME_SIZE * 2)
                if not data:
                    break
                if len(data) == FRAME_SIZE * 2:
                    import numpy as np
                    samples = np.frombuffer(data, dtype=np.int16)
                    audio_queue.put(samples)
        finally:
            proc.terminate()
            proc.wait()
            err = proc.stderr.read()
            if err:
                logger.warning("pw-record stderr: %s", err.decode("utf-8", errors="replace").strip())


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
        logger.info("PulseAudio monitor capture: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert proc.stdout is not None and proc.stderr is not None
        try:
            while not stop_event.is_set():
                data = proc.stdout.read(FRAME_SIZE * 2)
                if not data:
                    break
                if len(data) == FRAME_SIZE * 2:
                    import numpy as np
                    samples = np.frombuffer(data, dtype=np.int16)
                    audio_queue.put(samples)
        finally:
            proc.terminate()
            proc.wait()
            err = proc.stderr.read()
            if err:
                logger.warning("parec stderr: %s", err.decode("utf-8", errors="replace").strip())


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

    if preferred == "wasapi_soundcard":
        if WasapiSoundcardBackend.is_available():
            return "wasapi_soundcard", WasapiSoundcardBackend()
        logger.warning("soundcard が利用できません、sounddevice にフォールバック")
        return "sounddevice", None

    if preferred == "sounddevice":
        return "sounddevice", None

    # auto: Windows → WasapiSoundcardBackend / Linux → PipeWire → PulseAudio → sounddevice
    if sys.platform == "win32":
        if WasapiSoundcardBackend.is_available():
            return "wasapi_soundcard", WasapiSoundcardBackend()
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
    """RDP の virtual audio device か判定。

    soundcard で recorder を開くと WASAPI ドライバ層でセグフォし Python が
    無言で落ちるため、loopback 候補から除外する。
    """
    if not name:
        return False
    n = name.lower()
    return (
        "リモート オーディオ" in name      # ja (full-width space)
        or "リモート デスクトップ" in name  # ja (RDP redirected device)
        or "remote audio" in n             # en
        or "remote desktop" in n           # en
    )


class WasapiSoundcardBackend(AudioBackend):
    """Windows WASAPI ループバックバックエンド (soundcard パッケージ)"""

    @staticmethod
    def is_available() -> bool:
        if sys.platform != "win32":
            return False
        try:
            import soundcard  # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _local_loopback_mics() -> list:
        """RDP デバイスを除いた loopback マイク一覧"""
        import soundcard
        result = []
        for mic in soundcard.all_microphones(include_loopback=True):
            if not getattr(mic, "isloopback", False):
                continue
            if _is_rdp_audio(mic.name):
                logger.info("RDP オーディオデバイスをスキップ: %s", mic.name)
                continue
            result.append(mic)
        return result

    def detect_monitor_source(self) -> str | None:
        try:
            import soundcard
            default_spk_name = soundcard.default_speaker().name
            if _is_rdp_audio(default_spk_name):
                logger.info("既定スピーカーが RDP デバイス (%s)、ローカル loopback を探す",
                            default_spk_name)
                default_spk_name = ""
            local_mics = self._local_loopback_mics()
            # 既定スピーカーに対応する loopback を優先
            for mic in local_mics:
                if default_spk_name and mic.name == default_spk_name:
                    return mic.name
            # フォールバック: 最初のローカル loopback
            if local_mics:
                return local_mics[0].name
            return None
        except Exception as e:
            logger.warning("soundcard loopback マイク取得失敗: %s", e)
            return None

    def list_devices(self) -> None:
        try:
            import soundcard
            print(t("rec.wasapi_loopback_mics"))
            for mic in soundcard.all_microphones(include_loopback=True):
                if not getattr(mic, "isloopback", False):
                    continue
                marker = " (RDP — skipped)" if _is_rdp_audio(mic.name) else ""
                print(f"  {mic.name}{marker}")
        except ImportError:
            print(t("rec.wasapi_soundcard_unavailable"))

    def start_monitor_capture(self, source: str, audio_queue: queue.Queue,
                              stop_event: threading.Event) -> None:
        """soundcard の loopback マイクで WASAPI ループバックキャプチャ (polling)"""
        import numpy as np
        loopback_mics = self._local_loopback_mics()
        if not loopback_mics:
            logger.error("WASAPI loopback マイクが見つかりません(RDP デバイス除外後)")
            return
        mic = next((m for m in loopback_mics if m.name == source), loopback_mics[0])
        if _is_rdp_audio(mic.name):
            # source が RDP デバイス指定だった場合のガード(異常系)
            logger.error("RDP デバイス (%s) ではキャプチャしない", mic.name)
            return
        logger.info("WASAPI loopback キャプチャ開始: %s", mic.name)
        try:
            with mic.recorder(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=FRAME_SIZE) as rec:
                while not stop_event.is_set():
                    data = rec.record(numframes=FRAME_SIZE)
                    samples = (data[:, 0] * 32767).astype(np.int16)
                    audio_queue.put(samples)
        except Exception as e:
            logger.error("WASAPI loopback キャプチャエラー: %s", e)


def find_monitor_device_sd() -> tuple[int, dict[str, Any]] | None:
    """sounddevice でモニターデバイスを検索 (Linux のみ)

    戻り値: (デバイスID, sd.InputStream に追加で渡す kwargs) または None。
    Windows は WasapiSoundcardBackend を使うため None を返す。
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
