"""Shadow-clerk daemon: 音声デバイス一覧のスナップショット（ダッシュボードのデバイス選択用）"""
from __future__ import annotations
import json
import logging
import re
import shutil
import subprocess
from collections.abc import Iterator
from typing import Any
from shadow_clerk.i18n import t
from shadow_clerk._daemon_constants import IPC_TIMEOUT_SEC

logger = logging.getLogger("shadow-clerk")

_WPCTL_TOP_SECTION_RE = re.compile(r'^(Audio|Video|Settings|Jack|Midi)\s*$')
_WPCTL_LIST_HEADER_RE = re.compile(r'(Devices|Sinks|Sources|Filters|Streams):\s*$')
_WPCTL_ID_TEXT_RE = re.compile(r'^\*?\s*(\d+)\.\s+(.*)$')
_WPCTL_VOL_SUFFIX_RE = re.compile(r'\s*\[[^\]]*\]\s*$')
_HIFI_PORT_RE = re.compile(r'HiFi__([A-Za-z0-9]+)__(?:source|sink)')


def _wpctl_status(args: list[str]) -> str:
    """`wpctl status [args]` の stdout を返す。wpctl が無い/失敗した場合は空文字。"""
    if not shutil.which("wpctl"):
        return ""
    try:
        result = subprocess.run(["wpctl", "status", *args],
                                capture_output=True, text=True, timeout=IPC_TIMEOUT_SEC)
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def sink_serial(node_name: str) -> str | None:
    """PipeWire の Sink ノード名を `pw-record --target` 用の object.serial に解決する。

    pw-record の --target は、名前で指定した場合 Source ノードとしか照合しない。
    Sink 名（や "<Sink 名>.monitor"）を渡すと一致せず、警告も非ゼロ終了も無いまま
    既定の Source ＝ ユーザーのマイクにフォールバックする。モニターのはずの系統が
    マイクを録り、全発言が二重に転写される。Sink を確実に指す方法は数値の
    object.serial を渡すことだけ（object.id では駄目。両者は別の番号空間）。

    ノード名 → serial の引き当てに pw-dump を使うのは、`wpctl inspect` が
    ノード名を受け付けず（数値 ID か @DEFAULT_*@ のみ）、名前から引くには
    `wpctl status --name` ＋ ノード数ぶんの `wpctl inspect` が必要になるため。
    pw-dump なら 1 回の呼び出しで全ノードの node.name / object.serial /
    media.class が構造化 JSON で取れる。
    """
    for props in _pw_dump_node_props():
        if (props.get("media.class") == "Audio/Sink"
                and props.get("node.name") == node_name
                and (serial := props.get("object.serial")) is not None):
            return str(serial)
    return None


def _pw_dump_node_props() -> Iterator[dict[str, Any]]:
    """pw-dump から Node オブジェクトの props を順に yield する。

    pw-dump が無い/失敗した場合は何も yield しない（呼び出し側がフォールバック）。
    """
    if not shutil.which("pw-dump"):
        return
    try:
        result = subprocess.run(["pw-dump"], capture_output=True, text=True,
                                timeout=IPC_TIMEOUT_SEC)
        objects = json.loads(result.stdout) if result.returncode == 0 else []
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("pw-dump からノード情報を取得できません: %s", e)
        return
    if not isinstance(objects, list):
        return
    for obj in objects:
        if isinstance(obj, dict) and obj.get("type") == "PipeWire:Interface:Node":
            props = (obj.get("info") or {}).get("props")
            if isinstance(props, dict):
                yield props


def wpctl_audio_section_lines(stdout: str) -> Iterator[str]:
    """wpctl status の出力から Audio → Sinks/Sources 配下の行だけを yield する。

    `device_exists`（_daemon_audio.py の `_wpctl_audio_node_names`）とこのモジュール
    の ID+description 抽出は同じセクション追跡が必要なため、共通の歩き方をここに
    まとめる。Devices/Filters/Streams など無関係なリストは対象外にする:
    pipewire-pulse は自身を Clients セクションにノード名 "pipewire" として登録し、
    無関係セクションまで含めると PortAudio の ALSA プラグイン別名 "pipewire" と
    誤って一致する。
    """
    section: str | None = None
    subsection: str | None = None
    for raw_line in stdout.splitlines():
        line = raw_line.strip(" │└├─")
        if not line:
            continue
        if (m := _WPCTL_TOP_SECTION_RE.match(line)):
            section, subsection = m.group(1), None
            continue
        if (m := _WPCTL_LIST_HEADER_RE.search(line)):
            subsection = m.group(1)
            continue
        if section == "Audio" and subsection in ("Sinks", "Sources"):
            yield line


