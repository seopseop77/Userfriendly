"""Tests for the test-only token_counter plugin."""

from __future__ import annotations

import json

import pytest
from llm_tracker_plugin_token_counter import TokenCounterPlugin
from llm_tracker_plugin_token_counter.parser import UsageAccumulator
from llm_tracker_plugin_token_counter.storage import UsageStore
from llm_tracker_sdk.testing import PluginHarness


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def _message_start(
    *,
    model: str = "claude-test",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> bytes:
    return _sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cache_creation_input_tokens": cache_creation_input_tokens,
                    "cache_read_input_tokens": cache_read_input_tokens,
                },
            },
        },
    )


def _message_delta(*, output_tokens: int) -> bytes:
    return _sse(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": output_tokens},
        },
    )


# -- parser unit tests ---------------------------------------------------------


def test_accumulator_extracts_message_start_usage():
    acc = UsageAccumulator()
    acc.feed(
        _message_start(
            model="claude-3-5-sonnet",
            input_tokens=100,
            cache_creation_input_tokens=50,
            cache_read_input_tokens=25,
        )
    )
    assert acc.has_usage()
    assert acc.model == "claude-3-5-sonnet"
    assert acc.input_tokens == 100
    assert acc.cache_creation_input_tokens == 50
    assert acc.cache_read_input_tokens == 25


def test_accumulator_takes_max_output_from_message_delta():
    acc = UsageAccumulator()
    acc.feed(_message_start(input_tokens=10, output_tokens=1))
    acc.feed(_message_delta(output_tokens=42))
    assert acc.input_tokens == 10
    assert acc.output_tokens == 42


def test_accumulator_handles_split_chunks():
    acc = UsageAccumulator()
    payload = _message_start(input_tokens=7) + _message_delta(output_tokens=11)
    # Slice every byte on its own to torture-test the buffering.
    for i in range(len(payload)):
        acc.feed(payload[i : i + 1])
    assert acc.input_tokens == 7
    assert acc.output_tokens == 11


def test_accumulator_ignores_non_usage_events():
    acc = UsageAccumulator()
    acc.feed(_sse("ping", {"type": "ping"}))
    acc.feed(b"event: malformed\nno-colon\n\n")
    acc.feed(b"event: message_start\ndata: {not json}\n\n")
    assert not acc.has_usage()


def test_accumulator_ignores_non_int_values():
    acc = UsageAccumulator()
    acc.feed(
        _sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "model": "x",
                    "usage": {"input_tokens": "100", "output_tokens": None},
                },
            },
        )
    )
    assert not acc.has_usage()


# -- plugin behaviour ---------------------------------------------------------


@pytest.fixture
async def store(tmp_path):
    store = UsageStore(tmp_path / "tc.db")
    await store.init()
    yield store
    await store.close()


async def test_plugin_persists_usage_after_response_complete(store):
    plugin = TokenCounterPlugin(store=store)
    harness = PluginHarness(plugin)
    await harness.init()
    eid = "exch-1"

    await harness.on_response_chunk(
        _message_start(input_tokens=120, cache_read_input_tokens=30), eid
    )
    await harness.on_response_chunk(_message_delta(output_tokens=55), eid)
    # eid still in the in-memory accumulator at this point.
    assert eid in plugin._accumulators

    await harness.on_response_complete(eid)

    record = await store.fetch(eid)
    assert record is not None
    assert record.input_tokens == 120
    assert record.output_tokens == 55
    assert record.cache_read_input_tokens == 30
    # Accumulator dropped after flush.
    assert eid not in plugin._accumulators


async def test_plugin_skips_persist_when_no_usage_seen(store):
    plugin = TokenCounterPlugin(store=store)
    harness = PluginHarness(plugin)
    await harness.on_response_chunk(b"event: ping\ndata: {}\n\n", "exch-2")
    await harness.on_response_complete("exch-2")
    assert await store.fetch("exch-2") is None


async def test_plugin_isolates_concurrent_exchanges(store):
    plugin = TokenCounterPlugin(store=store)
    harness = PluginHarness(plugin)
    await harness.on_response_chunk(_message_start(input_tokens=1), "a")
    await harness.on_response_chunk(_message_start(input_tokens=2), "b")
    await harness.on_response_chunk(_message_delta(output_tokens=10), "a")
    await harness.on_response_chunk(_message_delta(output_tokens=20), "b")
    await harness.on_response_complete("a")
    await harness.on_response_complete("b")

    rec_a = await store.fetch("a")
    rec_b = await store.fetch("b")
    assert rec_a is not None and rec_a.input_tokens == 1 and rec_a.output_tokens == 10
    assert rec_b is not None and rec_b.input_tokens == 2 and rec_b.output_tokens == 20


async def test_plugin_shutdown_closes_store(store):
    plugin = TokenCounterPlugin(store=store)
    await plugin.on_shutdown()
    # The injected store was closed by the plugin and the reference cleared.
    assert plugin._store is None
