"""macOS 対応: 仮想オーディオデバイスを monitor に使う・/proc の無い環境でのプロセス確認・PTT キー"""
from __future__ import annotations

import os
import subprocess
from unittest.mock import patch

import pytest

from shadow_clerk import _daemon_audio, _daemon_audio_devices, _process
from shadow_clerk._daemon_audio_devices import is_monitor_name
from shadow_clerk._daemon_recorder_command import _RecorderCommandMixin

DEVICES = [
    {"name": "BlackHole 2ch", "max_input_channels": 2},
    {"name": "Built-in Microphone", "max_input_channels": 1},
    {"name": "Built-in Output", "max_input_channels": 0},
]


@pytest.mark.parametrize(("platform", "name", "expected"), [
    ("linux", "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor", True),
    ("linux", "Monitor of Built-in Audio", True),
    ("linux", "BlackHole 2ch", False),
    ("darwin", "BlackHole 2ch", True),
    ("darwin", "BlackHole 16ch", True),
    ("darwin", "Loopback Audio", True),
    ("darwin", "Built-in Microphone", False),
])
def test_is_monitor_name(platform: str, name: str, expected: bool) -> None:
    with patch.object(_daemon_audio_devices.sys, "platform", platform):
        assert is_monitor_name(name) is expected


def test_snapshot_puts_virtual_device_on_monitor_side() -> None:
    with patch.object(_daemon_audio_devices.sys, "platform", "darwin"), \
            patch("sounddevice.query_devices", return_value=DEVICES), \
            patch.object(_daemon_audio_devices, "_wpctl_description_map", return_value={}):
        snap = _daemon_audio_devices.snapshot_devices()
    assert [d["name"] for d in snap["monitor"]] == ["BlackHole 2ch"]
    assert [d["name"] for d in snap["mic"]] == ["Built-in Microphone"]


def test_monitor_autodetect_finds_virtual_device() -> None:
    with patch.object(_daemon_audio_devices.sys, "platform", "darwin"), \
            patch.object(_daemon_audio.sys, "platform", "darwin"), \
            patch("sounddevice.query_devices", return_value=DEVICES), \
            patch.object(_daemon_audio, "get_default_sink_name", return_value=None):
        device = _daemon_audio.find_monitor_device_sd()
    assert device is not None and (device.index, device.name) == (0, "BlackHole 2ch")


def _no_proc(path: str) -> bool:
    return False if path == "/proc" else os.path.isdir(path)


def test_all_pids_without_proc_uses_ps() -> None:
    ps = subprocess.CompletedProcess([], 0, stdout="    1\n  420\n 9001\n")
    with patch.object(_process.os.path, "isdir", side_effect=_no_proc), \
            patch.object(_process.subprocess, "run", return_value=ps) as run:
        assert _process.all_pids() == [1, 420, 9001]
    assert run.call_args.args[0] == ["ps", "-A", "-o", "pid="]


def test_all_pids_includes_self() -> None:
    assert os.getpid() in _process.all_pids()


@pytest.mark.parametrize(("command", "expected"), [
    ("/usr/bin/python3 /home/alice/.local/bin/clerk-daemon -d\n", True),
    ("/usr/bin/vim notes.txt\n", False),
])
def test_daemon_check_without_proc_reads_ps(command: str, expected: bool) -> None:
    ps = subprocess.CompletedProcess([], 0, stdout=command)
    with patch.object(_process, "is_pid_alive", return_value=True), \
            patch.object(_process.sys, "platform", "darwin"), \
            patch("builtins.open", side_effect=FileNotFoundError), \
            patch.object(_process.subprocess, "run", return_value=ps):
        assert _process.is_clerk_daemon_process(4242) is expected


def test_daemon_check_falls_back_to_alive_when_ps_fails() -> None:
    with patch.object(_process, "is_pid_alive", return_value=True), \
            patch.object(_process.sys, "platform", "darwin"), \
            patch("builtins.open", side_effect=FileNotFoundError), \
            patch.object(_process.subprocess, "run", side_effect=OSError):
        assert _process.is_clerk_daemon_process(4242) is True


@pytest.mark.parametrize(("key", "resolvable"), [("f23", False), ("f13", True), ("alt_r", True)])
def test_ptt_key_on_mac(key: str, resolvable: bool) -> None:
    from shadow_clerk import _daemon_recorder_command as mod
    if not mod._HAS_PYNPUT:
        pytest.skip("pynput がない")
    with patch.object(mod.sys, "platform", "darwin"):
        assert (_RecorderCommandMixin._resolve_pynput_key(object(), key) is not None) is resolvable
