"""`AnalyticsSink` plugin tests.

Three contract surfaces:

1. ``on_request_received`` stashes the request body keyed by
   ``exchange_id``.
2. ``on_persisted`` builds + writes a row whose columns line up with
   the SQL placeholders. The engine is mocked; assertions inspect the
   parameters dict the plugin hands to ``execute``.
3. A ``ctx`` without a parsed response (``response_usage()`` and
   ``response_content_json()`` both ``None``) still produces a valid
   row — the extractor-derived columns are NULL but the INSERT still
   fires (ADR-0027 axis 1: NULL is data).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from llm_tracker_plugin_analytics_sink.plugin import AnalyticsSink
from llm_tracker_sdk import HookContext


def _make_ctx(
    *,
    request_body: bytes,
    org_id: uuid.UUID | None,
    parsed_response: object | None,
) -> HookContext:
    """Build a HookContext shaped the way the server forwarder does."""
    ctx = HookContext(
        session_id="server",
        exchange_id="ex_test_01",
        mode="R",
        user_opted_in=True,
        _raw_request_body=request_body,
    )
    ctx.org_id = org_id
    ctx._parsed_response = parsed_response
    return ctx


def _fake_engine() -> tuple[MagicMock, AsyncMock]:
    """A MagicMock engine whose `begin()` yields a captured AsyncMock connection."""
    conn = AsyncMock()
    conn.execute = AsyncMock()

    @asynccontextmanager
    async def _begin():
        yield conn

    engine = MagicMock()
    engine.begin = _begin
    return engine, conn


@pytest.mark.asyncio
async def test_request_stashed_on_received() -> None:
    plugin = AnalyticsSink(engine=None)
    body = (
        b'{"model":"claude-haiku-4-5-20251001","system":"be brief",'
        b'"messages":[{"role":"user","content":"hi"}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    result = await plugin.on_request_received("ex_test_01", ctx)

    # Stash carries the raw request body as a string.
    assert plugin._stash["ex_test_01"] == body.decode("utf-8")
    assert result.__class__.__name__ == "Pass"


@pytest.mark.asyncio
async def test_row_written_on_persisted_with_parsed_response() -> None:
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    usage = MagicMock()
    usage.model_served = "claude-haiku-4-5-20251001"
    usage.input_tokens = 42
    usage.output_tokens = 15
    usage.cache_read_tokens = 7
    usage.cache_write_tokens = 3
    usage.stop_reason = "end_turn"
    parsed = MagicMock()
    parsed.usage = usage
    parsed.response_json = '{"model":"claude-haiku-4-5-20251001","content":[]}'

    org_uuid = uuid.uuid4()
    body = b'{"model":"claude-haiku-4-5-20251001","messages":[]}'
    ctx = _make_ctx(request_body=body, org_id=org_uuid, parsed_response=parsed)

    await plugin.on_request_received("ex_test_01", ctx)
    await plugin.on_persisted("ex_test_01", ctx)

    # Exactly one INSERT against the fake conn.
    assert conn.execute.await_count == 1
    _stmt, params = conn.execute.await_args.args
    assert params["exchange_id"] == "ex_test_01"
    assert params["org_id"] == org_uuid
    assert params["model_requested"] == "claude-haiku-4-5-20251001"
    assert params["model_served"] == "claude-haiku-4-5-20251001"
    assert params["messages_json"] == body.decode("utf-8")
    assert params["response_json"] == '{"model":"claude-haiku-4-5-20251001","content":[]}'
    assert params["input_tokens"] == 42
    assert params["output_tokens"] == 15
    assert params["cache_read_tokens"] == 7
    assert params["cache_write_tokens"] == 3
    assert params["stop_reason"] == "end_turn"
    # system_prompt and tool_call_count no longer exist (dropped in migration 0013).
    assert "system_prompt" not in params
    assert "tool_call_count" not in params
    # Stash is cleared after the write.
    assert "ex_test_01" not in plugin._stash


@pytest.mark.asyncio
async def test_missing_parsed_response_writes_nulls() -> None:
    """Plugin still inserts a row when the extractor produced no usage."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    org_uuid = uuid.uuid4()
    body = b'{"model":"claude-x","messages":[{"role":"user","content":"hi"}]}'
    ctx = _make_ctx(request_body=body, org_id=org_uuid, parsed_response=None)

    await plugin.on_request_received("ex_null", ctx)
    await plugin.on_persisted("ex_null", ctx)

    assert conn.execute.await_count == 1
    _stmt, params = conn.execute.await_args.args
    assert params["model_requested"] == "claude-x"
    assert params["model_served"] is None
    assert params["input_tokens"] is None
    assert params["output_tokens"] is None
    assert params["cache_read_tokens"] is None
    assert params["cache_write_tokens"] is None
    assert params["stop_reason"] is None
    assert params["response_json"] is None


@pytest.mark.asyncio
async def test_skip_when_org_id_missing() -> None:
    """Defensive: org-less ctx skips the INSERT rather than crashing."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = b'{"model":"claude-x","messages":[]}'
    ctx = _make_ctx(request_body=body, org_id=None, parsed_response=None)

    await plugin.on_request_received("ex_no_org", ctx)
    await plugin.on_persisted("ex_no_org", ctx)

    assert conn.execute.await_count == 0


@pytest.mark.asyncio
async def test_no_request_body_no_stash() -> None:
    """If `request_text()` is None (degraded ceiling, no body), nothing is stashed."""
    plugin = AnalyticsSink(engine=None)
    ctx = HookContext(session_id="server", exchange_id="ex_x", mode="R")

    result = await plugin.on_request_received("ex_x", ctx)
    assert "ex_x" not in plugin._stash
    assert result.__class__.__name__ == "Pass"
