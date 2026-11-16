"""一次 Agent 运行的结构化轨迹（trace）。

v2 只能靠 print 打日志，出问题无法复盘"哪一步慢、哪一次工具失败、重试了几次"。
这里把每个 LLM 调用与工具调用都记成一条 step，附带耗时、状态与摘要，
既可以随 HTTP 响应返回给前端，也可以导出成 JSON 做性能分析。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal

Status = Literal["ok", "error", "timeout", "skipped"]


def _now_ms() -> float:
    return time.perf_counter() * 1000


@dataclass
class TraceStep:
    index: int
    kind: Literal["llm", "tool"]
    name: str
    status: Status = "ok"
    duration_ms: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "detail": self.detail,
        }


@dataclass
class AgentTrace:
    steps: list[TraceStep] = field(default_factory=list)
    started_at: float = field(default_factory=_now_ms)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    retries: int = 0
    _seq: int = 0

    # ---- 记录 ----
    def next_index(self) -> int:
        self._seq += 1
        return self._seq

    def add(
        self,
        kind: Literal["llm", "tool"],
        name: str,
        duration_ms: int,
        status: Status = "ok",
        **detail: Any,
    ) -> TraceStep:
        step = TraceStep(
            index=self.next_index(),
            kind=kind,
            name=name,
            status=status,
            duration_ms=int(duration_ms),
            detail=detail,
        )
        self.steps.append(step)
        return step

    def record_usage(self, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.prompt_tokens += max(0, int(prompt_tokens or 0))
        self.completion_tokens += max(0, int(completion_tokens or 0))

    def record_retry(self) -> None:
        self.retries += 1

    # ---- 导出 ----
    @property
    def total_ms(self) -> int:
        return int(_now_ms() - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        tools = [s for s in self.steps if s.kind == "tool"]
        return {
            "steps": [s.to_dict() for s in self.steps],
            "total_ms": self.total_ms,
            "llm_calls": sum(1 for s in self.steps if s.kind == "llm"),
            "tool_calls": len(tools),
            "failed_tools": sum(1 for s in tools if s.status != "ok"),
            "retries": self.retries,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }


def stopwatch() -> float:
    """返回一个起点，配合 ``elapsed_ms`` 使用。"""
    return _now_ms()


def elapsed_ms(start: float) -> int:
    return int(_now_ms() - start)