def _wpctl_audio_entries(stdout: str) -> dict[str, str]:
    """wpctl status の出力から Audio → Sinks/Sources の {ノード ID: 表示テキスト} を取る。

    末尾の "[vol: ...]" のような注記は取り除く。
    """
    entries: dict[str, str] = {}
    for line in wpctl_audio_section_lines(stdout):
        if (m := _WPCTL_ID_TEXT_RE.match(line)):
            node_id, text = m.groups()
            entries[node_id] = _WPCTL_VOL_SUFFIX_RE.sub("", text).strip()
    return entries


_description_cache: dict[str, str] | None = None


def invalidate_description_cache() -> None:
    """デバイス再列挙時に呼ぶ。次の snapshot_devices で wpctl を引き直させる。

    デバイス構成が変わるのは再列挙（refresh_device_list）を伴う場面だけなので、
    そこだけ捨てれば十分。
    """
    global _description_cache  # pylint: disable=global-statement
    _description_cache = None


def _wpctl_description_map() -> dict[str, str]:
    """PipeWire ノード名 → OS の人間向け description の対応表を返す（キャッシュ付き）。

    `wpctl status --name` はノード名、`wpctl status`（--name 無し）は
    description を同じノード ID に対して出す。両方を取得して ID で対応付ける。
    wpctl が無い/取得できない環境では空の辞書を返し、呼び出し側はヒューリス
    ティックにフォールバックする。

    snapshot_devices はキャプチャスレッドがストリームを開くたびに呼ぶため、
    毎回 wpctl を 2 回 fork していると shutdown の join 予算を圧迫する。
    結果は再列挙まで変わらないのでキャッシュする。取得できなかった場合
    （空）はキャッシュせず次回引き直す — wpctl 不在なら subprocess は起きない
    ので、再試行のコストは無い。
    """
    global _description_cache  # pylint: disable=global-statement
    if _description_cache is not None:
        return _description_cache
    names = _wpctl_audio_entries(_wpctl_status(["--name"]))
    if not names:
        return {}
    descriptions = _wpctl_audio_entries(_wpctl_status([]))
    _description_cache = {name: descriptions[node_id]
                          for node_id, name in names.items() if node_id in descriptions}
    return _description_cache


def snapshot_devices() -> dict[str, Any]:
    """UI に出すデバイス一覧のスナップショットを取る。

    PortAudio のキャッシュを読むだけなので、ストリームを開くたびに呼んでも
    コストは無視できる。ブラウザからの要求ごとに再列挙はできない
    （refresh_device_list が全ストリームを破棄するため）ので、監視スレッドが
    このスナップショットを更新し、API はそれを返す。
    """
    import sounddevice as sd
    import time as _time
    mic: list[dict[str, str]] = []
    monitor: list[dict[str, str]] = []
    try:
        devices = sd.query_devices()
    except Exception as e:
        logger.warning("デバイス一覧を取得できません: %s", e)
        return {"mic": [], "monitor": [], "updated_at": None}
    inputs = [str(d["name"]) for d in devices if d["max_input_channels"] > 0]
    # 選択肢は PipeWire/PulseAudio のノードに限る。PortAudio は生 ALSA デバイス
    # ("HD-Audio Generic: ALC257 Analog (hw:1,0)") も列挙するが、これらは
    # device_exists で存在を確認できず復帰判定が働かない上、掴むとサウンド
    # カードを排他確保して他アプリの音を壊す。ノードが 1 つも無い環境
    # (PipeWire/PulseAudio 不在) でのみ全件にフォールバックする
    nodes = [n for n in inputs
             if n.startswith("alsa_input.") or n.startswith("alsa_output.")]
    desc_map = _wpctl_description_map()
    for name in (nodes or inputs):
        entry = {"name": name, "label": _device_label(name, desc_map)}
        if name.endswith(".monitor") or name.lower().startswith("monitor of "):
            monitor.append(entry)
        else:
            mic.append(entry)
    # オンボードデバイスは複数ポートが同じバス ID を共有するため、OS の
    # description・フォールバックのどちらでラベルを作っても偶然重複する
    # ことがある。UI で選択不能にならないよう最後に必ず一意化する
    _disambiguate_labels(mic)
    _disambiguate_labels(monitor)
    return {"mic": mic, "monitor": monitor, "updated_at": _time.time()}


