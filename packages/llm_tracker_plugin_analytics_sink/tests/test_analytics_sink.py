"""`AnalyticsSink` plugin tests (ADR-0038).

Contract surfaces:

1. ``on_request_received`` stashes the request body keyed by
   ``exchange_id``.
2. ``on_persisted`` builds + writes one analytics row per exchange.
   ADR-0038 retired the per-message UPSERT path; columns now include
   ``role``, ``request_jsonb``, ``system_prompt_jsonb``, and
   ``response_jsonb`` (renamed from ``response_json``).
3. A ``ctx`` without a parsed response still produces a valid row
   (NULL extractor-derived columns).
"""

from __future__ import annotations

import json
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


def _fake_engine(
    *,
    prev_conversation_id: str | None = None,
    prev_turn_seq: int | None = None,
    prev_system: object | None = None,
) -> tuple[MagicMock, AsyncMock]:
    """A MagicMock engine.

    Three SELECTs run before the INSERT, in order:
      1. chain lookup by first_msg_hash → returns a row with
         conversation_id, or None.
      2. last turn_seq in conversation → returns row.turn_seq or None.
      3. last non-null system_prompt_jsonb in conversation → returns
         row.system_prompt_jsonb or None.

    Pass any of `prev_*` to inject prior state. Anything not passed
    returns None.
    """
    conn = AsyncMock()

    chain_result = MagicMock()
    if prev_conversation_id is not None:
        chain_result.first = MagicMock(return_value=MagicMock(conversation_id=prev_conversation_id))
    else:
        chain_result.first = MagicMock(return_value=None)

    seq_result = MagicMock()
    if prev_turn_seq is not None:
        seq_result.first = MagicMock(return_value=MagicMock(turn_seq=prev_turn_seq))
    else:
        seq_result.first = MagicMock(return_value=None)

    system_result = MagicMock()
    if prev_system is not None:
        system_result.first = MagicMock(return_value=MagicMock(system_prompt_jsonb=prev_system))
    else:
        system_result.first = MagicMock(return_value=None)

    insert_result = MagicMock()
    insert_result.first = MagicMock(return_value=None)

    # The plugin emits at most three SELECTs then one INSERT. Some
    # paths skip the seq/system lookups (e.g. off-axis role) — the
    # remaining results are consumed in order regardless.
    results = [chain_result, seq_result, system_result, insert_result]

    async def _execute(_stmt, _params=None):
        if results:
            return results.pop(0)
        return insert_result

    conn.execute = AsyncMock(side_effect=_execute)

    @asynccontextmanager
    async def _begin():
        yield conn

    engine = MagicMock()
    engine.begin = _begin
    return engine, conn


def _insert_params(conn: AsyncMock) -> dict:
    """Return the param dict from the analytics-row INSERT.

    The INSERT is identifiable by carrying `request_jsonb` (only the
    INSERT statement binds this key under ADR-0038).
    """
    for call in reversed(conn.execute.await_args_list):
        params = call.args[1] if len(call.args) > 1 else None
        if isinstance(params, dict) and "request_jsonb" in params:
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
    # ADR-0038: response_jsonb replaces response_json (text → jsonb).
    assert params["response_jsonb"] == '{"model":"claude-haiku-4-5-20251001","content":[]}'
    assert "response_json" not in params
    assert params["input_tokens"] == 42
    # ADR-0038 columns:
    assert params["role"] == "user_input"
    # 2026-05-26 refinement: Rule-B collapse retired — single bare
    # text block is preserved as a one-element list.
    assert json.loads(params["request_jsonb"]) == [{"type": "text", "text": "hi"}]
    assert params["turn_seq"] == 1
    assert params["slash_commands"] is None
    assert isinstance(params["first_msg_hash"], str)
    assert len(params["first_msg_hash"]) == 16
    # Fresh conversation: conv_id = this row's id.
    assert params["conversation_id"] == params["id"]
    # Retired columns absent.
    assert "turn_kind" not in params
    assert "n_messages_at_request" not in params
    # No `system` field in the request → system_prompt_jsonb is None.
    assert params["system_prompt_jsonb"] is None
    # Stash cleared.
    assert "ex_test_01" not in plugin._stash


@pytest.mark.asyncio
async def test_missing_parsed_response_writes_nulls() -> None:
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
    assert params["response_jsonb"] is None
    assert params["role"] == "user_input"
    assert params["turn_seq"] == 1


