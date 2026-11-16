"""A2：Mock Provider 的脚本化行为、工厂选择、重试分类。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent.llm import LLMError, MockLLM, OpenAICompatLLM, build_llm
from config import Settings

ECHO_TOOL = {
    "type": "function",
    "function": {
        "name": "echo",
        "description": "echo",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
}


async def test_mock_emits_tool_call_then_answer() -> None:
    llm = MockLLM()
    deltas = [d async for d in llm.stream([{"role": "user", "content": "帮我算 1+1"}], [ECHO_TOOL])]

    tool_deltas = [d for d in deltas if d.has_tool_call]
    assert tool_deltas[0].tool_call_name == "echo"
    raw_args = "".join(d.tool_call_args for d in tool_deltas)
    assert json.loads(raw_args) == {"text": "帮我算 1+1"}
    assert deltas[-1].finish_reason == "tool_calls"

    # 第二轮：已有 tool 结果 → 输出文本增量
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "帮我算 1+1"},
        {"role": "assistant", "content": None, "tool_calls": []},
        {"role": "tool", "tool_call_id": "call_mock_0", "content": "echo:2"},
    ]
    chunks = [d.content async for d in llm.stream(messages, [ECHO_TOOL]) if d.content]
    assert len(chunks) > 1, "应当是多个 token 增量，而不是一次性整段"
    assert "echo:2" in "".join(chunks)


async def test_mock_answer_only_mode() -> None:
    llm = MockLLM(mode="answer_only")
    text = "".join([d.content async for d in llm.stream([{"role": "user", "content": "hi"}], [ECHO_TOOL])])
    assert "hi" in text


async def test_mock_no_tools_falls_back_to_text() -> None:
    llm = MockLLM()
    text = "".join([d.content async for d in llm.stream([{"role": "user", "content": "hi"}], None)])
    assert text


def test_build_llm_selects_implementation() -> None:
    assert isinstance(build_llm(Settings(OPENAI_API_KEY="", MOCK_LLM=False, _env_file=None)), MockLLM)
    assert isinstance(build_llm(Settings(OPENAI_API_KEY="sk-x", MOCK_LLM=False, _env_file=None)), OpenAICompatLLM)
    assert isinstance(build_llm(Settings(OPENAI_API_KEY="sk-x", MOCK_LLM=True, _env_file=None)), MockLLM)


def test_mock_latency_is_configurable() -> None:
    """演示用的打字机效果：MOCK_LATENCY 应传到 MockLLM，而不是被忽略。"""
    llm = build_llm(Settings(OPENAI_API_KEY="", MOCK_LLM=True, MOCK_LATENCY=0.03, _env_file=None))
    assert isinstance(llm, MockLLM)
    assert llm.latency == 0.03


async def test_retry_then_raise_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        OPENAI_API_KEY="sk-x",
        MOCK_LLM=False,
        MAX_RETRIES=2,
        RETRY_BACKOFF=1.0,
        _env_file=None,
    )
    llm = OpenAICompatLLM(settings)
    attempts: list[int] = []

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr(llm, "_open_stream", boom)
    llm.on_retry = lambda attempt, msg: attempts.append(attempt)

    with pytest.raises(LLMError) as exc:
        async for _ in llm.stream([{"role": "user", "content": "hi"}]):
            pass
    assert exc.value.retryable is True
    assert exc.value.code == "timeout"
    assert attempts == [1, 2]


async def test_tool_rejection_disables_tools_instead_of_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(OPENAI_API_KEY="sk-x", MOCK_LLM=False, _env_file=None)
    llm = OpenAICompatLLM(settings)
    calls: list[Any] = []

    async def fake_open(messages: Any, tools: Any, temperature: Any, max_tokens: Any) -> Any:
        calls.append(tools)
        if tools:
            raise RuntimeError("tools not supported by this model 400")
        return _FakeStream()

    monkeypatch.setattr(llm, "_open_stream", fake_open)
    deltas = [d async for d in llm.stream([{"role": "user", "content": "hi"}], [ECHO_TOOL])]
    assert llm.tools_supported is False
    assert calls[0] is not None and calls[1] is None
    assert any(d.content for d in deltas)


class _FakeDelta:
    content = "ok"
    tool_calls = None


class _FakeChoice:
    delta = _FakeDelta()
    finish_reason = "stop"


class _FakeChunk:
    usage = None
    choices = [_FakeChoice()]


class _FakeStream:
    def __init__(self) -> None:
        self._done = False

    def __aiter__(self) -> Any:
        return self

    async def __anext__(self) -> Any:
        if self._done:
            raise StopAsyncIteration
        self._done = True
        return _FakeChunk()
