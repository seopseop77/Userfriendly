"""Tests for the transparent proxy forwarder."""

import json

import httpx
import llm_tracker.proxy.forwarder as forwarder_module
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from llm_tracker.plugin_host.host import PluginHost
from llm_tracker.proxy.app import app
from llm_tracker.proxy.forwarder import forward_request
from llm_tracker.storage.models import Base, Exchange
from llm_tracker_sdk import BasePlugin, Block, HookContext, Pass, Transform
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

        async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
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


# -- ADR-0002 §3 synthetic SSE block response -----------------------------


def _parse_sse_events(payload: bytes) -> list[tuple[str, dict]]:
    """Parse an `event: <name>\\ndata: <json>\\n\\n` SSE stream.

    Returns a list of (event_name, parsed_data_dict). Stops at the first
    blank-line-terminated chunk that lacks both fields. Strict on shape
    so any deviation from the documented format fails the test.
    """
    events: list[tuple[str, dict]] = []
    text = payload.decode("utf-8")
    for chunk in text.split("\n\n"):
        if not chunk.strip():
            continue
        name = data = None
        for line in chunk.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
        assert name is not None, f"chunk missing event name: {chunk!r}"
        assert data is not None, f"chunk missing data line: {chunk!r}"
        events.append((name, data))
    return events


@pytest.mark.asyncio
async def test_block_emits_synthetic_anthropic_sse():
    """ADR-0002 §3: block path returns 200 OK + Anthropic SSE, never tool_use.

    A plugin's `on_request_received` returns Block. The forwarder must
    emit the documented six-event sequence as `text/event-stream` with
    status 200, and persist an `Exchange` row with `blocked_by` set.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    class _Blocker(BasePlugin):
        name = "blocker"

        async def on_request_received(
            self, exchange_id: str, ctx: HookContext
        ) -> Pass | Block:
            return Block(reason="out of scope")

    host = PluginHost(mode="L", session_factory=factory)
    host._plugins = [_Blocker()]

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

    response = await forward_request(request, "v1/messages", host)
    assert response.status_code == 200
    assert response.media_type == "text/event-stream"

    body = b""
    async for chunk in response.body_iterator:
        body += chunk

    events = _parse_sse_events(body)
    names = [name for name, _ in events]
    assert names == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]

    # Never emit tool_use anywhere — the block stream must not trigger tools.
    assert b"tool_use" not in body

    # The text_delta carries the [llm-tracker] prefix and the reason.
    delta_event = next(d for n, d in events if n == "content_block_delta")
    assert delta_event["delta"] == {
        "type": "text_delta",
        "text": "[llm-tracker] out of scope",
    }

    # message_delta declares end_turn so Claude Code does not retry.
    msg_delta = next(d for n, d in events if n == "message_delta")
    assert msg_delta["delta"]["stop_reason"] == "end_turn"

    # The Exchange row is persisted with blocked_by populated.
    async with factory() as session:
        rows = (await session.execute(select(Exchange))).scalars().all()
    assert len(rows) == 1
    assert rows[0].blocked_by == "blocker"
    assert rows[0].endpoint == "v1/messages"

    await engine.dispose()


# -- ADR-0011 Transform handling -----------------------------------------


def _build_request_scope() -> tuple[dict, callable]:
    """Build a minimal Starlette Request scope + receive() callable.

    Shared shape across the Transform tests below: POST /v1/messages
    with one client-set header (`x-api-key`) and a small JSON body.
    Tests can override pieces by editing the returned scope dict
    before constructing the Request.
    """
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/v1/messages",
        "raw_path": b"/v1/messages",
        "query_string": b"",
        "headers": [
            (b"content-type", b"application/json"),
            (b"x-api-key", b"sk-client"),
        ],
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 0),
        "root_path": "",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b'{"client": true}', "more_body": False}

    return scope, receive


async def _empty_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory


@pytest.mark.asyncio
async def test_transform_merges_new_header_into_request():
    """ADR-0011 §1: plugin headers are merged; new keys are added."""
    engine, factory = await _empty_factory()

    class _Tagger(BasePlugin):
        name = "tagger"

        async def before_forward(
            self, exchange_id: str, ctx: HookContext
        ) -> Pass | Transform:
            return Transform(headers={"x-llm-tracker-task": "research"})

    host = PluginHost(mode="L", session_factory=factory)
    host._plugins = [_Tagger()]

    scope, receive = _build_request_scope()
    request = Request(scope, receive=receive)

    with respx.mock:
        route = respx.post(_MESSAGES_URL).mock(
            return_value=httpx.Response(200, content=_SSE_BODY)
        )
        response = await forward_request(request, "v1/messages", host)
        async for _chunk in response.body_iterator:
            pass

    sent = route.calls[0].request
    assert sent.headers.get("x-llm-tracker-task") == "research"
    # Original client header survives the merge.
    assert sent.headers.get("x-api-key") == "sk-client"

    await engine.dispose()


@pytest.mark.asyncio
async def test_transform_plugin_header_wins_on_conflict():
    """ADR-0011 §1: plugin value wins when its key collides with the request's."""
    engine, factory = await _empty_factory()

    class _Rewriter(BasePlugin):
        name = "rewriter"

        async def before_forward(
            self, exchange_id: str, ctx: HookContext
        ) -> Pass | Transform:
            return Transform(headers={"x-api-key": "sk-rewritten"})

    host = PluginHost(mode="L", session_factory=factory)
    host._plugins = [_Rewriter()]

    scope, receive = _build_request_scope()
    request = Request(scope, receive=receive)

    with respx.mock:
        route = respx.post(_MESSAGES_URL).mock(
            return_value=httpx.Response(200, content=_SSE_BODY)
        )
        response = await forward_request(request, "v1/messages", host)
        async for _chunk in response.body_iterator:
            pass

    sent = route.calls[0].request
    assert sent.headers.get("x-api-key") == "sk-rewritten"

    await engine.dispose()


