"""CP7 -- Anthropic credential pass-through + log scrubbing (ADR-0020 Axis 2).

Two surfaces under test:

1. ``forward_request`` propagates the Anthropic credential header
   (``x-api-key`` / ``anthropic-api-key``) to the outbound request,
   and strips the llm-tracker bearer (``Authorization``) which was
   already consumed by ``AuthMiddleware``.

2. ``scrub_credential_processor`` redacts credentials from any
   structlog event, by header-name lookup and by value-prefix match
   on the Anthropic API-key shape (``sk-ant-...``). The configured
   logging chain wires it in so the credential bytes never reach
   stdout.

No PostgreSQL fixture: both surfaces are independent of the database.
The forwarder uses ``httpx.MockTransport`` to capture the outbound
request without hitting the network.
"""

from __future__ import annotations

import io
import json
import logging as stdlib_logging

import httpx
import pytest
import structlog
from llm_tracker_server.logging import configure_logging
from llm_tracker_server.proxy import (
    REDACTED,
    forward_request,
    scrub_credential_processor,
)
from starlette.requests import Request

ANTHROPIC_SECRET = "sk-ant-api03-abcdef0123456789"
TRACKER_BEARER = "lts_localcoolio"


def _make_request(
    *,
    method: str = "POST",
    path: str = "/v1/messages",
    headers: dict[str, str] | None = None,
    body: bytes = b'{"model":"claude-x","messages":[]}',
    query: str = "",
) -> Request:
    """Build a minimal Starlette Request from a raw ASGI scope.

    Using the real Request class (not a mock) keeps the test honest
    against any header-normalisation behaviour in
    :func:`forward_request`.
    """
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
        "query_string": query.encode("latin-1"),
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
            content=b"event: ping\ndata: {}\n\n",
        )

    return handler


async def _drain(response):
    """Consume the StreamingResponse body so the MockTransport handler runs."""
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    return body


@pytest.mark.asyncio
async def test_outbound_carries_x_api_key() -> None:
    """Inbound `x-api-key` reaches the upstream request unchanged."""
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    async with httpx.AsyncClient(transport=transport) as client:
        request = _make_request(
            headers={
                "x-api-key": ANTHROPIC_SECRET,
                "content-type": "application/json",
            },
        )
        response = await forward_request(
            request, "v1/messages", http_client=client, upstream_base="http://upstream"
        )
        await _drain(response)

    assert len(captured) == 1
    outbound = captured[0]
    assert outbound.headers.get("x-api-key") == ANTHROPIC_SECRET
    assert outbound.method == "POST"
    assert str(outbound.url) == "http://upstream/v1/messages"


@pytest.mark.asyncio
async def test_outbound_carries_anthropic_api_key_alternate() -> None:
    """The documented alternate header name `anthropic-api-key` passes through too."""
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    async with httpx.AsyncClient(transport=transport) as client:
        request = _make_request(
            headers={"anthropic-api-key": ANTHROPIC_SECRET},
        )
        response = await forward_request(
            request, "v1/messages", http_client=client, upstream_base="http://upstream"
        )
        await _drain(response)

    assert captured[0].headers.get("anthropic-api-key") == ANTHROPIC_SECRET


@pytest.mark.asyncio
async def test_outbound_strips_authorization_bearer() -> None:
    """`Authorization: Bearer <our token>` must NOT reach Anthropic."""
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    async with httpx.AsyncClient(transport=transport) as client:
        request = _make_request(
            headers={
                "authorization": f"Bearer {TRACKER_BEARER}",
                "x-api-key": ANTHROPIC_SECRET,
            },
        )
        response = await forward_request(
            request, "v1/messages", http_client=client, upstream_base="http://upstream"
        )
        await _drain(response)

    outbound = captured[0]
    assert "authorization" not in {k.lower() for k in outbound.headers}
    # The Anthropic credential survives the strip pass.
    assert outbound.headers.get("x-api-key") == ANTHROPIC_SECRET


