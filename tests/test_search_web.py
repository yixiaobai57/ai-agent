"""A7 补充：search_web 的 Mock 降级、条数收敛、以及三类网络错误的可读映射。"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from config import config
from skills.search_web import SERPER_ENDPOINT, SearchWebSkill


class FakeResponse:
    def __init__(self, payload: dict[str, Any] | None = None, status: int = 200) -> None:
        self._payload = payload or {}
        self.status_code = status
        self.request = httpx.Request("POST", SERPER_ENDPOINT)

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=self.request, response=self)  # type: ignore[arg-type]


class FakeClient:
    """替身 httpx.AsyncClient：记录请求体，按需抛错或返回固定响应。"""

    last_payload: dict[str, Any] | None = None
    last_headers: dict[str, str] | None = None

    def __init__(self, *, response: FakeResponse | None = None, error: Exception | None = None, **kwargs: Any) -> None:
        self._response = response or FakeResponse()
        self._error = error
        self.kwargs = kwargs

    async def __aenter__(self) -> FakeClient:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def post(self, url: str, headers: dict[str, str], json: dict[str, Any]) -> FakeResponse:
        FakeClient.last_payload = json
        FakeClient.last_headers = headers
        if self._error:
            raise self._error
        return self._response


@pytest.fixture
def skill() -> SearchWebSkill:
    return SearchWebSkill()


def _patch_client(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> None:
    FakeClient.last_payload = None
    FakeClient.last_headers = None
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: FakeClient(**kwargs, **kw))


async def test_without_api_key_returns_marked_mock(skill: SearchWebSkill, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SERPER_API_KEY", "")
    result = await skill.execute(query="fastapi 流式")

    assert result.success
    assert result.metadata["mock"] is True
    assert "Mock 搜索结果" in str(result.data)
    assert "fastapi 流式" in str(result.data)


async def test_real_call_parses_organic_and_truncates_snippet(
    skill: SearchWebSkill, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "SERPER_API_KEY", "test-key")
    long_snippet = "x" * 800
    _patch_client(
        monkeypatch,
        response=FakeResponse(
            {
                "organic": [
                    {"title": "标题一", "snippet": long_snippet, "link": "https://a.example"},
                    {"title": "标题二", "snippet": "短摘要", "link": "https://b.example"},
                ]
            }
        ),
    )

    result = await skill.execute(query="agent", num_results=5)

    assert result.success
    assert result.metadata["mock"] is False
    assert result.metadata["count"] == 2
    data = str(result.data)
    assert "**标题一**" in data and "https://b.example" in data
    # 单条摘要被裁到 500 字符，不会把整段 800 字符塞进上下文
    snippet_block = data.split("**标题一**")[1].split("https://a.example")[0]
    assert len(snippet_block.strip()) == 500
    assert FakeClient.last_headers is not None
    assert FakeClient.last_headers["X-API-KEY"] == "test-key"


async def test_num_results_is_clamped_to_1_10(skill: SearchWebSkill, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SERPER_API_KEY", "test-key")
    _patch_client(monkeypatch, response=FakeResponse({"organic": []}))

    await skill.execute(query="q", num_results=99)
    assert FakeClient.last_payload is not None and FakeClient.last_payload["num"] == 10

    await skill.execute(query="q", num_results=0)
    assert FakeClient.last_payload is not None and FakeClient.last_payload["num"] == 5

    await skill.execute(query="q", num_results=-3)
    assert FakeClient.last_payload is not None and FakeClient.last_payload["num"] == 1


async def test_empty_organic_is_a_normal_empty_result(skill: SearchWebSkill, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SERPER_API_KEY", "test-key")
    _patch_client(monkeypatch, response=FakeResponse({"organic": []}))

    result = await skill.execute(query="没有结果的词")

    assert result.success
    assert result.metadata["count"] == 0
    assert "没有找到相关结果" in str(result.data)


async def test_timeout_maps_to_readable_error(skill: SearchWebSkill, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SERPER_API_KEY", "test-key")
    _patch_client(monkeypatch, error=httpx.TimeoutException("timed out"))

    result = await skill.execute(query="q")

    assert not result.success
    assert result.metadata["error_code"] == "timeout"
    assert "超时" in str(result.error)


async def test_http_status_error_keeps_status_code(skill: SearchWebSkill, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SERPER_API_KEY", "test-key")
    _patch_client(monkeypatch, response=FakeResponse({}, status=429))

    result = await skill.execute(query="q")

    assert not result.success
    assert result.metadata["error_code"] == "http_error"
    assert result.metadata["status"] == 429
    assert "429" in str(result.error)


async def test_network_error_maps_to_network_error(skill: SearchWebSkill, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SERPER_API_KEY", "test-key")
    _patch_client(monkeypatch, error=httpx.ConnectError("connection reset"))

    result = await skill.execute(query="q")

    assert not result.success
    assert result.metadata["error_code"] == "network_error"