@pytest.mark.asyncio
async def test_transform_replaces_whole_body_when_body_is_set():
    """ADR-0011 §2: Transform.body, when not None, replaces the upstream body."""
    engine, factory = await _empty_factory()

    class _BodySwapper(BasePlugin):
        name = "swapper"

        async def before_forward(
            self, exchange_id: str, ctx: HookContext
        ) -> Pass | Transform:
            return Transform(body=b'{"plugin_rewrote": true}')

    host = PluginHost(mode="L", session_factory=factory)
    host._plugins = [_BodySwapper()]

    scope, receive = _build_request_scope()
    request = Request(scope, receive=receive)

    with respx.mock:
        route = respx.post(_MESSAGES_URL).mock(
            return_value=httpx.Response(200, content=_SSE_BODY)
        )
        response = await forward_request(request, "v1/messages", host)
        async for _chunk in response.body_iterator:
            pass

    sent = route.calls[0].request
    assert sent.content == b'{"plugin_rewrote": true}'

    await engine.dispose()


@pytest.mark.asyncio
async def test_transform_multi_plugin_first_wins():
    """ADR-0011 §3: first plugin returning Transform applies; later plugins skipped.

    Inject two plugins. Only the first should run; the second's hook is
    never called (asserted by an explicit counter), and the first's
    headers reach upstream — the second's do not.
    """
    engine, factory = await _empty_factory()

    second_was_called = []

    class _First(BasePlugin):
        name = "first"

        async def before_forward(
            self, exchange_id: str, ctx: HookContext
        ) -> Pass | Transform:
            return Transform(headers={"x-from-first": "yes"})

    class _Second(BasePlugin):
        name = "second"

        async def before_forward(
            self, exchange_id: str, ctx: HookContext
        ) -> Pass | Transform:
            second_was_called.append(True)
            return Transform(headers={"x-from-second": "yes"})

    host = PluginHost(mode="L", session_factory=factory)
    host._plugins = [_First(), _Second()]

    scope, receive = _build_request_scope()
    request = Request(scope, receive=receive)

    with respx.mock:
        route = respx.post(_MESSAGES_URL).mock(
            return_value=httpx.Response(200, content=_SSE_BODY)
        )
        response = await forward_request(request, "v1/messages", host)
        async for _chunk in response.body_iterator:
            pass

    sent = route.calls[0].request
    assert sent.headers.get("x-from-first") == "yes"
    assert sent.headers.get("x-from-second") is None
    assert second_was_called == []

    await engine.dispose()
