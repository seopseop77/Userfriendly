"""Tests for the Anthropic SSE extractor (ADR-0026 Option B).

Three contract surfaces are pinned:

1. A realistic Anthropic SSE sequence parses into populated
   `ResponseUsage` fields (model_served, input/output tokens, cache
   tokens, stop_reason) and the assembled `response_json` contains the
   accumulated `content_block_delta` text.
2. A truncated / malformed stream never raises — missing fields stay
   `None` (ADR-0027 axis 1 contract).
3. `response_json` is valid JSON whose `content` array carries the
   text deltas as one block per index.

The fixture feeds bytes through an `asyncio.Queue` exactly the way
`proxy.forwarder.generate` does in production.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from llm_tracker_server.extractors.anthropic import (
    ParsedResponse,
    ResponseUsage,
    parse_sse_stream,
)


async def _feed(events: list[bytes]) -> ParsedResponse:
    """Push each chunk through a Queue + sentinel, run the extractor."""
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    for chunk in events:
        await queue.put(chunk)
    await queue.put(None)
    return await parse_sse_stream(queue)


@pytest.mark.asyncio
async def test_parses_model_and_tokens() -> None:
    chunks = [
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"id":"msg_01","type":"message",'
        b'"role":"assistant","model":"claude-haiku-4-5-20251001","content":[],'
        b'"stop_reason":null,'
        b'"usage":{"input_tokens":42,"cache_read_input_tokens":7,'
        b'"cache_creation_input_tokens":3,"output_tokens":1}}}\n\n',
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,'
        b'"content_block":{"type":"text","text":""}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"Hello"}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":", world!"}}\n\n',
        b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
        b"event: message_delta\n"
        b'data: {"type":"message_delta",'
        b'"delta":{"stop_reason":"end_turn","stop_sequence":null},'
        b'"usage":{"output_tokens":15}}\n\n',
        b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
    ]
    parsed = await _feed(chunks)

    assert parsed.usage.model_served == "claude-haiku-4-5-20251001"
    assert parsed.usage.input_tokens == 42
    assert parsed.usage.output_tokens == 15
    assert parsed.usage.cache_read_tokens == 7
    assert parsed.usage.cache_write_tokens == 3
    assert parsed.usage.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_partial_stream_no_raise() -> None:
    """A stream that ends mid-event returns whatever was parsed, never raises."""
    # message_start lands; the second event is truncated mid-data.
    chunks = [
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"model":"claude-haiku-4-5-20251001",'
        b'"usage":{"input_tokens":3}}}\n\n',
        b"event: message_delta\n"
        b'data: {"type":"message_delta","del',  # truncated — sentinel right after.
    ]
    parsed = await _feed(chunks)

    # message_start fields survived.
    assert parsed.usage.model_served == "claude-haiku-4-5-20251001"
    assert parsed.usage.input_tokens == 3
    # The truncated message_delta did not populate stop_reason or
    # output_tokens (its `data:` line never finished JSON-decoding).
    assert parsed.usage.stop_reason is None
    assert parsed.usage.output_tokens is None


@pytest.mark.asyncio
async def test_malformed_json_no_raise() -> None:
    """A `data:` line with broken JSON is ignored; subsequent events still parse."""
    chunks = [
        b"event: message_start\ndata: {this is not json}\n\n",
        b"event: message_delta\n"
        b'data: {"delta":{"stop_reason":"max_tokens"},"usage":{"output_tokens":10}}\n\n',
    ]
    parsed = await _feed(chunks)

    assert parsed.usage.model_served is None
    assert parsed.usage.input_tokens is None
    assert parsed.usage.stop_reason == "max_tokens"
    assert parsed.usage.output_tokens == 10


@pytest.mark.asyncio
async def test_response_json_assembled() -> None:
    """`response_json` is valid JSON; content carries the concatenated deltas."""
    chunks = [
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"model":"claude-haiku-4-5-20251001",'
        b'"usage":{"input_tokens":1}}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"foo"}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"bar"}}\n\n',
        b"event: message_delta\n"
        b'data: {"delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}\n\n',
    ]
    parsed = await _feed(chunks)

    payload = json.loads(parsed.response_json)
    assert payload["model"] == "claude-haiku-4-5-20251001"
    assert payload["stop_reason"] == "end_turn"
    assert payload["usage"]["input_tokens"] == 1
    assert payload["usage"]["output_tokens"] == 2
    assert payload["content"] == [{"type": "text", "text": "foobar"}]


@pytest.mark.asyncio
async def test_chunk_boundary_mid_event() -> None:
    """A single SSE event split across chunks is still parsed correctly.

    Production SSE clients receive arbitrary byte boundaries; the
    extractor buffers across calls until it sees `\\n\\n`.
    """
    first = b'event: message_start\ndata: {"type":"message_start","message":'
    second = b'{"model":"claude-haiku-4-5-20251001","usage":{"input_tokens":11}}}\n\n'
    parsed = await _feed([first, second])

    assert parsed.usage.model_served == "claude-haiku-4-5-20251001"
    assert parsed.usage.input_tokens == 11


@pytest.mark.asyncio
async def test_empty_stream_returns_empty_response() -> None:
    """An immediate sentinel (no events) returns a ParsedResponse with all-None usage."""
    parsed = await _feed([])

    assert isinstance(parsed, ParsedResponse)
    assert isinstance(parsed.usage, ResponseUsage)
    assert parsed.usage.model_served is None
    assert parsed.usage.input_tokens is None
    payload = json.loads(parsed.response_json)
    assert payload["content"] == []
