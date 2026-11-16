"""联网搜索技能：通过 Serper Google Search API 检索网页。

未配置 ``SERPER_API_KEY`` 时返回 Mock 结果（并在 metadata 里标 ``mock=True``），
保证 clone 下来零配置即可跑通"有工具调用"的完整链路。

相比 v2：
- 超时/HTTP 错误被转成可读的 ``SkillResult``，不再抛异常穿透到 Agent；
- 结果条数做边界收敛（1~10），防止模型传 ``num_results=1000`` 打爆上游；
- 单条结果裁剪长度，避免 10 条长摘要撑爆上下文；
- 返回值带 ``count`` / ``mock`` 元信息，便于前端与 trace 观测。
"""

from __future__ import annotations

from typing import Any

import httpx

from config import config
from skills import BaseSkill, SkillParam, SkillResult, registry

SERPER_ENDPOINT = "https://google.serper.dev/search"
MAX_SNIPPET_CHARS = 500


@registry.register
class SearchWebSkill(BaseSkill):
    name = "search_web"
    description = "用 Google 搜索互联网，返回标题、摘要与链接。"
    requires = "SERPER_API_KEY"
    parameters = [
        SkillParam(name="query", type="string", description="搜索关键词", required=True),
        SkillParam(
            name="num_results",
            type="integer",
            description="返回条数（1-10，默认 5）",
            required=False,
            default=5,
            minimum=1,
            maximum=10,
        ),
    ]

    async def execute(self, query: str, num_results: int = 5, **kw: Any) -> SkillResult:  # type: ignore[override]
        num = max(1, min(int(num_results or 5), 10))
        api_key = (config.SERPER_API_KEY or "").strip()
        if not api_key:
            return SkillResult(
                success=True,
                data=(
                    f"[Mock 搜索结果] query={query!r}\n"
                    f"1. {query} 的官方文档\n"
                    f"2. {query} 的最新讨论\n"
                    f"3. {query} 实践指南\n"
                    "（设置 SERPER_API_KEY 后返回真实结果）"
                ),
                metadata={"mock": True, "count": 3, "query": query},
            )

        payload = {"q": query, "num": num}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    SERPER_ENDPOINT,
                    headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                    json=payload,
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()
        except httpx.TimeoutException:
            return SkillResult(
                success=False,
                error="搜索请求超时（10s）",
                metadata={"error_code": "timeout", "query": query},
            )
        except httpx.HTTPStatusError as exc:
            return SkillResult(
                success=False,
                error=f"搜索服务返回 {exc.response.status_code}",
                metadata={"error_code": "http_error", "status": exc.response.status_code},
            )
        except httpx.HTTPError as exc:
            return SkillResult(success=False, error=f"网络错误：{exc}", metadata={"error_code": "network_error"})

        organic: list[dict[str, Any]] = data.get("organic") or []
        lines = []
        for item in organic[:num]:
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or "").strip()[:MAX_SNIPPET_CHARS]
            link = str(item.get("link") or "").strip()
            lines.append(f"**{title}**\n{snippet}\n{link}")
        if not lines:
            return SkillResult(success=True, data="没有找到相关结果。", metadata={"mock": False, "count": 0})
        return SkillResult(
            success=True,
            data="\n\n".join(lines),
            metadata={"mock": False, "count": len(lines), "query": query},
        )


__all__ = ["SearchWebSkill"]
