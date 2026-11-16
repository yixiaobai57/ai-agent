"""A3：Agent 主循环的流式、并行工具、参数纠错、超时、兜底与 trace。"""

from __future__ import annotations

from typing import Any

import pytest

from agent.core import _MAX_STEPS, Agent
from agent.llm import LLMError
from skills.registry import SkillRegistry

from .helpers import BoomSkill, EchoSkill, RaisingLLM, ScriptedLLM, SlowSkill, StrictSkill, text_step, tool_step


def make_skills() -> SkillRegistry:
    reg = SkillRegistry()
    for cls in (EchoSkill, StrictSkill, SlowSkill, BoomSkill):
        reg.register(cls)
    return reg


@pytest.fixture
def skills() -> SkillRegistry:
    return make_skills()


async def test_mock_full_loop_streams_and_calls_tool(settings: Any, skills: SkillRegistry, events: list[Any]) -> None:
    async def cb(event: str, data: dict[str, Any]) -> None:
        events.append((event, data))

    agent = Agent(settings=settings, skills=skills)
    answer = await agent.run("查一下今天的 AI 新闻", on_event=cb)

    kinds = [e for e, _ in events]
    assert kinds[0] == "thinking"
    assert "tool_call" in kinds and "tool_result" in kinds
    assert kinds[-1] == "answer"
    assert kinds.count("token") > 1, "应当是 token 级流式，而不是一次性整段"
    assert answer and answer == events[-1][1]["content"]
    assert events[-1][1]["trace"]["tool_calls"] >= 1

    # 记忆里必须留下 assistant(tool_calls) + tool 结果
    roles = [m["role"] for m in agent.memory.messages]
    assert "tool" in roles
    tool_idx = roles.index("tool")
    assert agent.memory.messages[tool_idx - 1].get("tool_calls")


async def test_parallel_tool_calls_both_executed(settings: Any, skills: SkillRegistry, events: list[Any]) -> None:
    async def cb(event: str, data: dict[str, Any]) -> None:
        events.append((event, data))

    llm = ScriptedLLM(
        [
            tool_step({"name": "echo", "args": {"text": "A"}}, {"name": "echo", "args": {"text": "B"}}),
            text_step("两次都完成"),
        ]
    )
    agent = Agent(settings=settings, skills=skills, llm=llm)
    answer = await agent.run("并行跑两个工具", on_event=cb)

    results = [d for e, d in events if e == "tool_result"]
    assert [r["status"] for r in results] == ["ok", "ok"]
    assert [r["data"] for r in results] == ["echo:A", "echo:B"]
    assert answer == "两次都完成"


async def test_invalid_arguments_are_fed_back_to_model(settings: Any, skills: SkillRegistry, events: list[Any]) -> None:
    async def cb(event: str, data: dict[str, Any]) -> None:
        events.append((event, data))

    llm = ScriptedLLM(
        [
            tool_step({"name": "strict", "args": {"mode": "c", "count": 9}}),
            text_step("我改好了"),
        ]
    )
    agent = Agent(settings=settings, skills=skills, llm=llm)
    await agent.run("调用 strict", on_event=cb)

    tool_msgs = [m for m in agent.memory.messages if m["role"] == "tool"]
    assert tool_msgs and "ERROR[invalid_arguments]" in tool_msgs[0]["content"]
    assert any("a" in m["content"] for m in tool_msgs), "错误信息应告诉模型可选值"


async def test_tool_timeout_is_isolated(settings: Any, skills: SkillRegistry) -> None:
    settings.TOOL_TIMEOUT = 0.2
    llm = ScriptedLLM([tool_step({"name": "slow", "args": {}}), text_step("超时了但还能答")])
    agent = Agent(settings=settings, skills=skills, llm=llm)

    answer = await agent.run("跑慢工具")
    assert answer == "超时了但还能答"
    trace = agent.last_trace.to_dict()
    assert trace["failed_tools"] == 1
    assert any(s["status"] == "timeout" for s in trace["steps"])


async def test_unknown_tool_and_skill_exception(settings: Any, skills: SkillRegistry) -> None:
    llm = ScriptedLLM(
        [tool_step({"name": "not_exist", "args": {}}, {"name": "boom", "args": {}}), text_step("收尾")]
    )
    agent = Agent(settings=settings, skills=skills, llm=llm)
    await agent.run("乱调工具")

    tool_msgs = [m["content"] for m in agent.memory.messages if m["role"] == "tool"]
    assert "ERROR[unknown_tool]" in tool_msgs[0]
    assert "ERROR[tool_exception]" in tool_msgs[1]


async def test_max_iterations_guard(settings: Any, skills: SkillRegistry) -> None:
    settings.MAX_ITERATIONS = 2
    llm = ScriptedLLM([tool_step({"name": "echo", "args": {"text": "loop"}})])
    agent = Agent(settings=settings, skills=skills, llm=llm)

    answer = await agent.run("无限工具循环")
    assert answer == _MAX_STEPS
    assert llm.calls == 2


async def test_llm_error_returns_friendly_text(settings: Any, skills: SkillRegistry, events: list[Any]) -> None:
    async def cb(event: str, data: dict[str, Any]) -> None:
        events.append((event, data))

    agent = Agent(settings=settings, skills=skills, llm=RaisingLLM())
    answer = await agent.run("会失败的一轮", on_event=cb)

    assert "模型调用失败" in answer
    assert ("error" in [e for e, _ in events])


async def test_run_never_raises_on_internal_bug(settings: Any, skills: SkillRegistry) -> None:
    class BrokenLLM(RaisingLLM):
        async def stream(self, *args: Any, **kwargs: Any) -> Any:
            raise ValueError("unexpected")
            yield  # pragma: no cover

    agent = Agent(settings=settings, skills=skills, llm=BrokenLLM())
    answer = await agent.run("内部错误")
    assert "内部错误" in answer


async def test_per_call_callback_overrides_instance_callback(settings: Any, skills: SkillRegistry) -> None:
    instance_events: list[str] = []
    call_events: list[str] = []

    async def instance_cb(event: str, data: dict[str, Any]) -> None:
        instance_events.append(event)

    async def call_cb(event: str, data: dict[str, Any]) -> None:
        call_events.append(event)

    agent = Agent(settings=settings, skills=skills)
    agent.on_stream(instance_cb)
    await agent.run("hi", on_event=call_cb)

    assert call_events and not instance_events


async def test_trace_records_llm_and_tool_latency(settings: Any, skills: SkillRegistry) -> None:
    agent = Agent(settings=settings, skills=skills)
    await agent.run("hi")
    trace = agent.last_trace.to_dict()
    assert trace["llm_calls"] >= 2
    assert trace["tool_calls"] >= 1
    assert all("duration_ms" in s for s in trace["steps"])
    assert trace["total_ms"] >= 0
    assert trace["retries"] == 0


def test_llm_error_type_is_retryable_classified() -> None:
    err = LLMError("503 service unavailable", retryable=True, code="llm_error")
    assert err.retryable and err.code == "llm_error"
