"""Lifecycle tests for `SupabaseSinkPlugin`.

We construct the plugin with an injected `client=` and exercise the
chunk → complete → queue → flusher path with a stubbed
`SupabaseSinkClient` whose `submit` we control.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from llm_tracker_plugin_supabase_sink import (
    ExchangeRecord,
    SubmitOutcome,
    SupabaseSinkPlugin,
)
from llm_tracker_sdk import HookContext

# -- fixtures / stubs -------------------------------------------------------


class _StubClient:
    """Records `submit` calls; returns canned outcomes."""

    def __init__(self, outcomes: list[SubmitOutcome] | None = None) -> None:
        self._outcomes = list(outcomes or [])
        self.submitted: list[ExchangeRecord] = []

    async def submit(self, record: ExchangeRecord) -> SubmitOutcome:
        self.submitted.append(record)
        if not self._outcomes:
            return SubmitOutcome.OK
        return self._outcomes.pop(0)


def _ctx(
    *,
    exchange_id: str = "ex-1",
    session_id: str = "sess-1",
    mode: str = "R",
    user_opted_in: bool = True,
    request_body: bytes | None = None,
) -> HookContext:
    return HookContext(
        session_id=session_id,
        exchange_id=exchange_id,
        mode=mode,
        user_opted_in=user_opted_in,
        _raw_request_body=request_body,
    )


def _sse_lf(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def _full_response_stream() -> list[bytes]:
    """A complete Anthropic SSE stream emitting 'Hello!' as the response."""
    return [
        _sse_lf(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "m1",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-test",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 11,
                        "output_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                },
            },
        ),
        _sse_lf(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        _sse_lf(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hello!"},
            },
        ),
        _sse_lf("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _sse_lf(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 1},
            },
        ),
        _sse_lf("message_stop", {"type": "message_stop"}),
    ]


def _request_body() -> bytes:
    return json.dumps(
        {
            "model": "claude-test",
            "messages": [{"role": "user", "content": "Hi"}],
        }
    ).encode("utf-8")


async def _drain_one_batch(plugin: SupabaseSinkPlugin, *, max_wait_s: float = 0.5) -> None:
    """Wait until the queue is empty and the in-flight batch completes."""
    deadline = asyncio.get_event_loop().time() + max_wait_s
    while plugin._queue.qsize() > 0 and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.01)
    # Give the flusher one more tick to actually call submit.
    await asyncio.sleep(0.05)


# -- happy path -------------------------------------------------------------


async def test_full_chunk_to_submit_pipeline():
    """One exchange flows chunk-by-chunk → complete → flusher → submit."""
    stub = _StubClient()
    plugin = SupabaseSinkPlugin(client=stub, batch_size=1, batch_interval_s=0.05)
    await plugin.on_init()
    try:
        ctx = _ctx(request_body=_request_body())
        for chunk in _full_response_stream():
            await plugin.on_response_chunk("ex-1", chunk, ctx)
        await plugin.on_response_complete("ex-1", ctx)

        await _drain_one_batch(plugin)

        assert len(stub.submitted) == 1
        rec = stub.submitted[0]
        assert rec.exchange_id == "ex-1"
        assert rec.session_id == "sess-1"
        assert rec.mode == "R"
        assert rec.endpoint == "v1/messages"
        assert rec.source == "supabase_sink/0.1.0"
        assert rec.model_requested == "claude-test"
        assert rec.model_served == "claude-test"
        assert rec.stop_reason == "end_turn"
        assert rec.input_tokens == 11
        assert rec.output_tokens == 1
        assert rec.request_text and "[user]" in rec.request_text and "Hi" in rec.request_text
        assert rec.response_text == "Hello!"
        assert isinstance(rec.raw_request, dict)
        assert rec.raw_request["model"] == "claude-test"
        assert isinstance(rec.raw_response, dict)
        assert rec.raw_response["stop_reason"] == "end_turn"
    finally:
        await plugin.on_shutdown()


# -- consent gating ---------------------------------------------------------


async def test_user_opted_out_silently_no_ops():
    """Without opt-in the plugin must not capture state or enqueue."""
    stub = _StubClient()
    plugin = SupabaseSinkPlugin(client=stub, batch_size=1, batch_interval_s=0.05)
    await plugin.on_init()
    try:
        ctx = _ctx(user_opted_in=False, request_body=_request_body())
        for chunk in _full_response_stream():
            await plugin.on_response_chunk("ex-2", chunk, ctx)
        await plugin.on_response_complete("ex-2", ctx)

        await _drain_one_batch(plugin)

        assert stub.submitted == []
        assert "ex-2" not in plugin._states
    finally:
        await plugin.on_shutdown()


# -- batching ---------------------------------------------------------------


async def test_batch_size_threshold_flushes_immediately():
    """Once batch_size records have arrived, the flusher submits without
    waiting out the full batch_interval."""
    stub = _StubClient()
    plugin = SupabaseSinkPlugin(client=stub, batch_size=3, batch_interval_s=10.0)
    await plugin.on_init()
    try:
        for i in range(3):
            ctx = _ctx(exchange_id=f"ex-b{i}", request_body=_request_body())
            for chunk in _full_response_stream():
                await plugin.on_response_chunk(ctx.exchange_id, chunk, ctx)
            await plugin.on_response_complete(ctx.exchange_id, ctx)

        # Even though batch_interval_s=10, batch_size=3 should trigger
        # an immediate flush.
        for _ in range(50):
            if len(stub.submitted) >= 3:
                break
            await asyncio.sleep(0.02)

        assert len(stub.submitted) == 3
        assert {r.exchange_id for r in stub.submitted} == {"ex-b0", "ex-b1", "ex-b2"}
    finally:
        await plugin.on_shutdown()


# -- retry / drop -----------------------------------------------------------


async def test_retry_then_succeed_records_only_once():
    """A 5xx followed by 201 should retry and end up submitted exactly once."""
    stub = _StubClient(outcomes=[SubmitOutcome.RETRY, SubmitOutcome.OK])
    sleeps: list[float] = []

    async def _fake_sleep(t: float) -> None:
        sleeps.append(t)

    plugin = SupabaseSinkPlugin(
        client=stub,
        batch_size=1,
        batch_interval_s=0.05,
        sleep=_fake_sleep,
    )
    await plugin.on_init()
    try:
        ctx = _ctx(request_body=_request_body())
        for chunk in _full_response_stream():
            await plugin.on_response_chunk("ex-r", chunk, ctx)
        await plugin.on_response_complete("ex-r", ctx)

        await _drain_one_batch(plugin)

        assert len(stub.submitted) == 2  # called twice (retry + success)
        assert stub.submitted[0].exchange_id == "ex-r"
        assert stub.submitted[1].exchange_id == "ex-r"
        # First retry uses backoff_base * 2**0 = backoff_base.
        assert sleeps and sleeps[0] >= 0
    finally:
        await plugin.on_shutdown()


async def test_terminal_failure_drops_without_retry():
    stub = _StubClient(outcomes=[SubmitOutcome.TERMINAL_FAILURE])
    plugin = SupabaseSinkPlugin(client=stub, batch_size=1, batch_interval_s=0.05)
    await plugin.on_init()
    try:
        ctx = _ctx(request_body=_request_body())
        for chunk in _full_response_stream():
            await plugin.on_response_chunk("ex-t", chunk, ctx)
        await plugin.on_response_complete("ex-t", ctx)

        await _drain_one_batch(plugin)

        assert len(stub.submitted) == 1  # not retried
    finally:
        await plugin.on_shutdown()


async def test_max_attempts_exceeded_drops_record():
    """All attempts return RETRY → record dropped after max_attempts calls."""
    stub = _StubClient(outcomes=[SubmitOutcome.RETRY, SubmitOutcome.RETRY, SubmitOutcome.RETRY])

    async def _fake_sleep(_t: float) -> None:
        return None

    plugin = SupabaseSinkPlugin(
        client=stub,
        batch_size=1,
        batch_interval_s=0.05,
        max_attempts=3,
        sleep=_fake_sleep,
    )
    await plugin.on_init()
    try:
        ctx = _ctx(request_body=_request_body())
        for chunk in _full_response_stream():
            await plugin.on_response_chunk("ex-x", chunk, ctx)
        await plugin.on_response_complete("ex-x", ctx)

        await _drain_one_batch(plugin)

        assert len(stub.submitted) == 3  # exhausted, then dropped
    finally:
        await plugin.on_shutdown()


# -- shutdown drain ---------------------------------------------------------


async def test_on_shutdown_drains_queued_records():
    """Records enqueued just before shutdown must be flushed before the
    flusher exits."""
    stub = _StubClient()

    async def _fake_sleep(_t: float) -> None:
        return None

    # Big batch_interval so the only thing that triggers flush during
    # the test is the shutdown sentinel.
    plugin = SupabaseSinkPlugin(
        client=stub,
        batch_size=8,
        batch_interval_s=10.0,
        sleep=_fake_sleep,
    )
    await plugin.on_init()
    try:
        for i in range(3):
            ctx = _ctx(exchange_id=f"ex-d{i}", request_body=_request_body())
            for chunk in _full_response_stream():
                await plugin.on_response_chunk(ctx.exchange_id, chunk, ctx)
            await plugin.on_response_complete(ctx.exchange_id, ctx)
    finally:
        await plugin.on_shutdown()

    assert len(stub.submitted) == 3
    assert plugin._flusher_task is None  # shutdown cleaned up


# -- env-driven on_init -----------------------------------------------------


async def test_on_init_disables_when_env_missing(monkeypatch):
    """No URL/KEY in env and no client override → plugin disables itself."""
    monkeypatch.delenv("LLMTRACK_PLUGIN_SUPABASE_SINK_URL", raising=False)
    monkeypatch.delenv("LLMTRACK_PLUGIN_SUPABASE_SINK_KEY", raising=False)
    plugin = SupabaseSinkPlugin()
    await plugin.on_init()
    try:
        assert plugin._enabled is False
        # No flusher started.
        assert plugin._flusher_task is None

        ctx = _ctx(request_body=_request_body())
        for chunk in _full_response_stream():
            await plugin.on_response_chunk("ex-i", chunk, ctx)
        await plugin.on_response_complete("ex-i", ctx)

        # Plugin is disabled — no state captured, queue empty.
        assert plugin._states == {}
        assert plugin._queue.qsize() == 0
    finally:
        await plugin.on_shutdown()


async def test_on_init_disables_when_egress_unwired(monkeypatch):
    """Env present, but no host (so no egress) → plugin disables."""
    monkeypatch.setenv("LLMTRACK_PLUGIN_SUPABASE_SINK_URL", "https://x.test/rest/v1/exchanges")
    monkeypatch.setenv("LLMTRACK_PLUGIN_SUPABASE_SINK_KEY", "key")
    plugin = SupabaseSinkPlugin()  # no client override, no host wiring

    await plugin.on_init()
    try:
        assert plugin._enabled is False
        assert plugin._flusher_task is None
    finally:
        await plugin.on_shutdown()


# -- robustness -------------------------------------------------------------


async def test_on_response_complete_without_chunks_is_noop():
    """A blocked / aborted exchange may complete without any chunks."""
    stub = _StubClient()
    plugin = SupabaseSinkPlugin(client=stub, batch_size=1, batch_interval_s=0.05)
    await plugin.on_init()
    try:
        ctx = _ctx(request_body=_request_body())
        # No on_response_chunk calls.
        await plugin.on_response_complete("ex-empty", ctx)
        await _drain_one_batch(plugin)

        assert stub.submitted == []
    finally:
        await plugin.on_shutdown()


async def test_states_isolated_between_concurrent_exchanges():
    """Two interleaved exchanges produce two distinct records."""
    stub = _StubClient()
    plugin = SupabaseSinkPlugin(client=stub, batch_size=2, batch_interval_s=0.05)
    await plugin.on_init()
    try:
        ctx_a = _ctx(exchange_id="a", session_id="sess-a", request_body=_request_body())
        ctx_b = _ctx(exchange_id="b", session_id="sess-b", request_body=_request_body())

        chunks = _full_response_stream()
        # interleave
        for ca, cb in zip(chunks, chunks, strict=False):
            await plugin.on_response_chunk("a", ca, ctx_a)
            await plugin.on_response_chunk("b", cb, ctx_b)

        await plugin.on_response_complete("a", ctx_a)
        await plugin.on_response_complete("b", ctx_b)

        await _drain_one_batch(plugin)

        ids_seen = {r.exchange_id for r in stub.submitted}
        sessions_seen = {r.session_id for r in stub.submitted}
        assert ids_seen == {"a", "b"}
        assert sessions_seen == {"sess-a", "sess-b"}
    finally:
        await plugin.on_shutdown()


# pytest-asyncio handles the async tests via `asyncio_mode = "auto"`
# (configured in the workspace pyproject).
_ = pytest  # silence unused-import lint
