"""测试专用的可控 LLM 与技能，用来精确构造 Agent 主循环的各种分支。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from agent.llm import BaseLLM, Delta, LLMError
from skills.base import BaseSkill, SkillParam, SkillResult


class ScriptedLLM(BaseLLM):
    """按脚本逐轮吐事件，用来验证事件顺序、并行工具、超时、错误路径。"""

    def __init__(self, script: list[list[Delta]]) -> None:
        self.script = script
        self.calls = 0
        self.tools_supported = True
        self.on_retry = None

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Delta]:
        step = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        for delta in step:
            if isinstance(delta, Exception):
                raise delta
            yield delta

    async def complete(self, messages: list[dict[str, Any]], *, max_tokens: int = 256) -> str:
        return "摘要"


def text_step(*chunks: str) -> list[Delta]:
    deltas = [Delta(content=c) for c in chunks]
    deltas.append(Delta(finish_reason="stop"))
    return deltas


def tool_step(*calls: dict[str, Any]) -> list[Delta]:
    """构造一轮工具调用；``calls`` 每个元素形如 {"name": ..., "args": {...}}。"""
    deltas: list[Delta] = []
    for index, call in enumerate(calls):
        deltas.append(
            Delta(
                tool_call_index=index,
                tool_call_id=f"call_{index}",
                tool_call_name=call["name"],
                tool_call_args=json.dumps(call.get("args") or {}, ensure_ascii=False),
            )
        )
    deltas.append(Delta(finish_reason="tool_calls"))
    return deltas


class EchoSkill(BaseSkill):
    name = "echo"
    description = "原样返回传入文本"
    parameters = [SkillParam(name="text", type="string", description="文本", required=True)]

    async def execute(self, text: str, **kw: Any) -> SkillResult:  # type: ignore[override]
        return SkillResult(success=True, data=f"echo:{text}")


class StrictSkill(BaseSkill):
    """必填参 + enum，用来验证参数校验与纠错回喂。"""

    name = "strict"
    description = "严格参数校验"
    parameters = [
        SkillParam(name="mode", type="string", required=True, enum=["a", "b"]),
        SkillParam(name="count", type="integer", required=True, minimum=1, maximum=5),
    ]

    async def execute(self, mode: str, count: int, **kw: Any) -> SkillResult:  # type: ignore[override]
        return SkillResult(success=True, data=f"{mode}:{count}")


class SlowSkill(BaseSkill):
    name = "slow"
    description = "慢工具，验证单工具超时"

    async def execute(self, **kw: Any) -> SkillResult:  # type: ignore[override]
        await asyncio.sleep(1.5)
        return SkillResult(success=True, data="done")


class BoomSkill(BaseSkill):
    name = "boom"
    description = "总是抛异常，验证异常收敛"

    async def execute(self, **kw: Any) -> SkillResult:  # type: ignore[override]
        raise RuntimeError("炸了")


class RaisingLLM(BaseLLM):
    """第一轮就抛 LLMError，验证 Agent 兜底。"""

    def __init__(self) -> None:
        self.tools_supported = True
        self.on_retry = None

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Delta]:
        raise LLMError("429 too many requests", retryable=True, code="rate_limited")
        yield Delta()  # pragma: no cover - 让函数成为 async generator

    async def complete(self, messages: list[dict[str, Any]], *, max_tokens: int = 256) -> str:
        return ""
