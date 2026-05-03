"""Tests for the transparent proxy forwarder."""

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

import llm_tracker.proxy.forwarder as forwarder_module
from llm_tracker.proxy.app import app

_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_SSE_BODY = b'data: {"type":"message_start"}\n\ndata: [DONE]\n\n'


@pytest.fixture(autouse=True)
def reset_http_client():
    """Ensure the singleton client is recreated inside each respx.mock context."""
    forwarder_module._client = None
    yield
    forwarder_module._client = None


@pytest.mark.asyncio
async def test_basic_forward():
    with respx.mock:
        respx.post(_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200,
                content=_SSE_BODY,
                headers={"content-type": "text/event-stream"},
            )
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": "test-key", "anthropic-version": "2023-06-01"},
                json={"model": "claude-3-haiku-20240307", "max_tokens": 10, "messages": []},
            )

    assert response.status_code == 200
    assert b"message_start" in response.content


@pytest.mark.asyncio
async def test_auth_header_forwarded():
    with respx.mock:
        route = respx.post(_MESSAGES_URL).mock(return_value=httpx.Response(200, content=_SSE_BODY))
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            await client.post(
                "/v1/messages",
                headers={"x-api-key": "sk-ant-test", "anthropic-version": "2023-06-01"},
                json={},
            )

    assert route.called
    assert route.calls[0].request.headers.get("x-api-key") == "sk-ant-test"


@pytest.mark.asyncio
async def test_upstream_status_code_preserved():
    with respx.mock:
        respx.post(_MESSAGES_URL).mock(
            return_value=httpx.Response(
                400,
                content=b'{"type":"error","error":{"type":"invalid_request_error"}}',
                headers={"content-type": "application/json"},
            )
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/v1/messages", json={})

    assert response.status_code == 400
    assert b"error" in response.content