@pytest.mark.asyncio
async def test_skip_when_org_id_missing() -> None:
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = b'{"model":"claude-x","messages":[]}'
    ctx = _make_ctx(request_body=body, org_id=None, parsed_response=None)

    await plugin.on_request_received("ex_no_org", ctx)
    await plugin.on_persisted("ex_no_org", ctx)

    assert conn.execute.await_count == 0


@pytest.mark.asyncio
async def test_tool_result_role_inherits_conversation_and_increments_seq() -> None:
    """messages[-1] with a tool_result block → role=tool_result;
    chain-lookup inherits the prior conversation; turn_seq += 1."""
    engine, conn = _fake_engine(
        prev_conversation_id="conv_root_ulid",
        prev_turn_seq=1,
    )
    plugin = AnalyticsSink(engine=engine)

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
    assert params["role"] == "tool_result"
    assert params["conversation_id"] == "conv_root_ulid"
    assert params["turn_seq"] == 2
    # request_jsonb is the tool_result block list verbatim.
    decoded = json.loads(params["request_jsonb"])
    assert isinstance(decoded, list)
    assert decoded[0]["type"] == "tool_result"


@pytest.mark.asyncio
async def test_identical_first_prompt_inherits_under_b_rule() -> None:
    """(B) rule: same first_msg_hash inherits the prior conv id."""
    engine, conn = _fake_engine(
        prev_conversation_id="conv_prev_ulid",
        prev_turn_seq=1,
    )
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_new", ctx)
    await plugin.on_persisted("ex_new", ctx)

    params = _insert_params(conn)
    assert params["role"] == "user_input"
    assert params["conversation_id"] == "conv_prev_ulid"
    assert params["conversation_id"] != params["id"]
    assert params["turn_seq"] == 2


@pytest.mark.asyncio
async def test_no_request_body_no_stash() -> None:
    plugin = AnalyticsSink(engine=None)
    ctx = HookContext(session_id="server", exchange_id="ex_x", mode="R")

    result = await plugin.on_request_received("ex_x", ctx)
    assert "ex_x" not in plugin._stash
    assert result.__class__.__name__ == "Pass"


@pytest.mark.asyncio
async def test_persist_fallback_recovers_when_body_arrives_late() -> None:
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    ctx = HookContext(session_id="server", exchange_id="ex_late", mode="R", user_opted_in=True)
    ctx.org_id = uuid.uuid4()
    await plugin.on_request_received("ex_late", ctx)
    assert "ex_late" not in plugin._stash

    body = b'{"model":"claude-x","messages":[{"role":"user","content":"hi"}]}'
    ctx._raw_request_body = body

    await plugin.on_persisted("ex_late", ctx)

    params = _insert_params(conn)
    assert params["exchange_id"] == "ex_late"
    assert params["role"] == "sidecar"  # bare string content → sidecar.
    assert json.loads(params["request_jsonb"]) == "hi"


@pytest.mark.asyncio
async def test_slash_commands_bound_as_json_string_not_python_list() -> None:
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
    assert isinstance(params["slash_commands"], str)
    assert json.loads(params["slash_commands"]) == ["compact"]


@pytest.mark.asyncio
async def test_slash_commands_none_passes_through_as_none() -> None:
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = b'{"model":"claude-x","messages":[{"role":"user","content":"hi"}]}'
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_nullslash", ctx)
    await plugin.on_persisted("ex_nullslash", ctx)

    params = _insert_params(conn)
    assert params["slash_commands"] is None


@pytest.mark.asyncio
async def test_session_opener_wrappers_stripped_from_request_jsonb() -> None:
    """ADR-0038: session-opener's leading `<system-reminder>` blocks
    are dropped from request_jsonb. The trailing bare text block
    survives as a one-element list (Rule-B collapse retired
    2026-05-26)."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":[{"role":"user","content":['
        b'{"type":"text","text":"<system-reminder>\\nAvailable agent types..."},'
        b'{"type":"text","text":"<system-reminder>\\nMCP Server Instructions..."},'
        b'{"type":"text","text":"hello"}'
        b"]}]}"
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_opener", ctx)
    await plugin.on_persisted("ex_opener", ctx)

    params = _insert_params(conn)
    assert params["role"] == "user_input"
    assert json.loads(params["request_jsonb"]) == [{"type": "text", "text": "hello"}]


@pytest.mark.asyncio
async def test_session_string_classifies_as_sidecar() -> None:
    """`<session>...</session>` string content → role=sidecar
    (2026-05-26 refinement folded the former `title_gen` role into
    `sidecar`), off-axis (turn_seq NULL)."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":'
        b'[{"role":"user","content":"<session>\\nhello\\n</session>"}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_title", ctx)
    await plugin.on_persisted("ex_title", ctx)

    params = _insert_params(conn)
    assert params["role"] == "sidecar"
    assert params["turn_seq"] is None
    assert json.loads(params["request_jsonb"]) == "<session>\nhello\n</session>"


