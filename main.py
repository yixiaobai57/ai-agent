"""FastAPI 入口：应用工厂 + 生命周期 + 静态资源托管。

v2 的 main.py 把路由、鉴权、会话字典、静态托管全塞在一个文件里，
``registry.discover()`` 在 import 期执行，``sessions`` 是无界 dict，
``uvicorn.run(..., reload=True)`` 写死在 ``__main__``。
现在拆成 ``create_app()``，便于测试注入 settings / 会话后端，
并用 lifespan 统一管理启动与释放（测试里也能拿到 app.state）。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router, ws_chat_endpoint
from config import Settings, config
from sessions.store import SessionStore, create_session_store
from skills.registry import registry
from workflows.engine import workflow_engine

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
VERSION = "3.0.0"


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s - %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings.LOG_LEVEL)
    registry.discover()
    app.state.sessions = app.state.session_store_factory(settings)
    logger.info(
        "启动完成：model=%s mock=%s skills=%d workflows=%d sessions=%s",
        settings.AGENT_MODEL,
        settings.use_mock,
        len(registry.get_all()),
        len(workflow_engine.list_workflows()),
        settings.SESSION_BACKEND,
    )
    try:
        yield
    finally:
        app.state.sessions.close()
        logger.info("已释放会话后端")


def create_app(
    settings: Settings | None = None,
    *,
    session_store: SessionStore | None = None,
    session_store_factory: Any = None,
) -> FastAPI:
    settings = settings or config
    app = FastAPI(
        title="AI Agent Backend",
        version=VERSION,
        description="可插拔的多模型 AI Agent：流式输出、工具调用、工作流编排。",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.session_store_factory = session_store_factory or (
        (lambda s: session_store) if session_store is not None else create_session_store
    )

    # ---- CORS：白名单化。``*`` + credentials 是非法组合，浏览器会直接拒绝 ----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Admin-Token", "X-Request-ID"],
    )

    # ---- 请求大小与耗时日志 ----
    @app.middleware("http")
    async def _observe(request: Request, call_next: Any) -> Any:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.MAX_REQUEST_BYTES:
            return JSONResponse(
                status_code=413,
                content={"error_code": "payload_too_large", "message": "请求体过大"},
            )
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "%s %s -> %s (%.1fms) rid=%s",
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
            request_id,
        )
        return response

    # ---- 统一错误体：{error_code, message} ----
    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        return JSONResponse(
            status_code=422,
            content={
                "error_code": "invalid_request",
                "message": f"{loc}: {first.get('msg', '请求参数不合法')}",
            },
        )

    @app.exception_handler(HTTPException)
    async def _http_handler(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict):
            body = {
                "error_code": detail.get("error_code", "http_error"),
                "message": detail.get("message", ""),
            }
        else:
            body = {"error_code": "http_error", "message": str(detail)}
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未捕获异常：%s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error_code": "internal_error", "message": "服务内部错误，请查看服务端日志"},
        )

    # ---- 路由 ----
    app.include_router(router)
    app.add_api_websocket_route("/ws/chat", ws_chat_endpoint)

    # ---- 前端构建产物（可选）----
    if FRONTEND_DIST.exists():
        assets = FRONTEND_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> Any:
        idx = FRONTEND_DIST / "index.html"
        if idx.exists():
            return FileResponse(idx)
        return {
            "name": "AI Agent Backend",
            "version": VERSION,
            "docs": "/docs",
            "mock_mode": settings.use_mock,
            "frontend": "run `cd frontend && npm run dev`，或 `npm run build` 后由本服务托管",
        }

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon() -> Any:
        icon = FRONTEND_DIST / "favicon.svg"
        if icon.exists():
            return FileResponse(icon)
        return JSONResponse(status_code=404, content={"error_code": "not_found", "message": "no favicon"})

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = config
    print("=" * 56)
    print(f"AI Agent Backend v{VERSION}")
    print(f"  Model:     {settings.AGENT_MODEL}{'  (Mock 模式，无需 API Key)' if settings.use_mock else ''}")
    print(f"  API:       {settings.API_BASE_URL}")
    print(f"  Skills:    {len(registry.get_all()) if registry else 0} (startup 时自动发现)")
    print(f"  Sessions:  {settings.SESSION_BACKEND}")
    print(f"  Docs:      http://localhost:{settings.PORT}/docs")
    if FRONTEND_DIST.exists():
        print(f"  Frontend:  http://localhost:{settings.PORT}/  (built)")
    else:
        print("  Frontend:  http://localhost:5173/  (dev: cd frontend && npm run dev)")
    print("=" * 56)
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
    )


if __name__ == "__main__":
    main()
