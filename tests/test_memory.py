"""A4：窗口裁剪不破坏 assistant(tool_calls) / tool 的配对。"""

from __future__ import annotations

from typing import Any

from agent.memory import ConversationMemory, estimate_tokens, sanitize_assistant_tool_call


def _tool_pair(i: int) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": f"问题 {i}"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": f"call_{i}", "type": "function", "function": {"name": "echo", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "tool_call_id": f"call_{i}", "content": f"结果 {i}"},
        {"role": "assistant", "content": f"答案 {i}"},
    ]


def test_window_never_starts_with_tool_message() -> None:
    memory = ConversationMemory("sys", max_turns=5)
    for i in range(15):
        for msg in _tool_pair(i):
            memory.add_message(msg)

    window = memory.window()
    assert window, "窗口不应为空"
    assert window[0]["role"] == "user"
    assert window[0]["content"] == "问题 10"


def test_window_keeps_every_tool_call_paired() -> None:
    memory = ConversationMemory("sys", max_turns=20, token_budget=10**9)
    for i in range(30):
        for msg in _tool_pair(i):
            memory.add_message(msg)

    window = memory.get_messages()
    pending: set[str] = set()
    for msg in window:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            pending = {tc["id"] for tc in msg["tool_calls"]}
        elif msg.get("role") == "tool":
            assert msg["tool_call_id"] in pending, "出现了孤儿 tool 消息"
            pending.discard(msg["tool_call_id"])


def test_token_budget_drops_oldest_turns_only_at_boundary() -> None:
    memory = ConversationMemory("sys", max_turns=50, token_budget=120)
    for i in range(40):
        for msg in _tool_pair(i):
            memory.add_message(msg)

    window = memory.window()
    assert window[0]["role"] == "user"
    assert sum(estimate_tokens(str(m.get("content") or "")) for m in window) <= 120 + 60


def test_sanitize_assistant_tool_call_strips_extra_fields() -> None:
    msg = sanitize_assistant_tool_call(
        None,
        [{"id": "c1", "type": "function", "function": {"name": "echo", "arguments": '{"text":"x"}'}, "extra": 1}],
    )
    assert set(msg) == {"role", "content", "tool_calls"}
    assert msg["tool_calls"][0]["function"]["name"] == "echo"
    assert "extra" not in msg["tool_calls"][0]


async def test_maybe_summarize_compresses_and_keeps_recent() -> None:
    memory = ConversationMemory("sys")
    for i in range(60):
        memory.add_user(f"问题 {i}")
        memory.add_assistant(f"答案 {i}")

    async def fake_summary(messages: list[dict[str, Any]]) -> str:
        return "早期对话摘要"

    changed = await memory.maybe_summarize(fake_summary)
    assert changed is True
    assert memory.summary == "早期对话摘要"
    assert len(memory.messages) <= 40
    assert memory.messages[0]["role"] == "user"
    assert "早期对话摘要" in memory.get_messages()[0]["content"]


def test_roundtrip_serialization() -> None:
    memory = ConversationMemory("sys")
    memory.add_user("hi")
    memory.add_assistant("hello")
    memory.summary = "摘要"
    restored = ConversationMemory.from_dict(memory.to_dict())
    assert restored.messages == memory.messages
    assert restored.summary == "摘要"
    assert restored.turn_count() == 1


def test_estimate_tokens_monotonic() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abc") >= 1
    assert estimate_tokens("中文中文中文中文") > estimate_tokens("ab")
    assert estimate_tokens("a" * 400) > estimate_tokens("a" * 40)
