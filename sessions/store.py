"""会话存储：把"某个 session_id 对应哪个 Agent"这件事从 main.py 里抽出来。

v2 用 ``Dict[str, Agent]`` 存在进程内存里：重启即丢、没有上限（内存泄漏）、
``POST /api/config`` 时直接 ``sessions.clear()`` 把所有会话炸掉。

现在提供两个后端：
- ``memory``：进程内 LRU + TTL，适合单机演示
- ``sqlite``（默认）：会话历史落 ``data/sessions.db``，重启后还能接着聊

两者都实现同一套接口，``create_session_store(config)`` 根据配置选择。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from agent.core import Agent
from config import Settings, config

logger = logging.getLogger(__name__)

Snapshot = dict[str, Any]
AgentFactory = Callable[[Snapshot | None], Agent]


def default_agent_factory(snapshot: Snapshot | None = None) -> Agent:
    if snapshot:
        from agent.memory import ConversationMemory

        return Agent(memory=ConversationMemory.from_dict(snapshot))
    return Agent()


def _refresh_agent(agent: Agent) -> None:
    refresh = getattr(getattr(agent, "llm", None), "refresh", None)
    if callable(refresh):
        refresh()


class SessionStore(Protocol):
    def get_or_create(self, sid: str) -> Agent: ...
    def get(self, sid: str) -> Agent | None: ...
    def save(self, sid: str, agent: Agent) -> None: ...
    def delete(self, sid: str) -> bool: ...
    def clear(self) -> None: ...
    def count(self) -> int: ...
    def refresh_clients(self) -> None: ...
    def close(self) -> None: ...


# --------------------------------------------------------------------------- #
# 内存后端
# --------------------------------------------------------------------------- #
class MemorySessionStore:
    def __init__(
        self,
        factory: AgentFactory = default_agent_factory,
        *,
        max_sessions: int = 500,
        ttl: int = 3600,
    ) -> None:
        self._agents: OrderedDict[str, tuple[Agent, float]] = OrderedDict()
        self._factory = factory
        self._max = max(1, max_sessions)
        self._ttl = max(0, ttl)

    def _expired(self, touched: float) -> bool:
        return self._ttl > 0 and (time.time() - touched) > self._ttl

    def get(self, sid: str) -> Agent | None:
        item = self._agents.get(sid)
        if not item:
            return None
        agent, touched = item
        if self._expired(touched):
            self._agents.pop(sid, None)
            return None
        self._agents.move_to_end(sid)
        self._agents[sid] = (agent, time.time())
        return agent

    def get_or_create(self, sid: str) -> Agent:
        agent = self.get(sid)
        if agent is not None:
            return agent
        agent = self._factory(None)
        self._agents[sid] = (agent, time.time())
        while len(self._agents) > self._max:
            self._agents.popitem(last=False)
        return agent

    def save(self, sid: str, agent: Agent) -> None:
        self._agents[sid] = (agent, time.time())
        self._agents.move_to_end(sid)

    def delete(self, sid: str) -> bool:
        return self._agents.pop(sid, None) is not None

    def clear(self) -> None:
        self._agents.clear()

    def count(self) -> int:
        return len(self._agents)

    def refresh_clients(self) -> None:
        """配置被改写后，让已存在的 Agent 重建 LLM 连接（不丢历史）。"""
        for agent, _ in self._agents.values():
            _refresh_agent(agent)

    def close(self) -> None:
        self._agents.clear()


# --------------------------------------------------------------------------- #
# SQLite 后端
# --------------------------------------------------------------------------- #
_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);
"""


class SQLiteSessionStore:
    def __init__(
        self,
        path: Path,
        factory: AgentFactory = default_agent_factory,
        *,
        max_sessions: int = 500,
        ttl: int = 3600,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._factory = factory
        self._max = max(1, max_sessions)
        self._ttl = max(0, ttl)
        self._cache: OrderedDict[str, Agent] = OrderedDict()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---- 内部 ----
    def _read(self, sid: str) -> Snapshot | None:
        row = self._conn.execute("SELECT data, updated_at FROM sessions WHERE id = ?", (sid,)).fetchone()
        if not row:
            return None
        data, updated_at = row
        if self._ttl > 0 and (time.time() - float(updated_at)) > self._ttl:
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            self._conn.commit()
            return None
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            logger.warning("会话 %s 的历史数据损坏，已重置", sid)
            self._conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            self._conn.commit()
            return None

    def get(self, sid: str) -> Agent | None:
        cached = self._cache.get(sid)
        if cached is not None:
            self._cache.move_to_end(sid)
            return cached
        with self._lock:
            snapshot = self._read(sid)
        if snapshot is None:
            return None
        agent = self._factory(snapshot)
        self._cache[sid] = agent
        self._evict()
        return agent

    def get_or_create(self, sid: str) -> Agent:
        agent = self.get(sid)
        if agent is not None:
            return agent
        agent = self._factory(None)
        self._cache[sid] = agent
        self._evict()
        self.save(sid, agent)
        return agent

    def save(self, sid: str, agent: Agent) -> None:
        payload = json.dumps(agent.memory.to_dict(), ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (sid, payload, time.time()),
            )
            self._conn.commit()
        self._cache[sid] = agent
        self._cache.move_to_end(sid)
        self._evict()

    def _evict(self) -> None:
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            if total > self._max:
                excess = total - self._max
                stale = [
                    r[0]
                    for r in self._conn.execute(
                        "SELECT id FROM sessions ORDER BY updated_at ASC LIMIT ?", (excess,)
                    ).fetchall()
                ]
                for sid in stale:
                    self._conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
                    self._cache.pop(sid, None)
                self._conn.commit()

    def delete(self, sid: str) -> bool:
        self._cache.pop(sid, None)
        with self._lock:
            cur = self._conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            self._conn.commit()
        return cur.rowcount > 0 or sid in self._cache

    def clear(self) -> None:
        self._cache.clear()
        with self._lock:
            self._conn.execute("DELETE FROM sessions")
            self._conn.commit()

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])

    def refresh_clients(self) -> None:
        for agent in self._cache.values():
            _refresh_agent(agent)

    def close(self) -> None:
        self._cache.clear()
        with self._lock:
            self._conn.close()


def create_session_store(settings: Settings | None = None, **kwargs: Any) -> SessionStore:
    s = settings or config
    factory: AgentFactory = kwargs.pop("factory", default_agent_factory)
    if s.SESSION_BACKEND == "sqlite":
        return SQLiteSessionStore(
            s.session_db_path,
            factory,
            max_sessions=s.MAX_SESSIONS,
            ttl=s.SESSION_TTL,
        )
    return MemorySessionStore(factory, max_sessions=s.MAX_SESSIONS, ttl=s.SESSION_TTL)


__all__ = [
    "AgentFactory",
    "SessionStore",
    "MemorySessionStore",
    "SQLiteSessionStore",
    "create_session_store",
    "default_agent_factory",
]
