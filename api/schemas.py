"""HTTP 请求 / 响应模型。

v2 的 ``ChatReq`` 没有任何约束：``message`` 可以是空字符串，``session_id`` 可以是
任意串（包括 ``../../`` 或超长字符串），这些都直接进到会话字典和 LLM 上下文里。
这里统一长度与字符集约束，非法输入在进入业务逻辑前就被 422 拦下。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

SESSION_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class ChatReq(BaseModel):
    message: str = Field(min_length=1, max_length=20_000, description="用户本轮输入")
    session_id: str = Field(default="default", pattern=SESSION_PATTERN, description="会话 ID")


class SessionDeleteReq(BaseModel):
    """清空会话：v2 用 ``ChatReq``，但清空并不需要 message，这里放开为可选。"""

    session_id: str = Field(default="default", pattern=SESSION_PATTERN)
    message: str | None = Field(default=None, max_length=20_000)


class ChatResp(BaseModel):
    response: str
    session_id: str
    trace: dict[str, Any] | None = None


class ConfigReq(BaseModel):
    api_key: str | None = Field(default=None, max_length=512)
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)


class ConfigResp(BaseModel):
    status: str = "ok"
    model: str
    base_url: str
    mock: bool = False
    allow_runtime_config: bool = False


class SessionNewResp(BaseModel):
    session_id: str


class StatusResp(BaseModel):
    status: str = "ok"


class ErrorResp(BaseModel):
    error_code: str
    message: str


class SkillInfo(BaseModel):
    name: str
    description: str = ""
    enabled: bool = True
    dangerous: bool = False
    requires: str | None = None
    available: bool = True


__all__ = [
    "ChatReq",
    "ChatResp",
    "SessionDeleteReq",
    "ConfigReq",
    "ConfigResp",
    "SessionNewResp",
    "StatusResp",
    "ErrorResp",
    "SkillInfo",
    "SESSION_PATTERN",
]
