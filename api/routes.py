"""HTTP / WebSocket 路由。

对外契约（保持 v2 兼容，前端与老脚本无需改动）：
    GET  /health
    GET  /api/skills
    GET  /api/workflows
    GET  /api/config
    POST /api/config          ← 需要 ALLOW_RUNTIME_CONFIG + ADMIN_TOKEN
    POST /api/session/new
    DELETE /api/session
    POST /api/chat
    WS   /ws/chat
新增：
    GET  /api/health          ← /health 的别名，便于网关统一探活
    GET  /api/stats           ← 会话数 / 技能数 / 是否 Mock
    POST /api/chat/stream     ← SSE 流式（无 WebSocket 的客户端也能吃到 token 流）
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from api.deps import get_settings, get_store, require_admin
from api.schemas import ChatReq, ChatResp, ConfigReq, ConfigResp, SessionDeleteReq, SessionNewResp, StatusResp
from config import Settings
from sessions.store import SessionStore
from skills.registry import registry
from workflows.engine import workflow_engine

logger = logging.getLogger(__name__)

router = APIRouter()


# --------------------------------------------------------------------------- #
# 元信息
# --------------------------------------------------------------------------- #
@router.get("/health", tags=["meta"])
@router.get("/api/health", tags=["meta"])
async def health(request: Request) -> dict[str, Any]:
    settings: Settings = get_settings(request)
    return {
        "status": "ok",
        "model": settings.AGENT_MODEL,
        "base_url": settings.API_BASE_URL,
        "mock": settings.use_mock,
        "skills": len(registry.get_all()),
        "workflows": len(workflow_engine.list_workflows()),
    }


@router.get("/api/skills", tags=["meta"])
async def list_skills() -> dict[str, Any]:
    return {"skills": registry.list_skills()}


@router.get("/api/workflows", tags=["meta"])
async def list_workflows() -> dict[str, Any]:
    return {"workflows": workflow_engine.describe()}


@router.get("/api/stats", tags=["meta"])
async def stats(request: Request) -> dict[str, Any]:
    store: SessionStore = get_store(request)
    settings: Settings = get_settings(request)
    return {
        "sessions": store.count(),
        "skills": len(registry.get_all()),
        "workflows": len(workflow_engine.list_workflows()),
        "mock": settings.use_mock,
        "session_backend": settings.SESSION_BACKEND,
    }


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
@router.get("/api/config", tags=["config"])
async def read_config(request: Request) -> dict[str, Any]:
    settings: Settings = get_settings(request)
    data = settings.public_dict()
    return data


@router.post("/api/config", response_model=ConfigResp, tags=["config"], dependencies=[Depends(require_admin)])
async def update_config(req: ConfigReq, request: Request) -> ConfigResp:
    settings: Settings = get_settings(request)
    try:
        settings.update(api_key=req.api_key, base_url=req.base_url, model=req.model)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error_code": "invalid_config", "message": str(exc)}) from exc
    get_store(request).refresh_clients()
    logger.info("运行期配置已更新：model=%s", settings.AGENT_MODEL)
    return ConfigResp(
        model=settings.AGENT_MODEL,
        base_url=settings.API_BASE_URL,
        mock=settings.use_mock,
        allow_runtime_config=settings.ALLOW_RUNTIME_CONFIG,
    )


# --------------------------------------------------------------------------- #
# 会话
# --------------------------------------------------------------------------- #
@router.post("/api/session/new", response_model=SessionNewResp, tags=["session"])
async def new_session(request: Request) -> SessionNewResp:
    sid = uuid.uuid4().hex[:8]
    get_store(request).get_or_create(sid)
    return SessionNewResp(session_id=sid)


@router.delete("/api/session", response_model=StatusResp, tags=["session"])
async def clear_session(req: SessionDeleteReq, request: Request) -> StatusResp:
    store: SessionStore = get_store(request)
    agent = store.get(req.session_id)
    if agent is not None:
        agent.clear_memory()
        store.save(req.session_id, agent)
    return StatusResp(status="cleared")


# --------------------------------------------------------------------------- #
# 对话（同步）
# --------------------------------------------------------------------------- #
@router.post("/api/chat", response_model=ChatResp, tags=["chat"])
async def chat(req: ChatReq, request: Request) -> ChatResp:
    store: SessionStore = get_store(request)
    agent = store.get_or_create(req.session_id)
    answer = await agent.run(req.message)
    store.save(req.session_id, agent)
    trace = agent.last_trace.to_dict() if agent.last_trace else None
    return ChatResp(response=answer, session_id=req.session_id, trace=trace)


# --------------------------------------------------------------------------- #
# 对话（SSE 流式）
# --------------------------------------------------------------------------- #
@router.post("/api/chat/stream", tags=["chat"])
async def chat_stream(req: ChatReq, request: Request) -> StreamingResponse:
    store: SessionStore = get_store(request)
    agent = store.get_or_create(req.session_id)
    queue: asyncio.Queue[tuple[str | None, dict[str, Any] | None]] = asyncio.Queue()

    async def on_event(event: str, data: dict[str, Any]) -> None:
        await queue.put((event, data))

    async def runner() -> None:
        try:
            await agent.run(req.message, on_event=on_event)
        except Exception as exc:  # noqa: BLE001 - 兜底，保证 SSE 一定能收尾
            await queue.put(("error", {"message": f"{type(exc).__name__}: {exc}", "code": "internal_error"}))
        finally:
            store.save(req.session_id, agent)
            await queue.put((None, None))

    task = asyncio.create_task(runner())

    async def event_source() -> AsyncIterator[str]:
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if event is None:
                    break
                payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
async def ws_chat_endpoint(websocket: WebSocket) -> None:
    """``/ws/chat`` 的处理函数（由 main.py 注册）。

    与 v2 的差异：
    - 每轮把回调作为 ``run(on_event=...)`` 传入，而不是写在 Agent 实例上，
      同一个会话两个标签页同时对话时不会互相抢回调；
    - 事件带 ``session_id``，前端可多会话并行；
    - 心跳帧（``{"event":"ping"}``）不会打断推理。
    """
    await websocket.accept()
    store: SessionStore = websocket.app.state.sessions
    sid = "default"

    async def send_event(event: str, data: dict[str, Any]) -> None:
        await websocket.send_text(json.dumps({"event": event, "data": data}, ensure_ascii=False))

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"message": raw}
            if payload.get("event") == "ping":
                await send_event("pong", {})
                continue
            try:
                req = ChatReq(
                    message=payload.get("message", ""),
                    # 前端首次连接时可能还没分配会话 id，null/空串都回落到连接级默认值
                    session_id=payload.get("session_id") or sid,
                )
            except ValidationError as exc:
                await send_event("error", {"message": f"请求不合法：{exc.errors()[0]['msg']}", "code": "invalid_request"})
                continue
            sid = req.session_id
            agent = store.get_or_create(sid)
            await agent.run(req.message, on_event=send_event)
            store.save(sid, agent)
    except WebSocketDisconnect:
        logger.info("WS 断开：session=%s", sid)
    except Exception as exc:  # noqa: BLE001 - 单连接异常不该影响服务
        logger.warning("WS 异常（session=%s）：%s", sid, exc)


__all__ = ["router", "ws_chat_endpoint"]