@pytest.mark.asyncio
async def test_query_string_is_preserved() -> None:
    """Query strings round-trip to the upstream URL."""
    captured: list[httpx.Request] = []
    transport = httpx.MockTransport(_capture_handler(captured))
    async with httpx.AsyncClient(transport=transport) as client:
        request = _make_request(
            headers={"x-api-key": ANTHROPIC_SECRET},
            query="beta=tool-use-2024-04-04",
        )
        response = await forward_request(
            request, "v1/messages", http_client=client, upstream_base="http://upstream"
        )
        await _drain(response)

    assert str(captured[0].url) == "http://upstream/v1/messages?beta=tool-use-2024-04-04"


def test_scrub_processor_redacts_credential_header_key() -> None:
    """Top-level credential-header keys are redacted."""
    event = {
        "event": "proxy.forward",
        "x-api-key": ANTHROPIC_SECRET,
        "anthropic-api-key": ANTHROPIC_SECRET,
        "X-Api-Key": ANTHROPIC_SECRET,
        "method": "POST",
    }
    scrubbed = scrub_credential_processor(None, "info", event)
    assert scrubbed["x-api-key"] == REDACTED
    assert scrubbed["anthropic-api-key"] == REDACTED
    assert scrubbed["X-Api-Key"] == REDACTED
    assert scrubbed["method"] == "POST"


def test_scrub_processor_redacts_nested_credential_header() -> None:
    """Credential header keys inside nested dicts are redacted."""
    event = {
        "event": "proxy.forward",
        "headers": {"x-api-key": ANTHROPIC_SECRET, "user-agent": "claude-cli/1.0"},
    }
    scrubbed = scrub_credential_processor(None, "info", event)
    assert scrubbed["headers"]["x-api-key"] == REDACTED
    assert scrubbed["headers"]["user-agent"] == "claude-cli/1.0"


def test_scrub_processor_redacts_secret_value_anywhere() -> None:
    """Any string starting with `sk-ant-` is redacted no matter the key."""
    event = {
        "event": "proxy.forward",
        "leaked_blob": ANTHROPIC_SECRET,
        "deeply": {"nested": [ANTHROPIC_SECRET, "safe-value"]},
    }
    scrubbed = scrub_credential_processor(None, "info", event)
    assert scrubbed["leaked_blob"] == REDACTED
    assert scrubbed["deeply"]["nested"] == [REDACTED, "safe-value"]


def test_scrub_processor_does_not_mutate_input() -> None:
    """The processor returns a new dict; callers can still inspect the original."""
    event = {"x-api-key": ANTHROPIC_SECRET, "method": "POST"}
    scrubbed = scrub_credential_processor(None, "info", event)
    assert scrubbed is not event
    assert event["x-api-key"] == ANTHROPIC_SECRET


def test_configured_logging_chain_redacts_credential_from_stdout() -> None:
    """End-to-end: configure_logging() emits scrubbed JSON to stdlib logging.

    Replaces the stdlib root handler with a StringIO sink so we can
    assert the rendered bytes never carry the credential. The
    ``forwarded_credential`` flag in the proxy log is the audit signal
    we *do* expect to see.
    """
    buffer = io.StringIO()
    root = stdlib_logging.getLogger()
    prior_handlers = root.handlers[:]
    prior_level = root.level
    handler = stdlib_logging.StreamHandler(buffer)
    handler.setFormatter(stdlib_logging.Formatter("%(message)s"))
    try:
        configure_logging("INFO")
        root.handlers = [handler]
        root.setLevel(stdlib_logging.INFO)

        log = structlog.get_logger("test_credential_passthrough")
        log.info(
            "proxy.forward",
            method="POST",
            path="v1/messages",
            forwarded_credential=True,
            # Deliberately attempt to leak through several vectors that
            # a careless future caller might use.
            headers={"x-api-key": ANTHROPIC_SECRET},
            leaked_blob=ANTHROPIC_SECRET,
        )
        handler.flush()
    finally:
        root.handlers = prior_handlers
        root.setLevel(prior_level)

    rendered = buffer.getvalue()
    assert ANTHROPIC_SECRET not in rendered
    # Exactly one JSON line; parse it to confirm the audit signal landed.
    line = rendered.strip().splitlines()[-1]
    payload = json.loads(line)
    assert payload["forwarded_credential"] is True
    assert payload["headers"]["x-api-key"] == REDACTED
    assert payload["leaked_blob"] == REDACTED
