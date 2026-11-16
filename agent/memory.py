"""会话记忆：窗口裁剪、token 预算、以及长对话摘要。

v2 的 ``messages[-max_turns*2:]`` 是**按条数硬切**，会在长对话里把
``assistant(tool_calls)`` 和紧随其后的 ``tool`` 消息切成两半。OpenAI 协议要求
tool 消息必须紧跟在带 tool_calls 的 assistant 消息之后，于是第 20 轮之后必然 400。
这里的做法是**只在 user 轮边界切窗**，并额外做 token 预算裁剪——同样只在边界裁。

同时对外提供 ``to_dict`` / ``from_dict``，便于 SQLite 会话后端持久化。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from config import config

Message = dict[str, Any]
SummaryFn = Callable[[list[Message]], Awaitable[str]]


def estimate_tokens(text: str) -> int:
    """粗粒度 token 估算：中文按 1 字≈1 token，其余按 4 字符≈1 token。

    只需要"够用且单调"，用于预算裁剪，不追求与真实 tokenizer 一致。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + max(1, other // 4)


def _message_tokens(msg: Message) -> int:
    total = estimate_tokens(str(msg.get("content") or ""))
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        total += estimate_tokens(str(fn.get("name") or "")) + estimate_tokens(str(fn.get("arguments") or ""))
    return total


def sanitize_assistant_tool_call(content: str | None, tool_calls: list[dict[str, Any]]) -> Message:
    """把 SDK 对象收敛成协议允许的最小结构。

    v2 直接 ``msg.model_dump()`` 落库，会带上 ``refusal`` / ``annotations`` / ``audio``
    等字段，部分服务会以 400 拒绝这些未知字段。
    """
    cleaned = []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        cleaned.append(
            {
                "id": tc.get("id") or "",
                "type": "function",
                "function": {"name": fn.get("name") or "", "arguments": fn.get("arguments") or "{}"},
            }
        )
    return {"role": "assistant", "content": content or None, "tool_calls": cleaned}


class ConversationMemory:
    def __init__(self, system_prompt: str = "", *, max_turns: int | None = None, token_budget: int | None = None):
        self.system_prompt = system_prompt
        self.messages: list[Message] = []
        self.summary: str | None = None
        self.max_turns = config.MEMORY_MAX_TURNS if max_turns is None else max_turns
        self.token_budget = config.MEMORY_TOKEN_BUDGET if token_budget is None else token_budget

    # ---------------- 写入 ----------------
    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def add_user(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def add_tool_call(self, assistant_msg: Message) -> None:
        """兼容 v2 调用方：传入 assistant 消息（dict 或 SDK dump）。"""
        if assistant_msg.get("tool_calls"):
            self.messages.append(
                sanitize_assistant_tool_call(assistant_msg.get("content"), assistant_msg["tool_calls"])
            )
        else:
            self.messages.append({"role": "assistant", "content": assistant_msg.get("content") or ""})

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": tool_call_id, "content": content})

    # ---------------- 读取 ----------------
    def _user_indices(self) -> list[int]:
        return [i for i, m in enumerate(self.messages) if m.get("role") == "user"]

    def window(self, max_turns: int | None = None) -> list[Message]:
        """按 user 轮边界取最近 N 轮，并做 token 预算裁剪。

        断言：返回窗口的第一条永远不是 ``tool`` 角色，且每个 ``tool`` 消息前面
        必定有其对应的 ``assistant(tool_calls)``。
        """
        turns = self.max_turns if max_turns is None else max_turns
        idxs = self._user_indices()
        if not idxs:
            return list(self.messages[-(turns * 2) :]) if turns > 0 else []

        start = idxs[-turns] if len(idxs) > turns else idxs[0]
        window = self.messages[start:]

        # token 预算：只在 user 轮边界上往前丢，永不留孤儿 tool
        budget = self.token_budget
        while budget > 0 and self._window_tokens(window) > budget:
            inner = [i for i, m in enumerate(window) if m.get("role") == "user"]
            if len(inner) <= 1:
                break
            window = window[inner[1] :]
        return window

    @staticmethod
    def _window_tokens(window: list[Message]) -> int:
        return sum(_message_tokens(m) for m in window)

    def get_messages(self, max_turns: int | None = None) -> list[Message]:
        system = self.system_prompt
        if self.summary:
            system = f"{system}\n\n[Earlier conversation summary]\n{self.summary}"
        return [{"role": "system", "content": system}] + self.window(max_turns)

    def get_full_history(self) -> list[Message]:
        return list(self.messages)

    def turn_count(self) -> int:
        return len(self._user_indices())

    # ---------------- 摘要 ----------------
    async def maybe_summarize(self, summarize: SummaryFn) -> bool:
        """超过阈值就把较早的消息压成摘要。返回是否真的做了压缩。"""
        threshold = config.MEMORY_SUMMARY_THRESHOLD * 2
        if len(self.messages) <= threshold:
            return False

        idxs = self._user_indices()
        # 保留最后 threshold 条，且从 user 边界开始，避免截断配对
        keep_from = max(0, len(self.messages) - threshold)
        boundary = next((i for i in idxs if i >= keep_from), idxs[-1] if idxs else len(self.messages))
        old = self.messages[:boundary]
        lines = []
        for m in old:
            if m.get("role") in ("user", "assistant") and m.get("content"):
                label = "用户" if m["role"] == "user" else "助手"
                lines.append(f"{label}: {m['content']}")
        old_text = "\n".join(lines).strip()
        if not old_text:
            self.messages = self.messages[boundary:]
            return False

        new_summary = await summarize([{"role": "user", "content": old_text[:4000]}])
        if new_summary:
            self.summary = f"{self.summary}\n{new_summary}" if self.summary else new_summary
        self.messages = self.messages[boundary:]
        return True

    def clear(self) -> None:
        self.messages.clear()
        self.summary = None

    # ---------------- 持久化 ----------------
    def to_dict(self) -> dict[str, Any]:
        return {"system_prompt": self.system_prompt, "messages": self.messages, "summary": self.summary}

    @classmethod
    def from_dict(cls, data: dict[str, Any], **kwargs: Any) -> ConversationMemory:
        mem = cls(data.get("system_prompt") or "", **kwargs)
        mem.messages = list(data.get("messages") or [])
        mem.summary = data.get("summary")
        return mem


__all__ = ["ConversationMemory", "estimate_tokens", "sanitize_assistant_tool_call"]