@pytest.mark.asyncio
async def test_session_list_shape_classifies_as_sidecar() -> None:
    """Single bare text block carrying `<session>...</session>` →
    role=sidecar (was `title_gen` before the 2026-05-26
    refinement; regression coverage for the list-shape bug
    remains relevant since the same classifier branch is exercised)."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":'
        b'[{"role":"user","content":[{"type":"text","text":"<session>\\nhi\\n</session>"}]}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_title_list", ctx)
    await plugin.on_persisted("ex_title_list", ctx)

    params = _insert_params(conn)
    assert params["role"] == "sidecar"
    assert params["turn_seq"] is None


@pytest.mark.asyncio
async def test_sidecar_string_classifies_correctly() -> None:
    """SUGGESTION MODE / /compact summarize / step-away recap → sidecar,
    off-axis."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","messages":[{"role":"user","content":"hi"},'
        b'{"role":"assistant","content":[{"type":"text","text":"ok"}]},'
        b'{"role":"user","content":"[SUGGESTION MODE: ...]"}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_sidecar", ctx)
    await plugin.on_persisted("ex_sidecar", ctx)

    params = _insert_params(conn)
    assert params["role"] == "sidecar"
    assert params["turn_seq"] is None
    assert json.loads(params["request_jsonb"]) == "[SUGGESTION MODE: ...]"


@pytest.mark.asyncio
async def test_system_prompt_stored_on_first_exchange() -> None:
    """First exchange in a conversation (no prev row in the engine
    mock) → system field is stored verbatim."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","system":"You are Claude Code...",'
        b'"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_sys1", ctx)
    await plugin.on_persisted("ex_sys1", ctx)

    params = _insert_params(conn)
    assert params["system_prompt_jsonb"] is not None
    assert json.loads(params["system_prompt_jsonb"]) == "You are Claude Code..."


@pytest.mark.asyncio
async def test_system_prompt_stored_when_changed_from_prev() -> None:
    """If conversation has prior non-null system and current hash
    differs, store the new system."""
    engine, conn = _fake_engine(
        prev_conversation_id="conv_prev",
        prev_turn_seq=1,
        prev_system="Old system text",
    )
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","system":"NEW system text",'
        b'"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_sys_change", ctx)
    await plugin.on_persisted("ex_sys_change", ctx)

    params = _insert_params(conn)
    assert params["system_prompt_jsonb"] is not None
    assert json.loads(params["system_prompt_jsonb"]) == "NEW system text"


@pytest.mark.asyncio
async def test_system_prompt_billing_header_drift_treated_as_unchanged() -> None:
    """Claude Code's `x-anthropic-billing-header:` block drifts
    (cc_version, cch tokens) across exchanges without carrying any
    system-instruction content. The variation tracker must hash the
    stripped form, so a request whose only delta vs the prev stored
    system is the billing-header block stores NULL."""
    prev_stored = [{"type": "text", "text": "You are Claude Code..."}]
    engine, conn = _fake_engine(
        prev_conversation_id="conv_prev",
        prev_turn_seq=1,
        prev_system=prev_stored,
    )
    plugin = AnalyticsSink(engine=engine)

    body = json.dumps(
        {
            "model": "claude-x",
            "system": [
                {
                    "type": "text",
                    "text": (
                        "x-anthropic-billing-header: cc_version=2.1.151; "
                        "cc_entrypoint=cli; cch=NEWHASH;"
                    ),
                },
                {"type": "text", "text": "You are Claude Code..."},
            ],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        }
    ).encode()
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_billing_drift", ctx)
    await plugin.on_persisted("ex_billing_drift", ctx)

    params = _insert_params(conn)
    assert params["system_prompt_jsonb"] is None


@pytest.mark.asyncio
async def test_system_prompt_stored_form_has_billing_header_stripped() -> None:
    """First exchange in a conversation stores the system verbatim
    EXCEPT for `x-anthropic-billing-header:` telemetry blocks, which
    are dropped at the storage boundary so a future re-hash of the
    stored value matches the hash of any subsequent request."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = json.dumps(
        {
            "model": "claude-x",
            "system": [
                {
                    "type": "text",
                    "text": "x-anthropic-billing-header: cc_version=2.1.150; cch=f5075;",
                },
                {"type": "text", "text": "You are Claude Code, ..."},
            ],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        }
    ).encode()
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_strip_store", ctx)
    await plugin.on_persisted("ex_strip_store", ctx)

    params = _insert_params(conn)
    stored = json.loads(params["system_prompt_jsonb"])
    assert stored == [{"type": "text", "text": "You are Claude Code, ..."}]


