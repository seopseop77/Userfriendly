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
    """Return the parameter dict from the analytics-row INSERT call.

    The plugin runs (in order) a chain-lookup SELECT, optional
    last-seq SELECT, N per-message UPSERTs, then the analytics-row
    INSERT. The INSERT is the only call carrying `n_messages_at_request`.
    """
    for call in reversed(conn.execute.await_args_list):
        params = call.args[1]
        if isinstance(params, dict) and "n_messages_at_request" in params:
            return params
    raise AssertionError("INSERT call not found")


def _upsert_calls(conn: AsyncMock) -> list[dict]:
    """Return the parameter dicts from the conversation_messages UPSERTs."""
    return [
        call.args[1]
        for call in conn.execute.await_args_list
        if isinstance(call.args[1], dict) and "msg_index" in call.args[1]
    ]


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
    # messages_json column dropped in migration 0015; the pointer
    # `n_messages_at_request` replaces it. Body itself lands in the
    # conversation_messages UPSERTs (see test_messages_upserted_*).
    assert "messages_json" not in params
    assert params["n_messages_at_request"] == 1
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
    assert params["n_messages_at_request"] == 1
    assert "messages_json" not in params


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
    """tool_continuation request with same first_msg_hash inherits the
    prior row's conversation_id; turn_seq increments off the last seq.
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
    # (B) rule: same first_msg_hash always inherits prev conv id.
    assert params["conversation_id"] == "conv_root_ulid"
    # turn_seq = MAX prev seq (1) + 1.
    assert params["turn_seq"] == 2


@pytest.mark.asyncio
async def test_identical_first_prompt_inherits_under_b_rule() -> None:
    """(B) rule (2026-05-19): same first_msg_hash always inherits the
    prior conversation_id regardless of message count. The trade-off --
    that two genuinely-separate sessions sharing an identical first
    prompt fold into one conversation -- was an explicit design call
    to avoid splitting a single Claude Code session into many
    conversations whenever an internal_subprompt inflates the prev
    row's message count past the next user turn's.
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
    # (B): inherits the prior conv id rather than starting fresh.
    assert params["conversation_id"] == "conv_prev_ulid"
    assert params["conversation_id"] != params["id"]
    # Cumulative seq: prev MAX was 1 (mock returns turn_seq=1), so 2.
    assert params["turn_seq"] == 2


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
    ctx = HookContext(session_id="server", exchange_id="ex_late", mode="R", user_opted_in=True)
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
    assert params["n_messages_at_request"] == 1
    # And the recovered body produced one conversation_messages UPSERT.
    upserts = _upsert_calls(conn)
    assert len(upserts) == 1
    assert upserts[0]["msg_index"] == 0


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
        b"]}]}"
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
async def test_messages_upserted_one_per_index() -> None:
    """Each `messages[idx]` produces one UPSERT into conversation_messages
    with the correct conversation_id (= row's conv id) and msg_index.
    """
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":['
        b'{"role":"user","content":[{"type":"text","text":"first"}]},'
        b'{"role":"assistant","content":[{"type":"text","text":"ok"}]},'
        b'{"role":"user","content":[{"type":"tool_result","tool_use_id":"t","content":"x"}]}'
        b"]}"
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_three", ctx)
    await plugin.on_persisted("ex_three", ctx)

    upserts = _upsert_calls(conn)
    assert [u["msg_index"] for u in upserts] == [0, 1, 2]

    params = _insert_params(conn)
    # Every UPSERT carries the same conversation_id as the row's.
    assert all(u["conversation_id"] == params["conversation_id"] for u in upserts)
    assert params["n_messages_at_request"] == 3


@pytest.mark.asyncio
async def test_normalization_applied_at_upsert_boundary() -> None:
    """Rule B (single bare text block array → bare string) is applied
    in the UPSERT payload — `content_jsonb` is a JSON-encoded string,
    not an array.
    """
    import json as _json

    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":['
        b'{"role":"user","content":[{"type":"text","text":"hello"}]}'
        b"]}"
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_norm", ctx)
    await plugin.on_persisted("ex_norm", ctx)

    upserts = _upsert_calls(conn)
    assert len(upserts) == 1
    # content_jsonb is JSON-encoded; the inner value is the bare string.
    assert _json.loads(upserts[0]["content_jsonb"]) == "hello"
    # ADR-0037: role carries the 5-value display vocab. A list-content
    # user message with one real text block classifies as `user_input`.
    assert upserts[0]["role"] == "user_input"


