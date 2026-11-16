"""测试夹具：全部离线，不依赖任何真实 API Key。"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from agent.core import SYSTEM_PROMPT, Agent
from agent.llm import MockLLM
from agent.memory import ConversationMemory
from config import Settings
from main import create_app
from sessions.store import MemorySessionStore
from skills.registry import registry


@pytest.fixture(scope="session", autouse=True)
def discovered_skills() -> Any:
    """让全局注册表完成一次自动发现（各测试共用，不重复 reset）。"""
    registry.discover()
    return registry


@pytest.fixture
def settings(tmp_path: Any) -> Settings:
    return Settings(
        MOCK_LLM=True,
        OPENAI_API_KEY="",
        SESSION_BACKEND="memory",
        WORKSPACE_DIR=tmp_path / "workspace",
        DATA_DIR=tmp_path / "data",
        SESSION_TTL=0,
        TOOL_TIMEOUT=3.0,
        LOG_LEVEL="WARNING",
    )


@pytest.fixture
def agent_factory(settings: Settings) -> Any:
    def make(snapshot: dict[str, Any] | None = None, llm: Any = None) -> Agent:
        memory = (
            ConversationMemory.from_dict(snapshot) if snapshot else ConversationMemory(system_prompt=SYSTEM_PROMPT)
        )
        return Agent(memory=memory, llm=llm or MockLLM(), skills=registry, settings=settings)

    return make


@pytest.fixture
def agent(agent_factory: Any) -> Agent:
    return agent_factory()


@pytest.fixture
def client(settings: Settings, agent_factory: Any) -> Any:
    store = MemorySessionStore(agent_factory, max_sessions=10, ttl=0)
    app = create_app(settings=settings, session_store=store)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def events() -> list[Any]:
    return []


@pytest.fixture
def recorder(events: list[Any]) -> Any:
    async def callback(event: str, data: dict[str, Any]) -> None:
        events.append((event, data))

    return callback