def _device_label(name: str, desc_map: dict[str, str]) -> str:
    """デバイス名を人間が読める形に整える。

    OS (wpctl) が返す description があればそれを優先する。モニターデバイスは
    Sources には出てこない（PulseAudio 互換レイヤーが合成する仮想ソースの
    ため）ので、元になる Sink 名（".monitor" を外した名前）で desc_map を引き、
    見つかれば "(モニター)" を付記する。desc_map に無い名前・wpctl が使えない
    環境ではヒューリスティックにフォールバックする。
    """
    is_monitor = name.endswith(".monitor")
    lookup_name = name[: -len(".monitor")] if is_monitor else name
    if lookup_name in desc_map:
        label = desc_map[lookup_name]
        return f"{label} ({t('dash.audio_device_monitor')})" if is_monitor else label
    return _fallback_label(name)


def _fallback_label(name: str) -> str:
    """wpctl の description が無い場合のヒューリスティック整形。

    例: alsa_input.usb-Shokz_Shokz_Loop110_96D3...-02.mono-fallback
        → Shokz Shokz Loop110 (usb)
        alsa_input.pci-0000_c4_00.6.HiFi__Mic2__source → pci Mic2

    オンボードデバイスは複数ポート（Mic1/Mic2, HDMI1-4 等）が同じバス ID
    ("pci-0000_c4_00") を共有し、バス ID だけでは区別できない。
    "HiFi__<port>__source/sink" パターンがあれば、単純な最初の "." までの
    切り出し（バス ID の直後で切れてポート名が丸ごと消える）より優先して
    ポート名を残す。整形できない名前はそのまま返す。
    """
    body = name
    for prefix in ("alsa_input.", "alsa_output."):
        if body.startswith(prefix):
            body = body[len(prefix):]
            break
    body = body.removesuffix(".monitor")
    parts = body.split("-", 1)
    if len(parts) < 2 or parts[0] not in ("usb", "pci", "platform", "bluez"):
        return name
    bus, rest = parts
    if (m := _HIFI_PORT_RE.search(rest)):
        return f"{bus} {m.group(1)}"
    # usb-Shokz_Shokz_Loop110_96D3...-02.mono-fallback → Shokz Shokz Loop110
    middle = rest.split(".")[0]
    words = [w for w in middle.split("_") if w and not w.isdigit()]
    # 末尾のシリアルらしき長い英数字は落とす
    if words and len(words[-1]) > 12 and any(c.isdigit() for c in words[-1]):
        words = words[:-1]
    if words:
        return f"{' '.join(words)} ({bus})"
    return name


def _distinguishing_suffix(name: str) -> str:
    """重複解消の最終防衛で使う、name から取れる判別用の断片。"""
    if (m := _HIFI_PORT_RE.search(name)):
        return m.group(1)
    tail = name.rsplit(".", 1)[-1] if "." in name else name
    return tail or name


def _disambiguate_labels(entries: list[dict[str, str]]) -> None:
    """同じリスト内で label が重複したら決定的に区別する（最終防衛線）。

    OS description・ヒューリスティックどちらの経路で作られた label でも、
    ここを必ず通すことで例えば「c4 (pci)」のような重複が UI に出ないことを
    保証する。まず name から取れる断片を付記し、それでも衝突する場合は
    連番で確実に一意化する。
    """
    def _dupes() -> set[str]:
        seen: set[str] = set()
        dupes: set[str] = set()
        for e in entries:
            (dupes if e["label"] in seen else seen).add(e["label"])
        return dupes

    for label in _dupes():
        for e in entries:
            if e["label"] == label:
                e["label"] = f"{label} ({_distinguishing_suffix(e['name'])})"

    for label in _dupes():  # 断片同士がさらに衝突した場合の最終防衛
        n = 0
        for e in entries:
            if e["label"] == label:
                n += 1
                e["label"] = f"{label} #{n}"
