"""Shadow-clerk daemon: 音声デバイスの解決とデフォルト Sink/Source 名の取得

バックエンド検出 (detect_backend) に加え、PortAudio 経由のマイク/モニター
デバイス解決、OS 側の存在確認 (device_exists)、デフォルト Sink/Source 名の
取得を持つ。バックエンド実装 (pw-record/parec/WASAPI) は
_daemon_audio_backends.py、デバイス一覧のスナップショットは
_daemon_audio_devices.py に分離済み。
"""
from __future__ import annotations
import logging
import re
import shutil
import subprocess
import sys
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import IPC_TIMEOUT_SEC
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
# バックエンド実装 (pw-record/parec/WASAPI ループバック) は
# _daemon_audio_backends.py に分離した。既存の import 元
# (from shadow_clerk._daemon_audio import AudioBackend, ...) を壊さないよう、
# ここで re-export する
from shadow_clerk._daemon_audio_backends import (  # noqa: F401
    StopSignal, AudioBackend, PipeWireBackend, PulseAudioBackend, WasapiBackend,
    _wpctl_prop, _wpctl_inspect_default_sink, _wpctl_inspect_default_source,
    _capture_pcm_stream,
)

logger = logging.getLogger("shadow-clerk")


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
            stdout = _wpctl_inspect_default_sink()
            # node.name = "alsa_output.usb-Shokz..."
            if (name := _wpctl_prop(stdout, "node.name")):
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


def get_default_source_name() -> str | None:
    """wpctl/pactl でデフォルト Source の人間向け名前を取得。

    get_default_sink_name の Source 版。ただし用途が異なる: get_default_sink_name
    はモニター名 (".monitor" の元) を突き合わせるための node.name が必須だが、
    ここはレベルバーのツールチップに出す表示専用なので、wpctl が返す
    node.description（例:「Shokz Loop110 モノ」）を node.name より優先する。
    device=None でマイクを開くと PortAudio は "default" のようなエイリアスしか
    返さないため、呼び出し側 (FileWatcher) がこの結果でそれを解決する。
    """
    if shutil.which("wpctl"):
        try:
            stdout = _wpctl_inspect_default_source()
            name = _wpctl_prop(stdout, "node.description") or _wpctl_prop(stdout, "node.name")
            if name:
                logger.debug("デフォルト Source (wpctl): %s", name)
                return name
        except subprocess.TimeoutExpired:
            logger.warning("wpctl inspect がタイムアウトしました")
            return None
        except FileNotFoundError:
            pass

    if shutil.which("pactl"):
        try:
            result = subprocess.run(
                ["pactl", "get-default-source"],
                capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC,
            )
            name = result.stdout.strip()
            if name:
                logger.debug("デフォルト Source (pactl): %s", name)
                return name
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return None


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
