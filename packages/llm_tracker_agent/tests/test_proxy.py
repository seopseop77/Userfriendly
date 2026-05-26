"""Proxy: token injection, hop-by-hop stripping, fail-closed (ADR-0024)."""

from __future__ import annotations

import httpx
import pytest
from llm_tracker_agent.config import Config
from llm_tracker_agent.proxy import make_proxy_app

CONFIG = Config(
    server_url="https://central.test",
    token="lts_test_token",
    local_port=18080,
)


def _capture_transport() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            content=b"OK",
            headers={"content-type": "text/plain"},
        )

    return httpx.MockTransport(handler), captured


def _unreachable_transport() -> httpx.MockTransport:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated central server down")

    return httpx.MockTransport(handler)


async def _post_through_app(
    app, *, path: str, content: bytes, headers: dict[str, str] | None = None
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://agent.test") as client:
        return await client.post(path, content=content, headers=headers or {})


@pytest.mark.asyncio
async def test_injects_tracker_token() -> None:
    transport, captured = _capture_transport()
    upstream = httpx.AsyncClient(transport=transport, base_url=CONFIG.server_url)
    app = make_proxy_app(CONFIG, client=upstream)
    try:
        resp = await _post_through_app(app, path="/v1/messages", content=b'{"hi":1}')
    finally:
        await upstream.aclose()

    assert resp.status_code == 200
    assert len(captured) == 1
    assert captured[0].headers.get("x-llm-tracker-token") == "lts_test_token"


@pytest.mark.asyncio
async def test_strips_hop_by_hop() -> None:
    transport, captured = _capture_transport()
    upstream = httpx.AsyncClient(transport=transport, base_url=CONFIG.server_url)
    app = make_proxy_app(CONFIG, client=upstream)
    try:
        await _post_through_app(
            app,
            path="/v1/messages",
            content=b'{"hi":1}',
            headers={"transfer-encoding": "chunked", "connection": "close"},
        )
    finally:
        await upstream.aclose()

    outbound = {k.lower(): v for k, v in captured[0].headers.items()}
    # httpx re-derives host from base_url (we stripped the inbound "agent.test").
    assert outbound["host"] == "central.test"
    # The inbound's hop-by-hop values do not leak through. httpx may re-add
    # its own connection-management headers; what matters is that the
    # inbound's "chunked" / "close" values are not forwarded verbatim.
    assert outbound.get("transfer-encoding") != "chunked"
    assert outbound.get("connection") != "close"
    # httpx re-computes content-length from the new body, not from inbound.
    assert outbound["content-length"] == str(len(b'{"hi":1}'))


class _MidStreamFailStream(httpx.AsyncByteStream):
    """Yields a single chunk then raises mid-stream, as a chunked-transfer
    upstream that closes the TCP connection before terminating the body."""

    async def __aiter__(self):
        yield b"partial"
        raise httpx.RemoteProtocolError("simulated mid-stream close")

    async def aclose(self) -> None:
        return None


class _MidStreamFailTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            stream=_MidStreamFailStream(),
        )


@pytest.mark.asyncio
async def test_swallows_midstream_upstream_close() -> None:
    upstream = httpx.AsyncClient(
        transport=_MidStreamFailTransport(),
        base_url=CONFIG.server_url,
    )
    app = make_proxy_app(CONFIG, client=upstream)
    try:
        resp = await _post_through_app(app, path="/v1/messages", content=b'{"hi":1}')
    finally:
        await upstream.aclose()

    # Status + headers already shipped; partial body reaches the client and the
    # ASGI app terminates the generator cleanly (no 500, no traceback).
    assert resp.status_code == 200
    assert resp.content == b"partial"


@pytest.mark.asyncio
async def test_fail_closed_on_server_unreachable() -> None:
    upstream = httpx.AsyncClient(
        transport=_unreachable_transport(),
        base_url=CONFIG.server_url,
    )
    app = make_proxy_app(CONFIG, client=upstream)
    try:
        resp = await _post_through_app(app, path="/v1/messages", content=b'{"hi":1}')
    finally:
        await upstream.aclose()

    assert resp.status_code == 503
    assert resp.json() == {"detail": "llm-tracker central server unreachable"}
