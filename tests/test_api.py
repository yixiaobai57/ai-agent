"""A7：HTTP 契约（含 v2 兼容）、鉴权、统一错误体、SSE。

注意：这些用例用 TestClient 走真实启动流程（lifespan + 会话后端 + 技能发现），
但 LLM 是 Mock，不产生任何外部请求。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from config import Settings
from main import create_app
from sessions.store import MemorySessionStore


@pytest.fixture
def secured_client(settings: Settings, agent_factory: Any) -> Any:
    settings.ALLOW_RUNTIME_CONFIG = True
    settings.ADMIN_TOKEN = "s3cret"
    store = MemorySessionStore(agent_factory, max_sessions=10, ttl=0)
    app = create_app(settings=settings, session_store=store)
    with TestClient(app) as c:
        yield c


def test_health_and_alias(client: TestClient) -> None:
    for path in ("/health", "/api/health"):
        body = client.get(path).json()
        assert body["status"] == "ok"
        assert set(body) >= {"model", "base_url", "skills", "workflows", "mock"}


def test_skills_and_workflows_contract(client: TestClient) -> None:
    skills = client.get("/api/skills").json()["skills"]
    assert isinstance(skills, list) and len(skills) >= 4
    assert all({"name", "description", "enabled"} <= set(s) for s in skills)

    workflows = client.get("/api/workflows").json()["workflows"]
    assert any(w["name"] == "daily_report" for w in workflows)


def test_config_read_does_not_leak_secret(client: TestClient) -> None:
    body = client.get("/api/config").json()
    assert body["has_api_key"] is False
    assert "OPENAI_API_KEY" not in body
    assert body["mock"] is True


def test_chat_round_trip_and_session_isolation(client: TestClient) -> None:
    r = client.post("/api/chat", json={"message": "你好", "session_id": "s1"})
    assert r.status_code == 200
    body = r.json()
    assert body["response"]
    assert body["session_id"] == "s1"
    assert body["trace"]["llm_calls"] >= 2

    r2 = client.post("/api/chat", json={"message": "继续", "session_id": "s2"})
    assert r2.status_code == 200
    stats = client.get("/api/stats").json()
    assert stats["sessions"] >= 2


def test_empty_message_is_rejected_with_error_code(client: TestClient) -> None:
    r = client.post("/api/chat", json={"message": "", "session_id": "s1"})
    assert r.status_code == 422
    assert r.json()["error_code"] == "invalid_request"


def test_bad_session_id_is_rejected(client: TestClient) -> None:
    r = client.post("/api/chat", json={"message": "hi", "session_id": "../../etc"})
    assert r.status_code == 422


def test_new_and_clear_session(client: TestClient) -> None:
    sid = client.post("/api/session/new").json()["session_id"]
    assert 1 <= len(sid) <= 64
    r = client.request("DELETE", "/api/session", json={"session_id": sid})
    assert r.status_code == 200 and r.json()["status"] == "cleared"


def test_config_write_is_blocked_by_default(client: TestClient) -> None:
    r = client.post("/api/config", json={"base_url": "https://evil.example.com/v1"})
    assert r.status_code == 403
    assert r.json()["error_code"] == "runtime_config_disabled"


def test_config_write_requires_admin_token(secured_client: TestClient) -> None:
    assert secured_client.post("/api/config", json={"model": "x"}).status_code == 401
    r = secured_client.post("/api/config", json={"model": "qwen-plus"}, headers={"X-Admin-Token": "s3cret"})
    assert r.status_code == 200
    assert r.json()["model"] == "qwen-plus"
    bearer = secured_client.post(
        "/api/config", json={"model": "glm-4"}, headers={"Authorization": "Bearer s3cret"}
    )
    assert bearer.status_code == 200


def test_config_write_rejects_non_http_base_url(secured_client: TestClient) -> None:
    r = secured_client.post(
        "/api/config",
        json={"base_url": "ftp://evil.example.com"},
        headers={"X-Admin-Token": "s3cret"},
    )
    assert r.status_code == 400
    assert r.json()["error_code"] == "invalid_config"


def test_payload_too_large_is_413(client: TestClient, settings: Settings) -> None:
    settings.MAX_REQUEST_BYTES = 1024
    body = {"message": "x" * 2000, "session_id": "s1"}
    r = client.post("/api/chat", json=body)
    assert r.status_code in (413, 422)


def test_sse_streams_tokens(client: TestClient) -> None:
    with client.stream("POST", "/api/chat/stream", json={"message": "介绍一下自己", "session_id": "sse"}) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                events.append(payload["event"])
    assert "token" in events
    assert events[-1] == "answer"


def test_websocket_full_turn(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"message": "你好", "session_id": "ws1"})
        events = []
        while True:
            msg = ws.receive_json()
            events.append(msg["event"])
            if msg["event"] == "answer":
                break
    assert events[0] == "thinking"
    assert "token" in events and "tool_result" in events


def test_websocket_handles_ping_and_bad_request(client: TestClient) -> None:
    with client.websocket_connect("/ws/chat") as ws:
        ws.send_json({"event": "ping"})
        assert ws.receive_json()["event"] == "pong"
        ws.send_json({"message": "", "session_id": "ws2"})
        msg = ws.receive_json()
        assert msg["event"] == "error" and msg["data"]["code"] == "invalid_request"
