"""Shadow-clerk daemon: 音声バックエンド"""
from __future__ import annotations
import collections
import logging
import queue
import re
import shutil
import subprocess
import sys
import threading
from typing import Any, Protocol
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import (
    SAMPLE_RATE, CHANNELS, FRAME_SIZE, IPC_TIMEOUT_SEC,
)
from shadow_clerk.domain import AudioDevice
# デバイス一覧スナップショット (snapshot_devices) は _daemon_audio_devices.py に
# 分離した。既存の import 元 (from shadow_clerk._daemon_audio import
# snapshot_devices) を壊さないよう、ここで re-export する。
# wpctl_audio_section_lines は device_exists 用のノード名抽出と共通のセクション
# 追跡ロジック（Audio → Sinks/Sources サブリスト限定）を再利用するため
from shadow_clerk._daemon_audio_devices import (  # noqa: F401
    snapshot_devices, wpctl_audio_section_lines, sink_serial,
    invalidate_description_cache,
)

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


def _capture_pcm_stream(cmd: list[str], name: str, audio_queue: queue.Queue,
                        stop_event: StopSignal) -> None:
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

    def start_monitor_capture(self, source: str, audio_queue: queue.Queue,
                              stop_event: StopSignal) -> None:
        """モニター音声を audio_queue に流し続ける。stop_event が立つまで戻らない。

        source が何を指すかはバックエンドごとに違う（PipeWire は Sink の
        object.serial、PulseAudio はモニターソース名、WASAPI は loopback
        デバイス名の部分一致）。何を渡すかは呼び出し側が決める。
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
                result = subprocess.run(
                    ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                    capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC,
                )
                if (serial := _wpctl_prop(result.stdout, "object.serial")):
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
                              stop_event: StopSignal) -> None:
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
                              stop_event: StopSignal) -> None:
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


def get_default_sink_name() -> str | None:
    """wpctl/pactl でデフォルト Sink の名前を取得。

    device_exists と同じ理由で、wpctl がタイムアウトした場合は pactl に進まず
    即座に諦める（同じサーバーに聞くので待つだけ無駄）。
    """
    # wpctl (PipeWire)
    if shutil.which("wpctl"):
        try:
            result = subprocess.run(
                ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC,
            )
            # node.name = "alsa_output.usb-Shokz..."
            if (name := _wpctl_prop(result.stdout, "node.name")):
                logger.debug("デフォルト Sink (wpctl): %s", name)
                return name
        except subprocess.TimeoutExpired:
            logger.warning("wpctl inspect がタイムアウトしました")
            return None
        except FileNotFoundError:
            pass

    # pactl (PulseAudio)
    if shutil.which("pactl"):
        try:
            result = subprocess.run(
                ["pactl", "get-default-sink"],
                capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC,
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
                              stop_event: StopSignal) -> None:
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


def refresh_device_list() -> None:
    """PortAudio のデバイス一覧を再列挙する。

    PortAudio は Pa_Initialize 時点の一覧をキャッシュし、以後に現れた/消えた
    ノードを認識しない（サスペンド復帰や USB オーディオの抜き差しで実際に起きる）。
    Pa_Terminate は開いている全ストリームを破棄するため、呼び出し側は
    全ストリームを閉じた状態で呼ぶこと。
    """
    import sounddevice as sd
    sd._terminate()
    sd._initialize()
    # デバイス構成が変わる唯一の契機。ラベル用 description のキャッシュを捨てる
    invalidate_description_cache()


def resolve_mic_device(index: int | None) -> AudioDevice | None:
    """マイクデバイスを解決。index=None なら PortAudio のデフォルト入力デバイス。"""
    import sounddevice as sd
    try:
        info = sd.query_devices(index, kind="input")
    except (ValueError, sd.PortAudioError) as e:
        logger.warning("マイクデバイスを解決できません (index=%s): %s", index, e)
        return None
    return AudioDevice(index=index, name=str(info["name"]))


def resolve_monitor_device(index: int | None) -> AudioDevice | None:
    """モニターデバイスを解決。index 指定時はそれを使い、未指定なら自動検出する。"""
    import sounddevice as sd
    if index is None:
        return find_monitor_device_sd()
    try:
        info = sd.query_devices(index)
    except (ValueError, sd.PortAudioError) as e:
        logger.warning("モニターデバイスを解決できません (index=%s): %s", index, e)
        return None
    return AudioDevice(index=index, name=str(info["name"]))


def find_device_by_name(name: str, capture: bool) -> AudioDevice | None:
    """デバイス名で検索する。capture=True なら入力デバイスに限る。

    デバイス番号は再列挙で入れ替わるため、同じデバイスを掴み直す唯一の手掛かり。
    """
    import sounddevice as sd
    try:
        devices = sd.query_devices()
    except Exception as e:
        logger.warning("デバイス一覧を取得できません: %s", e)
        return None
    for i, dev in enumerate(devices):
        if dev["name"] == name and (not capture or dev["max_input_channels"] > 0):
            return AudioDevice(index=i, name=name)
    return None


_WPCTL_ENTRY_RE = re.compile(r'\*?\s*\d+\.\s+(\S+)')


def _wpctl_audio_node_names(stdout: str) -> set[str]:
    """wpctl status --name の出力から Audio → Sinks/Sources のノード名集合を取る。

    wpctl status は Clients/Streams など無関係なセクションにも "NN. 名前" 形式の
    行を出す。特に pipewire-pulse は自身を Clients セクションにノード名
    "pipewire" として登録するため、そこを含めて照合すると PortAudio が返す
    デバイス名 "pipewire"（ALSA の pipewire プラグイン別名）と衝突して誤検出
    する。Audio セクション配下の Sinks:/Sources: サブリストだけに限定して読む
    （セクション追跡は wpctl_audio_section_lines と共通）。
    """
    return {m.group(1) for line in wpctl_audio_section_lines(stdout)
            if (m := _WPCTL_ENTRY_RE.match(line))}


def device_exists(name: str) -> bool | None:
    """OS 側の一覧にこの名前のノードがあるか。取得できなければ None。

    PortAudio の一覧はキャッシュで、再列挙には全ストリームの破棄が必要なため、
    「抜き差しされたデバイスが戻ったか」の判定には使えない。OS 側に直接聞く。
    PortAudio のデバイス名は PipeWire のノード名と一致する。

    `.monitor` で終わる名前は PulseAudio 互換レイヤーが合成する仮想ソースで、
    PipeWire ネイティブのノードとしては存在せず wpctl の一覧に出てこない。
    そのためサフィックスを外し、対応する Sink の存在で代用判定する:
    モニターソースは、その元になる Sink が存在する場合にのみ存在する。

    一覧との照合は部分一致ではなく、Audio セクションの Sinks:/Sources: に列挙
    されたノード名（wpctl）/ タブ区切りフィールドのデバイス名（pactl）との
    完全一致で行う。部分一致や無関係セクションを含めた一致だと、例えば
    "pipewire" が wpctl の Clients セクションにある pipewire-pulse 自身の
    ノード名と誤ってマッチしてしまう。

    これはキャプチャスレッド上で同期的に走る。wpctl がタイムアウトした場合に
    pactl へ進まないのは、両者とも同じ PipeWire サーバーに聞いており、片方が
    刺さっているならもう片方も刺さるため。無駄に待って shutdown の join
    （5 秒）を食い潰すだけなので、判定不能 (None) として即座に返す。
    """
    target = name[: -len(".monitor")] if name.endswith(".monitor") else name
    if shutil.which("wpctl"):
        try:
            result = subprocess.run(["wpctl", "status", "--name"],
                                    capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC)
            if result.returncode == 0 and result.stdout:
                return target in _wpctl_audio_node_names(result.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("wpctl status がタイムアウトしました (%s)", name)
            return None
        except FileNotFoundError:
            pass
    if shutil.which("pactl"):
        for kind in ("sources", "sinks"):
            try:
                result = subprocess.run(["pactl", "list", "short", kind],
                                        capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return None
            for line in result.stdout.splitlines():
                fields = line.split("\t")
                if len(fields) >= 2 and fields[1] == target:
                    return True
        return False
    return None


def find_monitor_device_sd() -> AudioDevice | None:
    """sounddevice でモニターデバイスを検索 (Linux のみ)

    Windows は WasapiBackend を使うため None を返す。
    """
    if sys.platform == "win32":
        return None
    return _find_monitor_device_linux()


def _find_monitor_device_linux() -> AudioDevice | None:
    """Linux (PipeWire/PulseAudio) でモニターデバイスを検索

    PipeWire: `.monitor` サフィックスを持つ入力デバイス
    PulseAudio: "Monitor of " プレフィックスを持つ入力デバイス
    デフォルト Sink に対応するモニターを優先する。
    """
    import sounddevice as sd
    try:
        devices = sd.query_devices()
    except Exception as e:
        # 呼び出し元は全キャプチャを持つ 1 スレッドなので、ここで例外を漏らすと
        # マイクごと録音が止まる
        logger.warning("デバイス一覧を取得できません: %s", e)
        return None
    candidates = []
    for i, dev in enumerate(devices):
        name = dev["name"]
        is_monitor = (
            name.endswith(".monitor")
            or name.lower().startswith("monitor of ")
        )
        if is_monitor and dev["max_input_channels"] > 0:
            candidates.append(AudioDevice(index=i, name=name))
            logger.debug("monitor 候補: %s", candidates[-1])

    if not candidates:
        logger.debug("monitor 候補なし")
        return None

    # デフォルト Sink に対応するモニターを優先
    default_sink = get_default_sink_name()
    if default_sink:
        expected_monitor = default_sink + ".monitor"
        for device in candidates:
            if device.name == expected_monitor:
                logger.debug("デフォルト Sink のモニター選択: %s", device)
                return device

    # 見つからなければ最初の候補
    logger.debug("デフォルト Sink 不明、最初の候補を選択: %s", candidates[0])
    return candidates[0]


def list_all_devices(backend_name: str, backend: AudioBackend | None) -> None:
    """全デバイス一覧表示"""
    import sounddevice as sd
    print(t("rec.sounddevice_devices"))
    print(sd.query_devices())

    if backend:
        backend.list_devices()

    monitor_sd = find_monitor_device_sd()
    if monitor_sd is not None:
        print(t("rec.auto_detect_sd", device=monitor_sd.index))

    if backend:
        monitor = backend.detect_monitor_source()
        if monitor:
            print(t("rec.auto_detect_backend", backend=backend_name, source=monitor))
