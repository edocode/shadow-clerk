"""Shadow-clerk daemon: 音声バックエンド"""
import logging
import queue
import shutil
import subprocess
import threading
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import SAMPLE_RATE, CHANNELS, FRAME_SIZE

logger = logging.getLogger("shadow-clerk")


class AudioBackend:
    """音声バックエンド基底クラス"""

    def detect_monitor_source(self) -> str | None:
        raise NotImplementedError

    def list_devices(self):
        raise NotImplementedError


class PipeWireBackend(AudioBackend):
    """PipeWire バックエンド"""

    @staticmethod
    def is_available() -> bool:
        return shutil.which("pw-record") is not None

    def detect_monitor_source(self) -> str | None:
        try:
            result = subprocess.run(
                ["pw-record", "--list-targets"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "monitor" in line.lower():
                    return line.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return None

    def list_devices(self):
        print(t("rec.pipewire_devices"))
        try:
            result = subprocess.run(
                ["pw-record", "--list-targets"],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                print(result.stdout)
            else:
                print(t("rec.no_devices"))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            print(t("rec.pw_unavailable"))

    def start_monitor_capture(self, target: str, audio_queue: queue.Queue,
                              stop_event: threading.Event):
        """pw-record でモニターソースをキャプチャ"""
        cmd = [
            "pw-record", "--target", target,
            "--rate", str(SAMPLE_RATE),
            "--channels", str(CHANNELS),
            "--format", "s16",
            "-",
        ]
        logger.info("PipeWire monitor capture: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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

    def list_devices(self):
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
                              stop_event: threading.Event):
        """parec でモニターソースをキャプチャ"""
        cmd = [
            "parec",
            f"--device={source}",
            f"--rate={SAMPLE_RATE}",
            "--channels=1",
            "--format=s16le",
        ]
        logger.info("PulseAudio monitor capture: %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
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

    if preferred == "sounddevice":
        return "sounddevice", None

    # auto: PipeWire → PulseAudio → sounddevice
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


def find_monitor_device_sd() -> int | None:
    """sounddevice でモニターデバイスを検索

    `.monitor` サフィックスを持つ入力デバイスのみを対象とする。
    デフォルト Sink に対応するモニターを優先する。
    """
    import sounddevice as sd
    devices = sd.query_devices()
    candidates = []
    for i, dev in enumerate(devices):
        name = dev["name"]
        if name.endswith(".monitor") and dev["max_input_channels"] > 0:
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
                return idx

    # 見つからなければ最初の候補
    logger.debug("デフォルト Sink 不明、最初の候補を選択: #%d %s", *candidates[0])
    return candidates[0][0]


def list_all_devices(backend_name: str, backend: AudioBackend | None):
    """全デバイス一覧表示"""
    import sounddevice as sd
    print(t("rec.sounddevice_devices"))
    print(sd.query_devices())

    if backend:
        backend.list_devices()

    monitor_sd = find_monitor_device_sd()
    if monitor_sd is not None:
        print(t("rec.auto_detect_sd", device=monitor_sd))

    if backend:
        monitor = backend.detect_monitor_source()
        if monitor:
            print(t("rec.auto_detect_backend", backend=backend_name, source=monitor))
