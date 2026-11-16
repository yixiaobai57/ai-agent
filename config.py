"""集中配置层。

设计要点：
1. 用 pydantic-settings 做类型化 + 边界校验，非法值在进程启动时就会报错，
   而不是等到某次请求才炸出 ``int('abc')`` 之类的运行期异常。
2. 保留 v2 时代的属性名（``config.AGENT_MODEL``、``config.API_BASE_URL`` ...），
   老代码与外部脚本无需改动即可升级。
3. 运行期修改配置默认关闭（``ALLOW_RUNTIME_CONFIG=False``）。v2 的
   ``POST /api/config`` 无鉴权且能改写 ``base_url``，等于允许任何人把
   API Key 转发到他自己的服务器；现在必须显式开启并携带管理员令牌。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """全部配置项。字段名即环境变量名（大小写不敏感）。"""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- LLM ----------
    OPENAI_API_KEY: str = ""
    API_BASE_URL: str = "https://api.deepseek.com/v1"
    AGENT_MODEL: str = "deepseek-chat"
    AGENT_TEMPERATURE: float = Field(default=0.7, ge=0.0, le=2.0)
    MAX_TOKENS: int = Field(default=4096, ge=1, le=200_000)
    REQUEST_TIMEOUT: float = Field(default=120.0, gt=0)
    # 无 Key 或显式打开时，走确定性 Mock Provider，便于零成本演示与离线测试
    MOCK_LLM: bool = False
    # Mock 模式每个 chunk 的间隔秒数；>0 时前端能看到打字机效果（演示用，默认为 0 保持测试最快）
    MOCK_LATENCY: float = Field(default=0.0, ge=0.0, le=2.0)

    # ---------- Agent 循环 ----------
    MAX_ITERATIONS: int = Field(default=10, ge=1, le=50)
    MAX_RETRIES: int = Field(default=3, ge=1, le=10)
    RETRY_BACKOFF: float = Field(default=1.5, ge=1.0, le=10.0)
    MEMORY_SUMMARY_THRESHOLD: int = Field(default=20, ge=2)
    MEMORY_MAX_TURNS: int = Field(default=20, ge=1)
    MEMORY_TOKEN_BUDGET: int = Field(default=12_000, ge=512)
    PARALLEL_TOOL_CALLS: bool = True

    # ---------- 工具 ----------
    TOOL_TIMEOUT: float = Field(default=30.0, gt=0)
    SERPER_API_KEY: str = ""
    CODE_EXEC_TIMEOUT: float = Field(default=10.0, gt=0, le=120)
    ENABLE_CODE_EXEC: bool = True
    FILE_OPS_MAX_CHARS: int = Field(default=5000, ge=100)
    FILE_OPS_MAX_BYTES: int = Field(default=1_000_000, ge=1024)

    # ---------- 工作目录 ----------
    WORKSPACE_DIR: Path = BASE_DIR / "workspace"
    DATA_DIR: Path = BASE_DIR / "data"

    # ---------- 会话 ----------
    SESSION_BACKEND: Literal["memory", "sqlite"] = "sqlite"
    SESSION_DB_PATH: Path | None = None
    SESSION_TTL: int = Field(default=3600, ge=0)
    MAX_SESSIONS: int = Field(default=500, ge=1)

    # ---------- 服务 ----------
    HOST: str = "0.0.0.0"
    PORT: int = Field(default=8000, ge=1, le=65535)
    RELOAD: bool = False
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )
    MAX_REQUEST_BYTES: int = Field(default=256_000, ge=1024)

    # ---------- 运行期改写（默认关闭）----------
    ALLOW_RUNTIME_CONFIG: bool = False
    ADMIN_TOKEN: str = ""

    @field_validator("HOST", mode="before")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not str(v).strip():
            raise ValueError("HOST 不能为空")
        return str(v).strip()

    @field_validator("LOG_LEVEL")
    @classmethod
    def _valid_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed:
            raise ValueError(f"LOG_LEVEL 必须是 {sorted(allowed)} 之一")
        return v.upper()

    # ---------- 派生属性 ----------
    @property
    def use_mock(self) -> bool:
        """没有 Key 时自动降级为 Mock，保证 clone 下来就能跑。"""
        return bool(self.MOCK_LLM) or not bool(self.OPENAI_API_KEY.strip())

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def session_db_path(self) -> Path:
        return Path(self.SESSION_DB_PATH) if self.SESSION_DB_PATH else Path(self.DATA_DIR) / "sessions.db"

    def public_dict(self) -> dict[str, Any]:
        """给前端看的配置，绝不回显 API Key。"""
        return {
            "model": self.AGENT_MODEL,
            "base_url": self.API_BASE_URL,
            "has_api_key": bool(self.OPENAI_API_KEY.strip()),
            "mock": self.use_mock,
            "timeout": self.REQUEST_TIMEOUT,
            "max_iterations": self.MAX_ITERATIONS,
            "allow_runtime_config": self.ALLOW_RUNTIME_CONFIG,
        }

    def update(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        """运行期改写（仅在被 ``ALLOW_RUNTIME_CONFIG`` 放行后调用）。

        走一遍校验，避免把 ``base_url`` 改成脏协议。
        """
        if api_key is not None:
            self.OPENAI_API_KEY = api_key.strip()
        if base_url is not None:
            candidate = base_url.strip().rstrip("/")
            if not candidate.startswith(("http://", "https://")):
                raise ValueError("base_url 必须以 http:// 或 https:// 开头")
            self.API_BASE_URL = candidate
        if model is not None:
            if not model.strip():
                raise ValueError("model 不能为空")
            self.AGENT_MODEL = model.strip()


config = Settings()


def reload_config() -> Settings:
    """测试用：重新从环境变量构造一份配置。"""
    global config
    config = Settings()
    return config


__all__ = ["Settings", "config", "reload_config", "BASE_DIR"]
