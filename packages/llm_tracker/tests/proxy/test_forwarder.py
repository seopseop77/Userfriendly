"""Tests for the transparent proxy forwarder."""

import httpx
import llm_tracker.proxy.forwarder as forwarder_module
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from llm_tracker.plugin_host.host import PluginHost
from llm_tracker.proxy.app import app
from llm_tracker.proxy.forwarder import forward_request
from llm_tracker.storage.models import Base, Exchange
from llm_tracker_sdk import BasePlugin
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

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


@pytest.mark.asyncio
async def test_on_persisted_sees_exchange_row():
    """Regression: on_persisted runs *after* record_exchange_timing.

    design.md §6.3.2 specifies that `on_persisted` fires after the local
    DB write so plugins can read the exchange row back. The forwarder
    used to dispatch `on_persisted` before the timing write, which left
    the row invisible to the plugin. This test pins the corrected
    ordering by injecting a plugin whose `on_persisted` opens a session,
    selects the exchange row by id, and asserts the row exists.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    seen: list[Exchange | None] = []

    class _ReaderPlugin(BasePlugin):
        name = "reader"

        async def on_persisted(self, exchange_id: str) -> None:
            async with factory() as session:
                row = await session.execute(
                    select(Exchange).where(Exchange.id == exchange_id)
                )
                seen.append(row.scalar_one_or_none())

    host = PluginHost(mode="L", session_factory=factory)
    host._plugins = [_ReaderPlugin()]

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/messages",
        "raw_path": b"/v1/messages",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 0),
        "root_path": "",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    request = Request(scope, receive=receive)

    with respx.mock:
        respx.post(_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200,
                content=_SSE_BODY,
                headers={"content-type": "text/event-stream"},
            )
        )
        response = await forward_request(request, "v1/messages", host)
        # Drain the streaming body so the post-stream code (timing write +
        # on_persisted) actually runs.
        async for _chunk in response.body_iterator:
            pass

    await engine.dispose()

    assert len(seen) == 1
    assert seen[0] is not None, "on_persisted ran before record_exchange_timing"
    assert seen[0].endpoint == "v1/messages"
