"""端到端冒烟：HTTP + SSE + WebSocket 全链路（Mock 模式，无需真实 API Key）。

用法（服务已在 http://127.0.0.1:8011 启动）：
    python e2e_smoke.py
"""
from __future__ import annotations

import asyncio
import json

import httpx
import websockets

BASE = "http://127.0.0.1:8011"
WS = "ws://127.0.0.1:8011/ws/chat"


def check_html() -> None:
    r = httpx.get(BASE + "/", timeout=10)
    assert r.status_code == 200, r.status_code
    body = r.text
    assert "<div id=\"root\">" in body or "root" in body, body[:200]
    print(f"[ok] GET / -> {r.status_code}, html {len(body)} bytes")


def check_config() -> None:
    r = httpx.get(BASE + "/api/config", timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert "has_api_key" in d and "model" in d, d
    assert "api_key" not in json.dumps(d).lower().replace("has_api_key", ""), "配置接口泄露了 Key"
    print(f"[ok] GET /api/config -> model={d['model']} mock={d.get('mock')} allow_runtime={d.get('allow_runtime_config')}")


def check_skills() -> None:
    r = httpx.get(BASE + "/api/skills", timeout=10)
    d = r.json()
    names = [s["name"] if isinstance(s, dict) else s for s in d.get("skills", [])]
    assert "calculator" in names or names, names
    print(f"[ok] GET /api/skills -> {names}")


def check_chat() -> None:
    r = httpx.post(BASE + "/api/chat", json={"message": "帮我算一下 12*34", "session_id": "e2e"}, timeout=30)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["response"], d
    trace = d.get("trace") or {}
    print(f"[ok] POST /api/chat -> {d['response'][:60]!r} trace(tools={trace.get('tool_calls')}, ms={trace.get('total_ms')})")


def check_sse() -> None:
    events: list[tuple[str, dict]] = []
    with httpx.stream(
        "POST",
        BASE + "/api/chat/stream",
        json={"message": "把 3 和 5 相加", "session_id": "e2e-sse"},
        timeout=40,
    ) as resp:
        assert resp.status_code == 200, resp.status_code
        for line in resp.iter_lines():
            # SSE 帧形如 ``data: {"event":"token","data":{...}}``，与 WS 共用同一信封
            if not line.startswith("data: "):
                continue
            msg = json.loads(line[6:])
            events.append((msg["event"], msg.get("data") or {}))
    kinds = [e[0] for e in events]
    assert "answer" in kinds, kinds
    token_count = kinds.count("token")
    print(f"[ok] SSE -> events={sorted(set(kinds))} tokens={token_count}")
    assert token_count >= 1, "SSE 没有 token 级增量，仍是整段回答"


async def check_ws() -> None:
    events: list[tuple[str, dict]] = []
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({"message": "现在几点？顺便读一下 README", "session_id": "e2e-ws"}))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=40)
            msg = json.loads(raw)
            events.append((msg["event"], msg.get("data") or {}))
            if msg["event"] in ("answer", "error"):
                break
        await ws.send(json.dumps({"event": "ping"}))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert pong["event"] == "pong", pong
    kinds = [e[0] for e in events]
    print(f"[ok] WS -> events={kinds} pong=ok")
    assert "token" in kinds, "WS 没有 token 事件"
    answer = [d for e, d in events if e == "answer"]
    assert answer and answer[0].get("content"), answer


def check_bad_request() -> None:
    r = httpx.post(BASE + "/api/chat", json={"message": "", "session_id": "e2e"}, timeout=10)
    assert r.status_code == 422, r.status_code
    d = r.json()
    assert d.get("error_code") == "invalid_request", d
    print(f"[ok] 空消息被拒 -> {r.status_code} {d}")


def main() -> None:
    check_html()
    check_config()
    check_skills()
    check_chat()
    check_bad_request()
    check_sse()
    asyncio.run(check_ws())
    print("\n端到端冒烟全部通过")


if __name__ == "__main__":
    main()
