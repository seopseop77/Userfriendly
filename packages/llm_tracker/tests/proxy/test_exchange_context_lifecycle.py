"""Tests that `forward_request` always pairs `begin_exchange` with `end_exchange`.

Phase 1b loose-end fix: previously the forwarder called
`plugin_host.begin_exchange(...)` but never `end_exchange(...)`, so
`PluginHost._exchange_contexts` grew unboundedly across requests. The
cleanup must run from the generators that `StreamingResponse` iterates,
because `forward_request` itself returns to Starlette before any of the
generator code runs.

These tests pin the contract for three return paths:

1. Normal completion (upstream stream drains end-to-end).
2. Block from `on_request_received` (early return via the synthetic SSE
   block stream).
3. Abort from `on_upstream_response_start` (block stream after the
   upstream connection has been opened).
"""

from __future__ import annotations

import httpx
import llm_tracker.proxy.forwarder as forwarder_module
import pytest
import respx
from llm_tracker.plugin_host.host import PluginHost
from llm_tracker.proxy.forwarder import forward_request
from llm_tracker.storage.models import Base
from llm_tracker_sdk import Abort, BasePlugin, Block, HookContext, Pass
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_SSE_BODY = b'data: {"type":"message_start"}\n\ndata: [DONE]\n\n'


@pytest.fixture(autouse=True)
def reset_http_client():
    forwarder_module._client = None
    yield
    forwarder_module._client = None


async def _empty_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _build_request() -> Request:
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

    return Request(scope, receive=receive)


@pytest.mark.asyncio
async def test_normal_completion_clears_exchange_context() -> None:
    """Happy path: stream drains; `_exchange_contexts` is empty afterward."""
    engine, factory = await _empty_factory()
    host = PluginHost(mode="L", session_factory=factory)

    request = _build_request()
    with respx.mock:
        respx.post(_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200,
                content=_SSE_BODY,
                headers={"content-type": "text/event-stream"},
            )
        )
        response = await forward_request(request, "v1/messages", host)
        async for _chunk in response.body_iterator:
            pass

    assert host._exchange_contexts == {}
    await engine.dispose()


@pytest.mark.asyncio
async def test_block_on_request_received_clears_exchange_context() -> None:
    """Block path (no upstream call): cleanup runs from the synthetic gen()."""
    engine, factory = await _empty_factory()

    class _Blocker(BasePlugin):
        name = "blocker"

        async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
            return Block(reason="nope")

    host = PluginHost(mode="L", session_factory=factory)
    host._plugins = [_Blocker()]

    request = _build_request()
    response = await forward_request(request, "v1/messages", host)
    async for _chunk in response.body_iterator:
        pass

    assert host._exchange_contexts == {}
    await engine.dispose()


@pytest.mark.asyncio
async def test_abort_on_upstream_response_start_clears_exchange_context() -> None:
    """Abort path (after upstream open): cleanup still runs."""
    engine, factory = await _empty_factory()

    class _Aborter(BasePlugin):
        name = "aborter"

        async def on_upstream_response_start(
            self, exchange_id: str, ctx: HookContext
        ) -> Pass | Abort:
            return Abort(reason="upstream rejected")

    host = PluginHost(mode="L", session_factory=factory)
    host._plugins = [_Aborter()]

    request = _build_request()
    with respx.mock:
        respx.post(_MESSAGES_URL).mock(
            return_value=httpx.Response(
                200,
                content=_SSE_BODY,
                headers={"content-type": "text/event-stream"},
            )
        )
        response = await forward_request(request, "v1/messages", host)
        async for _chunk in response.body_iterator:
            pass

    assert host._exchange_contexts == {}
    await engine.dispose()