@pytest.mark.asyncio
async def test_upserts_carry_display_roles() -> None:
    """ADR-0037: each UPSERT's `role` reflects the 5-value display
    vocab (system_prompt / user_input / title_gen / model_output /
    assistant). A mixed `messages` array (bare user text — no split,
    assistant turn, tool_result continuation, SUGGESTION sidecar,
    user follow-up) produces one distinct role per index.
    """
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    # 5 messages — index 0 is bare user text (no wrapper) so no split.
    body = (
        b'{"model":"claude-x","messages":['
        # msg 0: user-typed (single text block, no leading wrapper)
        b'{"role":"user","content":[{"type":"text","text":"first"}]},'
        # msg 1: assistant response
        b'{"role":"assistant","content":[{"type":"text","text":"ok"}]},'
        # msg 2: user tool_result continuation
        b'{"role":"user","content":[{"type":"tool_result","tool_use_id":"t","content":"x"}]},'
        # msg 3: SUGGESTION MODE sidecar (string content)
        b'{"role":"user","content":"[SUGGESTION MODE: ...]"},'
        # msg 4: user-typed follow-up
        b'{"role":"user","content":[{"type":"text","text":"next"}]}'
        b"]}"
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_mix", ctx)
    await plugin.on_persisted("ex_mix", ctx)

    upserts = _upsert_calls(conn)
    by_index = {u["msg_index"]: u["role"] for u in upserts}
    assert by_index == {
        0: "user_input",
        1: "model_output",
        2: "assistant",  # tool_continuation folded into assistant under ADR-0037
        3: "assistant",  # SUGGESTION MODE folded into assistant under ADR-0037
        4: "user_input",
    }


@pytest.mark.asyncio
async def test_session_opener_splits_into_system_prompt_and_user_input() -> None:
    """ADR-0037 split: `messages[0]` whose content begins with
    `<system-reminder>` wrappers expands to two stored rows.
    Subsequent API messages shift msg_index by +1 and
    `n_messages_at_request` is bumped to match the helper view's
    row-count filter.
    """
    import json as _json

    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":['
        b'{"role":"user","content":['
        b'{"type":"text","text":"<system-reminder>\\nAvailable agent types..."},'
        b'{"type":"text","text":"hello"}'
        b"]},"
        b'{"role":"assistant","content":[{"type":"text","text":"ok"}]}'
        b"]}"
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_split", ctx)
    await plugin.on_persisted("ex_split", ctx)

    upserts = _upsert_calls(conn)
    by_index = {u["msg_index"]: u for u in upserts}
    # Three stored rows from two API messages (split applied at idx 0).
    assert sorted(by_index) == [0, 1, 2]
    assert by_index[0]["role"] == "system_prompt"
    sys_content = _json.loads(by_index[0]["content_jsonb"])
    assert isinstance(sys_content, list)
    assert sys_content[0]["text"].startswith("<system-reminder>")
    assert by_index[1]["role"] == "user_input"
    # Single bare text block normalises to a bare string.
    assert _json.loads(by_index[1]["content_jsonb"]) == "hello"
    assert by_index[2]["role"] == "model_output"

    params = _insert_params(conn)
    # API delivered 2 messages, split yields 3 stored rows.
    assert params["n_messages_at_request"] == 3


@pytest.mark.asyncio
async def test_title_gen_string_classifies_correctly() -> None:
    """`<session>...</session>` string payload at messages[0] →
    role=`title_gen`. The split helper returns None for string content,
    so no msg_index shift."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":['
        b'{"role":"user","content":"<session>\\nhello\\n</session>"}'
        b"]}"
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_title", ctx)
    await plugin.on_persisted("ex_title", ctx)

    upserts = _upsert_calls(conn)
    assert len(upserts) == 1
    assert upserts[0]["msg_index"] == 0
    assert upserts[0]["role"] == "title_gen"


@pytest.mark.asyncio
async def test_upsert_sql_uses_priority_do_update() -> None:
    """ADR-0037: the UPSERT SQL allows real-content arrivals to
    displace a stored `title_gen` sidecar placeholder. We assert the
    SQL string rather than against a live DB — keeps the contract
    visible at the plugin layer; full UPSERT semantics are exercised
    by integration tests downstream.
    """
    from llm_tracker_plugin_analytics_sink.plugin import _UPSERT_MESSAGE_SQL

    sql = str(_UPSERT_MESSAGE_SQL)
    # DO UPDATE replaces the prior DO NOTHING policy.
    assert "DO UPDATE" in sql
    assert "DO NOTHING" not in sql
    # Stored sidecar placeholder under ADR-0037 is `title_gen` only.
    assert "'title_gen'" in sql
    # Pre-ADR-0037 placeholder names no longer appear.
    assert "'internal_subprompt'" not in sql
    assert "'claude_manage_probe'" not in sql
    # Real-content arrivals — the 4 values that can displace title_gen.
    assert "'system_prompt'" in sql
    assert "'user_input'" in sql
    assert "'model_output'" in sql
    assert "'assistant'" in sql


@pytest.mark.asyncio
async def test_persist_skipped_when_body_never_arrives() -> None:
    """If neither hook can read the body, on_persisted bails out
    cleanly (no INSERT, no exception).
    """
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    ctx = HookContext(session_id="server", exchange_id="ex_never", mode="R", user_opted_in=True)
    ctx.org_id = uuid.uuid4()
    await plugin.on_request_received("ex_never", ctx)
    await plugin.on_persisted("ex_never", ctx)

    assert conn.execute.await_count == 0
