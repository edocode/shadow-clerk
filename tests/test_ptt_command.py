"""PTT の定型コマンドは API 障害時もローカルで実行する。"""
from __future__ import annotations

import re
import json
import subprocess

import pytest
from unittest.mock import Mock, patch

from shadow_clerk._daemon_recorder_command import _RecorderCommandMixin


class Host(_RecorderCommandMixin):
    def __init__(self) -> None:
        self._custom_commands = [(re.compile("テスト実行"), "echo test")]
        self.executed: list[str] = []

    def _execute_command(self, command: str) -> None:
        self.executed.append(command)


def test_known_commands_skip_unavailable_api() -> None:
    for method in ("_llm_match_and_execute", "_spell_and_match"):
        for text, expected in (("会議開始", "start_meeting"),
                               ("翻訳停止", "translate_stop"),
                               ("テスト実行", "custom_exec echo test")):
            host = Host()
            with patch("shadow_clerk._daemon_recorder_command.load_config", return_value={"api_endpoint": "https://example.invalid"}), patch(
                "shadow_clerk._daemon_recorder_command.subprocess.run", side_effect=AssertionError("API must not be called")
            ):
                getattr(host, method)(text)
            assert host.executed == [expected]


def test_unknown_text_still_uses_api() -> None:
    host = Host()
    with patch("shadow_clerk._daemon_recorder_command.subprocess.run") as run:
        run.return_value.returncode = 1
        run.return_value.stderr = "502"
        host._llm_match_and_execute("何か質問です")
    run.assert_called_once()
    assert host.executed == []


def test_local_match_does_not_turn_unknown_text_into_query() -> None:
    host = Host()
    with patch("shadow_clerk._daemon_recorder_command.load_config", return_value={"api_endpoint": "https://example.invalid"}):
        assert not host._execute_local_command("何か質問です")
        assert host._match_command_body("何か質問です") == "llm_query 何か質問です"
    assert host.executed == []


@pytest.mark.parametrize("failure", ["exit", "timeout", "json", "exception"])
def test_api_errors_notify_dashboard(failure: str) -> None:
    host = Host()
    host._file_watcher = Mock()
    with patch("shadow_clerk._daemon_recorder_command.subprocess.run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "invalid json"
        if failure == "exit":
            run.return_value.returncode = 1
            run.return_value.stderr = "502"
        elif failure == "timeout":
            run.side_effect = subprocess.TimeoutExpired("match-command", 30)
        elif failure == "exception":
            run.side_effect = OSError("unavailable")
        host._llm_match_and_execute("何か質問です")
    event, data = host._file_watcher._broadcast.call_args.args
    assert event == "alert"
    payload = json.loads(data)
    assert payload["kind"] == "command_api_error"
    assert "何か質問です" in payload["message"]
    assert "502" not in payload["message"]
    assert host.executed == []
