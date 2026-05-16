"""Forwarder + plugin-host integration (CP8).

CP7 pinned the credential pass-through; CP8 wires the 8-hook lifecycle
around the same forwarder. These tests exercise the new wiring:

* ``Block`` from ``on_request_received`` short-circuits to the
  synthetic SSE block stream and never calls upstream.
* ``Block`` from ``before_forward`` short-circuits *after* the
  request-received hook, also without calling upstream.
* ``Transform`` from ``before_forward`` rewrites outbound
  headers/body.
* ``Abort`` from ``on_upstream_response_start`` closes the upstream
  stream and emits the synthetic SSE block stream.
* ``Abort`` from ``on_response_chunk`` cuts the stream mid-flight.
* The happy path runs every per-exchange hook in order and ends with
  ``on_persisted``.

No PostgreSQL fixture: the host is constructed with a list-capturing
audit writer and ``httpx.MockTransport`` stands in for Anthropic.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from llm_tracker_sdk import Abort, BasePlugin, Block, HookContext, Pass, Transform
from llm_tracker_server.plugin_host.host import PluginHost
from llm_tracker_server.proxy.forwarder import forward_request
from starlette.requests import Request


def _make_request(
    *,
    method: str = "POST",
    path: str = "/v1/messages",
    headers: dict[str, str] | None = None,
    body: bytes = b'{"model":"claude-x","messages":[]}',
) -> Request:
    raw_headers: list[tuple[bytes, bytes]] = []
    for key, value in (headers or {}).items():
        raw_headers.append((key.lower().encode("latin-1"), value.encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "headers": raw_headers,
    }
    sent = {"done": False}

    async def receive() -> dict:
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive=receive)


def _capture_handler(captured: list[httpx.Request]):
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"event: ping\ndata: {}\n\nevent: message_stop\ndata: {}\n\n",
        )

    return handler


async def _drain(response) -> bytes:
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    return body


@pytest.fixture
def captured_audit():
    rows: list[dict[str, Any]] = []

    async def writer(**kwargs: Any) -> None:
        rows.append(kwargs)

    writer.rows = rows  # type: ignore[attr-defined]
    return writer


# -- Block from on_request_received --------------------------------------


class _BlockOnReceive(BasePlugin):
    name = "block_on_receive"

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        return Block(reason="not on my watch")


@pytest.mark.asyncio
async def test_block_on_request_received_short_circuits_upstream(captured_audit):
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [_BlockOnReceive()]

    async with httpx.AsyncClient(transport=transport) as client:
        response = await forward_request(
            _make_request(headers={"x-api-key": "sk-ant-test"}),
            "v1/messages",
            http_client=client,
            upstream_base="http://upstream",
            plugin_host=host,
        )
        body = await _drain(response)

    assert captured == []  # never called upstream
    assert response.status_code == 200
    assert b"[llm-tracker] not on my watch" in body
    # Per-exchange ctx is dropped via the gen()'s finally clause.
    assert host._exchange_contexts == {}


# -- Block from before_forward -------------------------------------------


class _BlockBeforeForward(BasePlugin):
    name = "block_before_forward"

    async def before_forward(self, exchange_id: str, ctx: HookContext) -> Pass | Block | Transform:
        return Block(reason="late veto")


@pytest.mark.asyncio
async def test_block_on_before_forward_short_circuits_upstream(captured_audit):
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [_BlockBeforeForward()]

    async with httpx.AsyncClient(transport=transport) as client:
        response = await forward_request(
            _make_request(),
            "v1/messages",
            http_client=client,
            upstream_base="http://upstream",
            plugin_host=host,
        )
        body = await _drain(response)

    assert captured == []
    assert b"[llm-tracker] late veto" in body


# -- Transform from before_forward ---------------------------------------


class _TransformBeforeForward(BasePlugin):
    name = "transform_before_forward"

    async def before_forward(self, exchange_id: str, ctx: HookContext) -> Pass | Block | Transform:
        return Transform(
            headers={"x-llm-transform-marker": "yes"},
            body=b'{"model":"claude-x","messages":[{"role":"user","content":"replaced"}]}',
        )


@pytest.mark.asyncio
async def test_transform_in_before_forward_rewrites_outbound(captured_audit):
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [_TransformBeforeForward()]

    async with httpx.AsyncClient(transport=transport) as client:
        response = await forward_request(
            _make_request(headers={"x-api-key": "sk-ant-test"}),
            "v1/messages",
            http_client=client,
            upstream_base="http://upstream",
            plugin_host=host,
        )
        await _drain(response)

    assert len(captured) == 1
    outbound = captured[0]
    assert outbound.headers.get("x-llm-transform-marker") == "yes"
    # Credential still passes through; transform appended, not replaced.
    assert outbound.headers.get("x-api-key") == "sk-ant-test"
    # Replacement body landed on the upstream request.
    assert b'"content":"replaced"' in outbound.content


# -- Abort on upstream response start ------------------------------------


class _AbortOnStart(BasePlugin):
    name = "abort_on_start"

    async def on_upstream_response_start(self, exchange_id: str, ctx: HookContext) -> Pass | Abort:
        return Abort(reason="not this stream")


@pytest.mark.asyncio
async def test_abort_on_upstream_response_start_emits_block_stream(captured_audit):
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [_AbortOnStart()]

    async with httpx.AsyncClient(transport=transport) as client:
        response = await forward_request(
            _make_request(),
            "v1/messages",
            http_client=client,
            upstream_base="http://upstream",
            plugin_host=host,
        )
        body = await _drain(response)

    # Upstream WAS called (it had to be, to even reach
    # on_upstream_response_start) -- but its body is replaced.
    assert len(captured) == 1
    assert b"[llm-tracker] not this stream" in body
    assert b"event: ping" not in body  # upstream stream replaced wholesale


# -- happy path: all per-exchange hooks fire in order --------------------


class _LifecycleRecorder(BasePlugin):
    name = "recorder"

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        self.calls.append("on_request_received")
        return Pass()

    async def before_forward(self, exchange_id: str, ctx: HookContext) -> Pass | Block | Transform:
        self.calls.append("before_forward")
        return Pass()

    async def on_upstream_response_start(self, exchange_id: str, ctx: HookContext) -> Pass | Abort:
        self.calls.append("on_upstream_response_start")
        return Pass()

    async def on_response_chunk(
        self, exchange_id: str, chunk: bytes, ctx: HookContext
    ) -> Pass | Abort:
        self.calls.append("on_response_chunk")
        return Pass()

    async def on_response_complete(self, exchange_id: str, ctx: HookContext) -> None:
        self.calls.append("on_response_complete")

    async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
        self.calls.append("on_persisted")


@pytest.mark.asyncio
async def test_happy_path_dispatches_every_hook_in_order(captured_audit):
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    plugin = _LifecycleRecorder()
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [plugin]

    async with httpx.AsyncClient(transport=transport) as client:
        response = await forward_request(
            _make_request(headers={"x-api-key": "sk-ant-test"}),
            "v1/messages",
            http_client=client,
            upstream_base="http://upstream",
            plugin_host=host,
        )
        body = await _drain(response)

    assert len(captured) == 1
    # Anthropic body streamed back verbatim.
    assert b"event: ping" in body
    # Strict prefix + final two hooks; on_response_chunk may fire
    # multiple times depending on chunk boundaries from
    # `aiter_bytes`, so assert >=1 in the middle.
    assert plugin.calls[0] == "on_request_received"
    assert plugin.calls[1] == "before_forward"
    assert plugin.calls[2] == "on_upstream_response_start"
    assert "on_response_chunk" in plugin.calls
    assert plugin.calls[-2] == "on_response_complete"
    assert plugin.calls[-1] == "on_persisted"
    # Context cleanup ran in the gen()'s finally clause.
    assert host._exchange_contexts == {}


# -- Abort mid-stream ----------------------------------------------------


class _AbortOnFirstChunk(BasePlugin):
    name = "abort_chunk"

    async def on_response_chunk(
        self, exchange_id: str, chunk: bytes, ctx: HookContext
    ) -> Pass | Abort:
        return Abort(reason="poisoned chunk")


@pytest.mark.asyncio
async def test_abort_on_response_chunk_skips_remaining_hooks(captured_audit):
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    plugin = _AbortOnFirstChunk()
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [plugin]

    async with httpx.AsyncClient(transport=transport) as client:
        response = await forward_request(
            _make_request(),
            "v1/messages",
            http_client=client,
            upstream_base="http://upstream",
            plugin_host=host,
        )
        await _drain(response)

    # Mid-stream abort: completion + persisted hooks must NOT fire,
    # but the context still gets cleaned up via gen()'s finally.
    hooks_seen = {r["hook"] for r in captured_audit.rows if r["kind"] == "hook_invoked"}
    assert "on_response_complete" not in hooks_seen
    assert "on_persisted" not in hooks_seen
    assert host._exchange_contexts == {}


# -- plugin_host=None is the CP7 transparent shape -----------------------


@pytest.mark.asyncio
async def test_no_plugin_host_is_transparent_passthrough():
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    async with httpx.AsyncClient(transport=transport) as client:
        response = await forward_request(
            _make_request(headers={"x-api-key": "sk-ant-test"}),
            "v1/messages",
            http_client=client,
            upstream_base="http://upstream",
            plugin_host=None,
        )
        body = await _drain(response)

    assert len(captured) == 1
    assert captured[0].headers.get("x-api-key") == "sk-ant-test"
    # Upstream body streamed verbatim.
    assert b"event: ping" in body


# -- ADR-0027 axis 2: pre-SSE upstream failure path ----------------------


@pytest.mark.asyncio
async def test_axis2_non_200_short_circuits_with_status(captured_audit):
    """Upstream non-2xx before SSE: forward verbatim + skip SSE-only hooks.

    The CP9 row-write call site is gated on `has_request_scope`; this
    test exercises the no-auth-middleware shape, so it verifies the
    forwarder-level behaviour only — status forwarded, body forwarded,
    SSE-only plugin hooks bypassed, and the ctx cleaned up explicitly
    because the streaming generator's `finally` never runs on this
    path.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            headers={"content-type": "application/json"},
            content=b'{"error":{"type":"authentication_error","message":"invalid x-api-key"}}',
        )

    transport = httpx.MockTransport(handler)
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = []

    async with httpx.AsyncClient(transport=transport) as client:
        response = await forward_request(
            _make_request(headers={"x-api-key": "sk-ant-bogus"}),
            "v1/messages",
            http_client=client,
            upstream_base="http://upstream",
            plugin_host=host,
        )

    assert response.status_code == 401
    assert b"authentication_error" in response.body

    hooks_seen = {r["hook"] for r in captured_audit.rows if r["kind"] == "hook_invoked"}
    assert "on_upstream_response_start" not in hooks_seen
    assert "on_response_complete" not in hooks_seen
    assert host._exchange_contexts == {}


@pytest.mark.asyncio
async def test_axis2_upstream_connection_error_returns_503(captured_audit):
    """Upstream `ConnectError`: forwarder returns 503 + cleans up ctx.

    On this path `record_exchange_failure` writes the row with the
    documented `status_code=599` sentinel under the auth-middleware
    shape; here we verify the forwarder-level behaviour (no auth
    middleware: 503 returned, ctx cleaned, SSE-only hooks not fired).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("name resolution failed")

    transport = httpx.MockTransport(handler)
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = []

    async with httpx.AsyncClient(transport=transport) as client:
        response = await forward_request(
            _make_request(headers={"x-api-key": "sk-ant-test"}),
            "v1/messages",
            http_client=client,
            upstream_base="http://upstream",
            plugin_host=host,
        )

    assert response.status_code == 503
    assert host._exchange_contexts == {}
    hooks_seen = {r["hook"] for r in captured_audit.rows if r["kind"] == "hook_invoked"}
    assert "on_upstream_response_start" not in hooks_seen
