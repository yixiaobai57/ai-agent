"""A8：会话后端（内存 LRU / TTL、SQLite 持久化、重启续聊）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from config import Settings
from sessions.store import MemorySessionStore, SQLiteSessionStore, create_session_store


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        MOCK_LLM=True,
        OPENAI_API_KEY="",
        WORKSPACE_DIR=tmp_path / "ws",
        DATA_DIR=tmp_path / "data",
        SESSION_BACKEND="sqlite",
        SESSION_TTL=0,
        _env_file=None,
    )


def test_memory_store_is_lru_bounded(agent_factory: Any) -> None:
    store = MemorySessionStore(agent_factory, max_sessions=2, ttl=0)
    a = store.get_or_create("a")
    store.get_or_create("b")
    store.get("a")  # 让 a 变成最近使用
    store.get_or_create("c")
    assert store.count() == 2
    assert store.get("b") is None
    assert store.get("a") is a


def test_memory_store_ttl_expires(agent_factory: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemorySessionStore(agent_factory, max_sessions=10, ttl=1)
    store.get_or_create("a")
    monkeypatch.setattr("sessions.store.time.time", lambda: 10_000_000_000.0)
    assert store.get("a") is None


def test_sqlite_persists_across_restart(tmp_path: Path, agent_factory: Any) -> None:
    db = tmp_path / "sessions.db"
    store = SQLiteSessionStore(db, agent_factory, max_sessions=10, ttl=0)
    agent = store.get_or_create("s1")
    agent.memory.add_user("我叫小白")
    agent.memory.add_assistant("记住了")
    store.save("s1", agent)
    assert store.count() == 1
    store.close()

    reopened = SQLiteSessionStore(db, agent_factory, max_sessions=10, ttl=0)
    restored = reopened.get("s1")
    assert restored is not None
    assert [m["content"] for m in restored.memory.messages] == ["我叫小白", "记住了"]
    assert reopened.count() == 1
    reopened.close()


def test_sqlite_caps_total_sessions(tmp_path: Path, agent_factory: Any) -> None:
    store = SQLiteSessionStore(tmp_path / "s.db", agent_factory, max_sessions=2, ttl=0)
    for sid in ("a", "b", "c"):
        agent = store.get_or_create(sid)
        store.save(sid, agent)
    assert store.count() <= 2
    store.close()


def test_sqlite_delete_and_clear(tmp_path: Path, agent_factory: Any) -> None:
    store = SQLiteSessionStore(tmp_path / "d.db", agent_factory, max_sessions=5, ttl=0)
    store.get_or_create("x")
    assert store.delete("x") is True
    store.get_or_create("y")
    store.clear()
    assert store.count() == 0
    store.close()


def test_create_session_store_respects_backend(settings: Settings, agent_factory: Any) -> None:
    store = create_session_store(settings, factory=agent_factory)
    assert isinstance(store, SQLiteSessionStore)
    settings.SESSION_BACKEND = "memory"
    assert isinstance(create_session_store(settings, factory=agent_factory), MemorySessionStore)


def test_refresh_clients_keeps_history(agent_factory: Any) -> None:
    store = MemorySessionStore(agent_factory, max_sessions=5, ttl=0)
    agent = store.get_or_create("a")
    agent.memory.add_user("hi")
    store.refresh_clients()
    assert store.get("a") is agent
    assert agent.memory.messages
