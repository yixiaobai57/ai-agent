"""LLM 抽象层。

为什么单独抽一层：
- **流式**：OpenAI 兼容接口的 ``stream=True`` 会在每个 chunk 里给 ``delta``，
  工具调用参数也是分片到达的（``tool_calls[].function.arguments`` 增量拼接）。
  把这套解析逻辑塞在 Agent 主循环里会让主循环不可读，也不可测。
- **重试/退避**：网络抖动、429、5xx 是常态。只有"一个 token 都没吐出去"时才允许
  重试，否则会向用户重复输出内容。
- **Mock Provider**：没有 API Key 也能跑完整链路（含工具调用），
  这样 HR / 面试官 clone 下来执行 ``python main.py`` 就能看到效果，也让单测零网络。

对外只有两个入口：``stream()``（流式增量）与 ``complete()``（一次性补全，用于记忆摘要）。
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from config import Settings, config

Message = dict[str, Any]


# --------------------------------------------------------------------------- #
# 增量数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Delta:
    """一次流式增量。同一个 chunk 可能同时带正文与工具调用分片。"""

    content: str = ""
    tool_call_index: int | None = None
    tool_call_id: str | None = None
    tool_call_name: str | None = None
    tool_call_args: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] | None = None

    @property
    def has_tool_call(self) -> bool:
        return self.tool_call_index is not None or self.tool_call_name is not None


class LLMError(RuntimeError):
    """统一的模型调用错误，带可重试标记与错误码。"""

    def __init__(self, message: str, *, retryable: bool = False, code: str = "llm_error"):
        super().__init__(message)
        self.retryable = retryable
        self.code = code


class ToolsUnsupportedError(LLMError):
    """部分 OpenAI 兼容服务不支持 function calling，需要降级为纯对话。"""

    def __init__(self, message: str):
        super().__init__(message, retryable=False, code="tools_unsupported")


# --------------------------------------------------------------------------- #
# 基类
# --------------------------------------------------------------------------- #
class BaseLLM(ABC):
    tools_supported: bool = True
    on_retry: Callable[[int, str], None] | None = None

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Delta]:
        """产出增量。实现为 async generator。"""

    @abstractmethod
    async def complete(self, messages: list[Message], *, max_tokens: int = 256) -> str:
        """一次性补全（记忆摘要用）。"""


# --------------------------------------------------------------------------- #
# OpenAI 兼容实现
# --------------------------------------------------------------------------- #
_RETRYABLE_MARKERS = ("timeout", "timed out", "rate limit", "overloaded", "connection", "502", "503", "504")


def _classify(exc: Exception) -> LLMError:
    text = f"{type(exc).__name__}: {exc}"
    lowered = text.lower()
    retryable = any(m in lowered for m in _RETRYABLE_MARKERS)
    code = "rate_limited" if "rate" in lowered else ("timeout" if "time" in lowered else "llm_error")
    return LLMError(text, retryable=retryable, code=code)


def _looks_like_tool_rejection(exc: Exception) -> bool:
    lowered = f"{exc}".lower()
    if "stream_options" in lowered:
        return False
    keywords = ("tool", "function call", "functions", "tool_choice")
    return any(k in lowered for k in keywords) and any(
        w in lowered for w in ("support", "unsupported", "not allowed", "invalid", "400")
    )


class OpenAICompatLLM(BaseLLM):
    """面向 DeepSeek / Moonshot / Qwen / GLM / OpenAI 等 OpenAI 兼容端点。"""

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or config
        self._client = self._build_client()
        self.tools_supported = True
        self.on_retry = None

    def _build_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self._settings.OPENAI_API_KEY or "sk-mock",
            base_url=self._settings.API_BASE_URL,
            timeout=self._settings.REQUEST_TIMEOUT,
            max_retries=0,  # 重试由本层统一控制，避免双重放大
        )

    def refresh(self) -> None:
        """配置被运行期改写后重建连接。"""
        self._client = self._build_client()

    async def _open_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> Any:
        params: dict[str, Any] = {
            "model": self._settings.AGENT_MODEL,
            "messages": messages,
            "temperature": self._settings.AGENT_TEMPERATURE if temperature is None else temperature,
            "max_tokens": self._settings.MAX_TOKENS if max_tokens is None else max_tokens,
            "stream": True,
        }
        if tools and self.tools_supported:
            params["tools"] = tools
            params["tool_choice"] = "auto"
        try:
            params["stream_options"] = {"include_usage": True}
            return await self._client.chat.completions.create(**params)
        except Exception as exc:  # 少数服务不认 stream_options，去掉再试
            if "stream_options" not in f"{exc}".lower():
                raise
            params.pop("stream_options", None)
            return await self._client.chat.completions.create(**params)

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Delta]:
        attempt = 0
        emitted = False
        while True:
            try:
                stream = await self._open_stream(messages, tools, temperature, max_tokens)
                async for chunk in stream:
                    delta = self._parse_chunk(chunk)
                    if delta is None:
                        continue
                    emitted = True
                    yield delta
                return
            except Exception as exc:  # noqa: BLE001 - 统一归一到 LLMError
                if _looks_like_tool_rejection(exc) and tools and self.tools_supported:
                    self.tools_supported = False
                    tools = None
                    emitted = False
                    continue
                err = _classify(exc)
                if not emitted and err.retryable and attempt < self._settings.MAX_RETRIES:
                    attempt += 1
                    if self.on_retry:
                        self.on_retry(attempt, str(err))
                    delay = min(0.4 * (self._settings.RETRY_BACKOFF ** attempt), 8.0)
                    await asyncio.sleep(delay + random.uniform(0, 0.1))
                    continue
                raise err from exc

    @staticmethod
    def _parse_chunk(chunk: Any) -> Delta | None:
        usage = getattr(chunk, "usage", None)
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            if usage is not None:
                return Delta(
                    usage={
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                        "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
                    }
                )
            return None
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        out = Delta(finish_reason=getattr(choice, "finish_reason", None))
        if usage is not None:
            out.usage = {
                "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            }
        if delta is not None:
            out.content = getattr(delta, "content", None) or ""
            for tc in getattr(delta, "tool_calls", None) or []:
                fn = getattr(tc, "function", None)
                out.tool_call_index = getattr(tc, "index", 0) or 0
                out.tool_call_id = getattr(tc, "id", None)
                out.tool_call_name = getattr(fn, "name", None) if fn is not None else None
                out.tool_call_args = (getattr(fn, "arguments", None) or "") if fn is not None else ""
        return out

    async def complete(self, messages: list[Message], *, max_tokens: int = 256) -> str:
        try:
            resp = await self._client.chat.completions.create(
                model=self._settings.AGENT_MODEL,
                messages=messages,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:  # noqa: BLE001
            raise _classify(exc) from exc


# --------------------------------------------------------------------------- #
# Mock 实现：零 Key、零网络、结果可预测
# --------------------------------------------------------------------------- #
_SPECIAL_ARGS: dict[str, Any] = {
    # 冒泡排序：既是面试常见题，也能证明“子进程执行 + stdout 回传”整条链路真的通了
    "code": (
        "nums = [5, 2, 9, 1, 7]\n"
        "for i in range(len(nums)):\n"
        "    for j in range(len(nums) - 1 - i):\n"
        "        if nums[j] > nums[j + 1]:\n"
        "            nums[j], nums[j + 1] = nums[j + 1], nums[j]\n"
        "print(nums)\n"
    ),
    "path": "mock_note.txt",
    "content": "mock content",
    "workflow_name": "daily_report",
    "action": "write",
    "query": "AI agent 工程化最佳实践",
}

# Mock 的“意图识别”：只靠关键词路由到最像的已注册工具，保证演示时工具选得合理
_TOOL_HINTS: dict[str, tuple[str, ...]] = {
    "search_web": ("搜索", "查一下", "新闻", "最新", "search"),
    "file_ops": ("文件", "写入", "加个", "保存", "创建", "读一下"),
    "run_workflow": ("工作流", "workflow"),
    "execute_code": ("代码", "执行", "排序", "计算", "python", "跑一下"),
}
_FILENAME = re.compile(r"[\w\-]+\.(?:py|md|txt|json|csv|yaml|yml)")


def _action_from_text(text: str) -> str:
    """把「创建/追加/看有哪些」这类说法映射到 file_ops 的 action。"""
    if any(h in text for h in ("列表", "列出", "有哪些", "list")):
        return "list"
    if "追加" in text:
        return "append"
    if any(h in text for h in ("写入", "创建", "保存", "写")):
        return "write"
    return "read"


def _pick_tool(tools: list[dict[str, Any]], text: str) -> dict[str, Any]:
    """按关键词挑一个工具；都不像就退回第一个（保持确定性）。"""
    for tool in tools:
        fn = tool.get("function", tool)
        hints = _TOOL_HINTS.get(fn.get("name", ""), ())
        if any(h in text for h in hints):
            return tool
    return tools[0]


def _build_args_from_schema(schema: dict[str, Any] | None, text: str) -> dict[str, Any]:
    """按 JSON Schema 造一组合法入参，保证 Mock 的工具调用一定能跑通。"""
    schema = schema or {}
    props: dict[str, Any] = schema.get("properties") or {}
    required: list[str] = schema.get("required") or list(props.keys())
    args: dict[str, Any] = {}
    # 用户话里出现的文件名，直接当 path 用，演示时比 mock_note.txt 更自然
    found = _FILENAME.search(text)
    for name in required:
        meta = props.get(name) or {}
        if meta.get("enum"):
            # action 这类枚举别一律取第一个值，否则“创建文件”会被翻译成“读文件”
            candidate = _action_from_text(text) if name == "action" else None
            args[name] = candidate if candidate in meta["enum"] else meta["enum"][0]
        elif name == "path" and found:
            args[name] = found.group(0)
        elif name == "content":
            args[name] = text[:200] or _SPECIAL_ARGS["content"]
        elif name in _SPECIAL_ARGS:
            args[name] = _SPECIAL_ARGS[name]
        else:
            kind = meta.get("type", "string")
            if kind == "integer":
                args[name] = 3
            elif kind == "number":
                args[name] = 1.0
            elif kind == "boolean":
                args[name] = True
            elif kind == "object":
                args[name] = {}
            elif kind == "array":
                args[name] = []
            else:
                args[name] = text[:60] or "mock"
    return args


class MockLLM(BaseLLM):
    """确定性脚本模型：首轮发起一次工具调用，拿到结果后流式给出结论文本。

    ``mode`` 可选：
    - ``tool_then_answer``（默认）：完整走一次工具调用，用于演示与集成测试
    - ``answer_only``：直接流式回答，用于纯前端联调
    """

    def __init__(self, mode: str = "tool_then_answer", *, chunk_size: int = 8, latency: float = 0.0):
        self.mode = mode
        self.chunk_size = max(1, chunk_size)
        self.latency = latency
        self.tools_supported = True
        self.on_retry = None

    @staticmethod
    def _last_tool_result(messages: list[Message]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                return str(msg.get("content") or "")
        return ""

    @staticmethod
    def _last_user_text(messages: list[Message]) -> str:
        for msg in reversed(messages):
            if msg.get("role") == "user":
                return str(msg.get("content") or "")
        return ""

    async def _emit_text(self, text: str) -> AsyncIterator[Delta]:
        for i in range(0, len(text), self.chunk_size):
            if self.latency:
                await asyncio.sleep(self.latency)
            yield Delta(content=text[i : i + self.chunk_size])
        yield Delta(finish_reason="stop", usage={"prompt_tokens": 0, "completion_tokens": max(1, len(text) // 4)})

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[Delta]:
        user_text = self._last_user_text(messages)
        tool_result = self._last_tool_result(messages)

        if tool_result:
            answer = (
                f"工具返回：\n\n{tool_result[:300]}\n\n"
                f"（Mock 模式：以上是一次真实工具调用的结果。配置 OPENAI_API_KEY 后，"
                f"这里会由模型结合工具输出来回答「{user_text[:40]}」。）"
            )
            async for delta in self._emit_text(answer):
                yield delta
            return

        if self.mode == "answer_only" or not tools:
            async for delta in self._emit_text(f"[Mock 模式] 已收到：{user_text[:80]}（配置 OPENAI_API_KEY 后为真实推理）"):
                yield delta
            return

        tool = _pick_tool(tools, user_text)
        fn = tool.get("function", tool)
        args = _build_args_from_schema(fn.get("parameters"), user_text)
        raw = json.dumps(args, ensure_ascii=False)
        yield Delta(tool_call_index=0, tool_call_id="call_mock_0", tool_call_name=fn.get("name", "search_web"))
        for i in range(0, len(raw), 12):
            if self.latency:
                await asyncio.sleep(self.latency)
            yield Delta(tool_call_index=0, tool_call_args=raw[i : i + 12])
        yield Delta(finish_reason="tool_calls", usage={"prompt_tokens": 0, "completion_tokens": 12})

    async def complete(self, messages: list[Message], *, max_tokens: int = 256) -> str:
        return "[Mock 摘要] 之前的对话主要围绕用户的需求展开。"


def build_llm(settings: Settings | None = None, *, force_mock: bool = False) -> BaseLLM:
    s = settings or config
    if force_mock or s.use_mock:
        # MOCK_LATENCY 用于演示：>0 时按 chunk 间隔吐字，前端能看到真正的打字机效果
        return MockLLM(latency=getattr(s, "MOCK_LATENCY", 0.0))
    return OpenAICompatLLM(s)


__all__ = [
    "Delta",
    "LLMError",
    "ToolsUnsupportedError",
    "BaseLLM",
    "OpenAICompatLLM",
    "MockLLM",
    "build_llm",
]
