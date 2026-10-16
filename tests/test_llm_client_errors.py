"""llm_client の設定不足は sys.exit ではなく LlmClientError で伝える（daemon のスレッドから呼べるように）"""
from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("SHADOW_CLERK_DATA_DIR", tempfile.mkdtemp(prefix="shadow-clerk-llm-"))

from shadow_clerk import _llm_config  # noqa: E402
from shadow_clerk._llm_config import LlmClientError, get_api_client  # noqa: E402


def test_missing_endpoint_raises() -> None:
    with pytest.raises(LlmClientError):
        get_api_client({"api_endpoint": "", "api_model": "m"})


def test_missing_model_raises() -> None:
    with pytest.raises(LlmClientError):
        get_api_client({"api_endpoint": "http://localhost:1", "api_model": ""})


def test_missing_api_key_env_raises(monkeypatch) -> None:
    monkeypatch.delenv("SHADOW_CLERK_TEST_KEY", raising=False)
    with pytest.raises(LlmClientError) as e:
        get_api_client({"api_endpoint": "http://localhost:1", "api_model": "m", "api_key_env": "SHADOW_CLERK_TEST_KEY"})
    assert "SHADOW_CLERK_TEST_KEY" in str(e.value)


def test_main_turns_error_into_exit_code(monkeypatch, capsys) -> None:
    from shadow_clerk import llm_client
    monkeypatch.setattr(llm_client, "load_config", lambda: {"api_endpoint": "", "api_model": ""})
    monkeypatch.setattr("sys.argv", ["llm_client", "query", "hi"])
    with pytest.raises(SystemExit) as e:
        llm_client.main()
    assert e.value.code == 1 and capsys.readouterr().err.strip()
