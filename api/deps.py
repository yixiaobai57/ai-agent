"""FastAPI 依赖：从 ``app.state`` 取配置与会话仓库，并提供管理员鉴权。

为什么把鉴权放在依赖里：
v2 的 ``POST /api/config`` 任何人都能调，并且能改 ``base_url``——
攻击者只要让受害者点一下（或利用 ``CORS: *``），就能把 API Key 指到自己的服务器，
下一次对话 Key 就以 Bearer 头的形式发过去了。这是一个真实的凭据外泄路径。
现在该端点默认关闭，开启后必须携带 ``X-Admin-Token`` / ``Authorization: Bearer``。
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from config import Settings
from sessions.store import SessionStore


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_store(request: Request) -> SessionStore:
    return request.app.state.sessions


def _extract_token(request: Request) -> str | None:
    header = request.headers.get("x-admin-token")
    if header:
        return header.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


async def require_admin(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if not settings.ALLOW_RUNTIME_CONFIG:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "runtime_config_disabled",
                "message": "运行期修改配置已关闭（安全默认）。请改 .env 后重启，"
                "或设置 ALLOW_RUNTIME_CONFIG=true 且 ADMIN_TOKEN 后重试。",
            },
        )
    if not settings.ADMIN_TOKEN:
        raise HTTPException(
            status_code=403,
            detail={
                "error_code": "admin_token_missing",
                "message": "已开启运行期配置但未设置 ADMIN_TOKEN，拒绝写入。",
            },
        )
    token = _extract_token(request)
    if not token or not hmac.compare_digest(token, settings.ADMIN_TOKEN):
        raise HTTPException(
            status_code=401,
            detail={"error_code": "unauthorized", "message": "管理员令牌无效。"},
        )


__all__ = ["get_settings", "get_store", "require_admin"]
