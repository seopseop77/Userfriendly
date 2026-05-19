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
    """A MagicMock engine whose `begin()` yields a captured AsyncMock connection.

    `conn.execute` returns a result whose `.first()` is None — sufficient
    for the fresh-conversation path (no prior same-hash row exists).
    """
    conn = AsyncMock()
    result = MagicMock()
    result.first = MagicMock(return_value=None)
    conn.execute = AsyncMock(return_value=result)

    @asynccontextmanager
    async def _begin():
        yield conn

    engine = MagicMock()
    engine.begin = _begin
    return engine, conn


def _insert_params(conn: AsyncMock) -> dict:
    """Return the parameter dict from the INSERT call (last execute)."""
    # The plugin runs a SELECT first (chain lookup), then the INSERT.
    # Distinguish by params dict size — INSERT has many keys.
    for call in reversed(conn.execute.await_args_list):
        params = call.args[1]
        if isinstance(params, dict) and "messages_json" in params:
            return params
    raise AssertionError("INSERT call not found")


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
    body = (
        b'{"model":"claude-haiku-4-5-20251001",'
        b'"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=org_uuid, parsed_response=parsed)

    await plugin.on_request_received("ex_test_01", ctx)
    await plugin.on_persisted("ex_test_01", ctx)

    params = _insert_params(conn)
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
    # Classification fields (migration 0014):
    assert params["turn_kind"] == "user_input_turn_start"
    assert params["turn_seq"] == 1
    assert params["slash_commands"] is None
    assert isinstance(params["first_msg_hash"], str)
    assert len(params["first_msg_hash"]) == 16
    # Fresh conversation: conversation_id == this row's id.
    assert params["conversation_id"] == params["id"]
    # Dropped columns absent (migration 0013).
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
    body = (
        b'{"model":"claude-x","messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=org_uuid, parsed_response=None)

    await plugin.on_request_received("ex_null", ctx)
    await plugin.on_persisted("ex_null", ctx)

    params = _insert_params(conn)
    assert params["model_requested"] == "claude-x"
    assert params["model_served"] is None
    assert params["input_tokens"] is None
    assert params["output_tokens"] is None
    assert params["cache_read_tokens"] is None
    assert params["cache_write_tokens"] is None
    assert params["stop_reason"] is None
    assert params["response_json"] is None
    assert params["turn_kind"] == "user_input_turn_start"
    assert params["turn_seq"] == 1


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


def _fake_engine_with_prev(
    *, prev_conversation_id: str, prev_messages: list
) -> tuple[MagicMock, AsyncMock]:
    """Engine whose chain-lookup SELECT returns a synthetic prior row.

    The plugin's `_resolve_conversation` runs two SELECTs in some
    paths (chain lookup + last-seq lookup). We model that by returning
    the prev row from the first SELECT and a synthetic turn_seq=1 row
    from the second.
    """
    conn = AsyncMock()

    prev_row = MagicMock(conversation_id=prev_conversation_id, msgs=prev_messages)
    prev_result = MagicMock()
    prev_result.first = MagicMock(return_value=prev_row)

    seq_row = MagicMock(turn_seq=1)
    seq_result = MagicMock()
    seq_result.first = MagicMock(return_value=seq_row)

    results = [prev_result, seq_result]

    async def _execute(_stmt, _params):
        # First call: chain lookup. Subsequent: last-seq lookup or INSERT.
        if results:
            return results.pop(0)
        return MagicMock()

    conn.execute = AsyncMock(side_effect=_execute)

    @asynccontextmanager
    async def _begin():
        yield conn

    engine = MagicMock()
    engine.begin = _begin
    return engine, conn


@pytest.mark.asyncio
async def test_tool_continuation_inherits_conversation_id() -> None:
    """tool_continuation request with same first_msg_hash and longer
    history inherits the prior row's conversation_id; turn_seq increments.
    """
    engine, conn = _fake_engine_with_prev(
        prev_conversation_id="conv_root_ulid",
        prev_messages=[{"role": "user", "content": "first"}],
    )
    plugin = AnalyticsSink(engine=engine)

    # Request: 3 messages, last is user-content with tool_result block.
    body = (
        b'{"model":"claude-x","messages":['
        b'{"role":"user","content":[{"type":"text","text":"first"}]},'
        b'{"role":"assistant","content":[{"type":"text","text":"ok"}]},'
        b'{"role":"user","content":[{"type":"tool_result","tool_use_id":"t","content":"x"}]}'
        b"]}"
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_cont", ctx)
    await plugin.on_persisted("ex_cont", ctx)

    params = _insert_params(conn)
    assert params["turn_kind"] == "tool_continuation"
    # Inherits prev conversation_id (n=3 > prev n=1).
    assert params["conversation_id"] == "conv_root_ulid"
    # turn_seq = prev seq (1) + 1.
    assert params["turn_seq"] == 2


@pytest.mark.asyncio
async def test_identical_first_prompt_after_clear_starts_new_conversation() -> None:
    """If a request with n=1 finds a prior same-hash row whose n>=1,
    it starts a new conversation rather than inheriting.
    """
    engine, conn = _fake_engine_with_prev(
        prev_conversation_id="conv_prev_ulid",
        # Prior row was a long-running conversation that ended.
        prev_messages=[{"role": "user", "content": "hi"}] * 10,
    )
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_new", ctx)
    await plugin.on_persisted("ex_new", ctx)

    params = _insert_params(conn)
    assert params["turn_kind"] == "user_input_turn_start"
    # New conversation: conversation_id == this row's id (NOT prev's).
    assert params["conversation_id"] == params["id"]
    assert params["conversation_id"] != "conv_prev_ulid"
    assert params["turn_seq"] == 1


@pytest.mark.asyncio
async def test_no_request_body_no_stash() -> None:
    """If `request_text()` is None (degraded ceiling, no body), nothing is stashed."""
    plugin = AnalyticsSink(engine=None)
    ctx = HookContext(session_id="server", exchange_id="ex_x", mode="R")

    result = await plugin.on_request_received("ex_x", ctx)
    assert "ex_x" not in plugin._stash
    assert result.__class__.__name__ == "Pass"


@pytest.mark.asyncio
async def test_persist_fallback_recovers_when_body_arrives_late() -> None:
    """Stash miss at `on_request_received` is recovered by re-reading
    the body at `on_persisted`. This guards against the forwarder
    populating `_raw_request_body` after the first hook fires.
    """
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    # First hook: ctx has no body yet — stash miss.
    ctx = HookContext(
        session_id="server", exchange_id="ex_late", mode="R", user_opted_in=True
    )
    ctx.org_id = uuid.uuid4()
    await plugin.on_request_received("ex_late", ctx)
    assert "ex_late" not in plugin._stash

    # Body lands before on_persisted (simulating the forwarder
    # finishing the body read between the two hooks).
    body = b'{"model":"claude-x","messages":[{"role":"user","content":"hi"}]}'
    ctx._raw_request_body = body

    await plugin.on_persisted("ex_late", ctx)

    # INSERT fires from the fallback path — row is recovered.
    params = _insert_params(conn)
    assert params["exchange_id"] == "ex_late"
    assert params["messages_json"] == body.decode("utf-8")


@pytest.mark.asyncio
async def test_slash_commands_bound_as_json_string_not_python_list() -> None:
    """Regression: live `analytics_sink.insert_failed` 2026-05-19 against
    exchange 01KRZARYVBNAN9XCPNB8N8BAVT raised
    `'list' object has no attribute 'encode'` because asyncpg's raw-SQL
    path (sa.text) has no column-type info and cannot encode a Python
    list as JSONB. The plugin must JSON-encode the value before binding;
    the INSERT then casts it to jsonb in SQL.
    """
    import json as _json

    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":[{"role":"user","content":['
        b'{"type":"text","text":"<command-name>/compact</command-name>"},'
        b'{"type":"text","text":"resume after compact"}'
        b']}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_slash", ctx)
    await plugin.on_persisted("ex_slash", ctx)

    params = _insert_params(conn)
    assert isinstance(params["slash_commands"], str), (
        "slash_commands must be JSON-encoded for asyncpg JSONB binding"
    )
    assert _json.loads(params["slash_commands"]) == ["compact"]


@pytest.mark.asyncio
async def test_slash_commands_none_passes_through_as_none() -> None:
    """Null slash_commands must remain Python None (not the string 'null')
    so the JSONB column stores SQL NULL.
    """
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = b'{"model":"claude-x","messages":[{"role":"user","content":"hi"}]}'
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_nullslash", ctx)
    await plugin.on_persisted("ex_nullslash", ctx)

    params = _insert_params(conn)
    assert params["slash_commands"] is None


@pytest.mark.asyncio
async def test_persist_skipped_when_body_never_arrives() -> None:
    """If neither hook can read the body, on_persisted bails out
    cleanly (no INSERT, no exception).
    """
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    ctx = HookContext(
        session_id="server", exchange_id="ex_never", mode="R", user_opted_in=True
    )
    ctx.org_id = uuid.uuid4()
    await plugin.on_request_received("ex_never", ctx)
    await plugin.on_persisted("ex_never", ctx)

    assert conn.execute.await_count == 0
