"""Agent 主循环：流式对话 → 工具调用 → 再回到模型 → 产出答案。

与 v2 的关键差异：
1. **真正的 token 级流式**：v2 只在最后一次性推送 ``answer``，前端所谓"打字机"
   是假的。现在每个 delta 都会以 ``token`` 事件推给前端。
2. **并行工具调用**：模型一次返回多个 tool_call 时并发执行（``asyncio.gather``），
   每个工具单独超时，互不阻塞。
3. **参数校验回喂**：工具参数不合 schema 时，不再直接 TypeError，而是把
   "缺哪个参数、类型错在哪"作为工具结果回给模型，让它下一轮自我修正。
4. **结构化 trace**：每次 LLM/工具调用的耗时与状态入库，随答案一起返回。
5. **不向上抛异常**：任何 LLM 侧故障都转成 ``error`` 事件 + 兜底文案，
   WebSocket 不会因为一次 429 就静默断开。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from agent.llm import BaseLLM, LLMError, ToolsUnsupportedError, build_llm
from agent.memory import ConversationMemory, estimate_tokens, sanitize_assistant_tool_call
from agent.trace import AgentTrace, Status, elapsed_ms, stopwatch
from config import Settings, config
from skills.base import SkillResult
from skills.registry import SkillRegistry
from skills.registry import registry as default_registry

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], Awaitable[None]]

SYSTEM_PROMPT = (
    "You are a tool-using AI agent running inside a FastAPI service.\n"
    "Rules:\n"
    "1. Decide whether a tool is needed before answering; prefer tools over guessing.\n"
    "2. Call tools with arguments that exactly match their JSON schema.\n"
    "3. If a tool returns ERROR[invalid_arguments], fix the arguments and retry once.\n"
    "4. Never invent tool output; base your answer on the actual tool results.\n"
    "5. Answer in the user's language, use Markdown, keep it concise."
)

_NO_ANSWER = "抱歉，这一步没有产出有效回答。可以把问题拆得更具体一些再试一次。"
_MAX_STEPS = "已达到最大推理步数上限，先给出目前掌握的部分结论。"


class Agent:
    """单个会话的 Agent 实例。"""

    def __init__(
        self,
        system_prompt: str = "",
        *,
        memory: ConversationMemory | None = None,
        llm: BaseLLM | None = None,
        skills: SkillRegistry | None = None,
        settings: Settings | None = None,
    ):
        self.settings = settings or config
        self.memory = memory or ConversationMemory(system_prompt or SYSTEM_PROMPT)
        self.llm = llm or build_llm(self.settings)
        self.skills = skills or default_registry
        self.last_trace: AgentTrace | None = None
        self._on_stream: EventCallback | None = None
        self._active_cb: EventCallback | None = None

    # ---------------- 事件 ----------------
    def on_stream(self, callback: EventCallback | None) -> None:
        """设置默认回调（兼容 v2）。并发场景请用 ``run(..., on_event=cb)``。"""
        self._on_stream = callback

    async def _emit(self, event: str, data: dict[str, Any]) -> None:
        cb = self._active_cb or self._on_stream
        if cb is None:
            return
        try:
            await cb(event, data)
        except Exception:  # noqa: BLE001 - 前端断开不该中断推理
            logger.debug("stream callback failed", exc_info=True)

    # ---------------- 主流程 ----------------
    async def run(self, user_message: str, *, on_event: EventCallback | None = None) -> str:
        """跑一轮完整对话，返回最终答案文本（永不抛异常）。"""
        self._active_cb = on_event
        trace = AgentTrace()
        self.last_trace = trace
        memory = self.memory
        memory.add_user(user_message)
        await self._emit("thinking", {"status": "思考中…"})

        try:
            return await self._loop(trace)
        except ToolsUnsupportedError:
            logger.info("provider 不支持工具调用，降级为纯对话")
            return await self._loop(trace, tools_disabled=True)
        except LLMError as exc:
            logger.warning("LLM error: %s", exc)
            message = f"模型调用失败：{exc}"
            memory.add_assistant(message)
            await self._emit("error", {"message": message, "code": exc.code})
            return message
        except Exception as exc:  # noqa: BLE001 - 兜底，保证 WS 会话不炸
            logger.exception("agent loop crashed")
            message = f"内部错误：{type(exc).__name__}: {exc}"
            await self._emit("error", {"message": message, "code": "internal_error"})
            return message
        finally:
            self._active_cb = None

    async def _loop(self, trace: AgentTrace, *, tools_disabled: bool = False) -> str:
        memory = self.memory
        max_iter = self.settings.MAX_ITERATIONS

        for step in range(1, max_iter + 1):
            tools = [] if tools_disabled else self.skills.get_openai_tools()
            messages = memory.get_messages()
            started = stopwatch()
            content_parts: list[str] = []
            tool_calls: dict[int, dict[str, Any]] = {}
            finish_reason: str | None = None

            async for delta in self.llm.stream(messages, tools or None):
                if delta.content:
                    content_parts.append(delta.content)
                    await self._emit("token", {"delta": delta.content})
                if delta.has_tool_call:
                    slot = tool_calls.setdefault(
                        delta.tool_call_index or 0,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    if delta.tool_call_id:
                        slot["id"] = delta.tool_call_id
                    if delta.tool_call_name:
                        slot["name"] = delta.tool_call_name
                    if delta.tool_call_args:
                        slot["arguments"] += delta.tool_call_args
                if delta.finish_reason:
                    finish_reason = delta.finish_reason
                if delta.usage:
                    trace.record_usage(delta.usage.get("prompt_tokens", 0), delta.usage.get("completion_tokens", 0))

            text = "".join(content_parts)
            trace.add(
                "llm",
                self.settings.AGENT_MODEL,
                elapsed_ms(started),
                step=step,
                has_tool_calls=bool(tool_calls),
                finish_reason=finish_reason,
                chars=len(text),
                tokens=estimate_tokens(text),
            )

            if not tool_calls:
                if not text.strip():
                    text = _NO_ANSWER
                memory.add_assistant(text)
                await self._summarize(trace)
                await self._emit("answer", {"content": text, "trace": trace.to_dict()})
                return text

            # 有工具调用：先落 assistant(tool_calls)，再执行
            assistant_msg = sanitize_assistant_tool_call(
                text or None,
                [
                    {"id": v["id"] or f"call_{i}", "function": {"name": v["name"], "arguments": v["arguments"]}}
                    for i, v in tool_calls.items()
                ],
            )
            memory.add_message(assistant_msg)
            results = await self._execute_tools(tool_calls, trace)
            for call_id, content in results:
                memory.add_tool_result(call_id, content)

            await self._emit("thinking", {"status": "整理工具结果…"})

        memory.add_assistant(_MAX_STEPS)
        await self._emit("answer", {"content": _MAX_STEPS, "trace": trace.to_dict()})
        return _MAX_STEPS

    # ---------------- 工具执行 ----------------
    async def _execute_tools(
        self, tool_calls: dict[int, dict[str, Any]], trace: AgentTrace
    ) -> list[tuple[str, str]]:
        items = sorted(tool_calls.items())
        if self.settings.PARALLEL_TOOL_CALLS and len(items) > 1:
            results = await asyncio.gather(*[self._run_tool(i, call, trace) for i, call in items])
        else:
            results = [await self._run_tool(i, call, trace) for i, call in items]
        return list(results)

    async def _run_tool(self, index: int, call: dict[str, Any], trace: AgentTrace) -> tuple[str, str]:
        call_id = call["id"] or f"call_{index}"
        name = call["name"]
        raw_args = call["arguments"] or "{}"
        try:
            parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            parsed = {}

        await self._emit("tool_call", {"name": name, "args": parsed, "status": "running"})
        started = stopwatch()
        skill = self.skills.get(name)
        if skill is None:
            content = f"ERROR[unknown_tool]: 没有名为 {name} 的工具，可用工具：{', '.join(self.skills.names())}"
            trace.add("tool", name, elapsed_ms(started), "error", error="unknown_tool")
            await self._emit("tool_result", {"name": name, "data": content, "status": "error"})
            return call_id, content

        try:
            result: SkillResult = await asyncio.wait_for(skill(**parsed), timeout=self.settings.TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            content = f"ERROR[timeout]: 工具 {name} 超过 {self.settings.TOOL_TIMEOUT:g}s 未返回，已中止"
            trace.add("tool", name, elapsed_ms(started), "timeout", args=parsed)
            await self._emit("tool_result", {"name": name, "data": content, "status": "timeout"})
            return call_id, content

        duration = elapsed_ms(started)
        status: Status = "ok" if result.success else "error"
        content = result.as_tool_content()
        trace.add(
            "tool",
            name,
            duration,
            status,
            args=parsed,
            error=result.error,
            error_code=result.metadata.get("error_code"),
        )
        await self._emit(
            "tool_result",
            {"name": name, "data": content[:500], "status": status, "duration_ms": duration},
        )
        return call_id, content

    # ---------------- 其它 ----------------
    async def _summarize(self, trace: AgentTrace) -> None:
        try:
            await self.memory.maybe_summarize(
                lambda msgs: self.llm.complete(msgs, max_tokens=256)  # type: ignore[arg-type]
            )
        except Exception:  # noqa: BLE001 - 摘要失败不影响主答案
            logger.debug("summarize failed", exc_info=True)

    def clear_memory(self) -> None:
        self.memory.clear()

    def reset_trace(self) -> None:
        self.last_trace = None


__all__ = ["Agent", "SYSTEM_PROMPT"]