@pytest.mark.asyncio
async def test_system_prompt_null_when_unchanged_from_prev() -> None:
    """Identical system as prev (same hash) → store NULL."""
    engine, conn = _fake_engine(
        prev_conversation_id="conv_prev",
        prev_turn_seq=1,
        prev_system="Same system text",
    )
    plugin = AnalyticsSink(engine=engine)

    body = (
        b'{"model":"claude-x","system":"Same system text",'
        b'"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]}'
    )
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_sys_same", ctx)
    await plugin.on_persisted("ex_sys_same", ctx)

    params = _insert_params(conn)
    assert params["system_prompt_jsonb"] is None


@pytest.mark.asyncio
async def test_session_id_extracted_from_metadata_user_id() -> None:
    """Claude Code packs the CLI session id into `metadata.user_id` as
    a JSON string; the plugin extracts `session_id` into its own column.
    Fixture value mirrors a real captured payload."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    user_id = json.dumps(
        {
            "device_id": "0" * 64,
            "account_uuid": "00000000-0000-0000-0000-000000000001",
            "session_id": "11111111-2222-3333-4444-555555555555",
        }
    )
    body = json.dumps(
        {
            "model": "claude-x",
            "metadata": {"user_id": user_id},
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        }
    ).encode()
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_sid", ctx)
    await plugin.on_persisted("ex_sid", ctx)

    params = _insert_params(conn)
    assert params["session_id"] == "11111111-2222-3333-4444-555555555555"


@pytest.mark.asyncio
async def test_session_id_none_when_metadata_absent() -> None:
    """No `metadata` field (or non-JSON / opaque user_id) → session_id
    stays NULL; other clients are not forced into the CC-specific shape."""
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    body = json.dumps(
        {
            "model": "claude-x",
            "metadata": {"user_id": "opaque-non-json-id"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        }
    ).encode()
    ctx = _make_ctx(request_body=body, org_id=uuid.uuid4(), parsed_response=None)

    await plugin.on_request_received("ex_no_sid", ctx)
    await plugin.on_persisted("ex_no_sid", ctx)

    params = _insert_params(conn)
    assert params["session_id"] is None


@pytest.mark.asyncio
async def test_insert_sql_uses_new_column_names() -> None:
    """The INSERT SQL writes response_jsonb / request_jsonb /
    system_prompt_jsonb / role; turn_kind / n_messages_at_request /
    response_json are gone."""
    from llm_tracker_plugin_analytics_sink.plugin import _INSERT_SQL

    sql = str(_INSERT_SQL)
    assert "response_jsonb" in sql
    assert "request_jsonb" in sql
    assert "system_prompt_jsonb" in sql
    assert "session_id" in sql
    assert "role" in sql
    assert "turn_kind" not in sql
    assert "n_messages_at_request" not in sql


@pytest.mark.asyncio
async def test_persist_skipped_when_body_never_arrives() -> None:
    engine, conn = _fake_engine()
    plugin = AnalyticsSink(engine=engine)

    ctx = HookContext(session_id="server", exchange_id="ex_never", mode="R", user_opted_in=True)
    ctx.org_id = uuid.uuid4()
    await plugin.on_request_received("ex_never", ctx)
    await plugin.on_persisted("ex_never", ctx)

    assert conn.execute.await_count == 0
