"""A1：配置类型化、边界校验、旧属性兼容、密钥不外泄。"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from config import Settings


def test_defaults_keep_v2_attribute_names() -> None:
    s = Settings(_env_file=None)
    for attr in (
        "OPENAI_API_KEY",
        "API_BASE_URL",
        "AGENT_MODEL",
        "AGENT_TEMPERATURE",
        "HOST",
        "PORT",
        "SERPER_API_KEY",
        "CODE_EXEC_TIMEOUT",
        "MAX_ITERATIONS",
        "MAX_TOKENS",
        "MEMORY_SUMMARY_THRESHOLD",
        "REQUEST_TIMEOUT",
    ):
        assert hasattr(s, attr), attr
    assert s.MAX_ITERATIONS == 10
    assert s.PORT == 8000


def test_invalid_port_raises_at_init() -> None:
    with pytest.raises(ValidationError):
        Settings(PORT="abc")
    with pytest.raises(ValidationError):
        Settings(PORT=70000)


def test_invalid_log_level_raises() -> None:
    with pytest.raises(ValidationError):
        Settings(LOG_LEVEL="verbose")
    assert Settings(LOG_LEVEL="debug").LOG_LEVEL == "DEBUG"


def test_use_mock_when_no_key() -> None:
    assert Settings(OPENAI_API_KEY="", MOCK_LLM=False).use_mock is True
    assert Settings(OPENAI_API_KEY="sk-x", MOCK_LLM=False).use_mock is False
    assert Settings(OPENAI_API_KEY="sk-x", MOCK_LLM=True).use_mock is True


def test_public_dict_never_leaks_key() -> None:
    s = Settings(OPENAI_API_KEY="sk-super-secret")
    payload = json.dumps(s.public_dict(), ensure_ascii=False)
    assert "sk-super-secret" not in payload
    assert s.public_dict()["has_api_key"] is True


def test_update_validates_base_url_and_model() -> None:
    s = Settings(OPENAI_API_KEY="")
    with pytest.raises(ValueError):
        s.update(base_url="ftp://evil.example.com")
    with pytest.raises(ValueError):
        s.update(model="   ")
    s.update(base_url="https://api.example.com/v1/", model="qwen-plus")
    assert s.API_BASE_URL == "https://api.example.com/v1"
    assert s.AGENT_MODEL == "qwen-plus"


def test_cors_origins_and_session_path() -> None:
    s = Settings(CORS_ORIGINS="http://a, http://b ,", DATA_DIR="/tmp/x")
    assert s.cors_origins == ["http://a", "http://b"]
    assert str(s.session_db_path).endswith("sessions.db")


def test_runtime_config_is_off_by_default() -> None:
    s = Settings(_env_file=None)
    assert s.ALLOW_RUNTIME_CONFIG is False
    assert s.ADMIN_TOKEN == ""
