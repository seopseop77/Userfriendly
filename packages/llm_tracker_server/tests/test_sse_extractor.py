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


# ---------- ADR-0028: faithful reassembly of non-stream response shape ----------


@pytest.mark.asyncio
async def test_tool_use_block_assembled() -> None:
    """A tool_use block is reassembled with id, name, and the parsed input dict."""
    chunks = [
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"id":"msg_02","type":"message",'
        b'"role":"assistant","model":"claude-opus-4-7",'
        b'"usage":{"input_tokens":50,"output_tokens":1}}}\n\n',
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,'
        b'"content_block":{"type":"tool_use","id":"toolu_01ABC",'
        b'"name":"get_weather","input":{}}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"input_json_delta","partial_json":"{\\"location\\":"}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"input_json_delta","partial_json":"\\"Seoul\\"}"}}\n\n',
        b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
        b"event: message_delta\n"
        b'data: {"delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":112}}\n\n',
    ]
    parsed = await _feed(chunks)

    assert parsed.usage.stop_reason == "tool_use"
    assert parsed.usage.output_tokens == 112

    payload = json.loads(parsed.response_json)
    assert payload["stop_reason"] == "tool_use"
    assert payload["content"] == [
        {
            "type": "tool_use",
            "id": "toolu_01ABC",
            "name": "get_weather",
            "input": {"location": "Seoul"},
        }
    ]


@pytest.mark.asyncio
async def test_mixed_text_and_tool_use_blocks() -> None:
    """A response with text at index 0 and tool_use at index 1 reassembles both, in order."""
    chunks = [
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"model":"claude-opus-4-7",'
        b'"usage":{"input_tokens":20,"output_tokens":1}}}\n\n',
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,'
        b'"content_block":{"type":"text","text":""}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"text_delta","text":"Let me check."}}\n\n',
        b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":1,'
        b'"content_block":{"type":"tool_use","id":"toolu_X",'
        b'"name":"search","input":{}}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":1,'
        b'"delta":{"type":"input_json_delta","partial_json":"{\\"q\\":\\"x\\"}"}}\n\n',
        b'event: content_block_stop\ndata: {"type":"content_block_stop","index":1}\n\n',
        b"event: message_delta\n"
        b'data: {"delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":40}}\n\n',
    ]
    parsed = await _feed(chunks)

    payload = json.loads(parsed.response_json)
    assert payload["content"] == [
        {"type": "text", "text": "Let me check."},
        {"type": "tool_use", "id": "toolu_X", "name": "search", "input": {"q": "x"}},
    ]


@pytest.mark.asyncio
async def test_thinking_block_assembled() -> None:
    """A thinking block accumulates `thinking_delta` text verbatim."""
    chunks = [
        b"event: message_start\n"
        b'data: {"type":"message_start","message":{"model":"claude-opus-4-7",'
        b'"usage":{"input_tokens":5,"output_tokens":1}}}\n\n',
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,'
        b'"content_block":{"type":"thinking","thinking":""}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"thinking_delta","thinking":"Step 1. "}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"thinking_delta","thinking":"Step 2."}}\n\n',
        b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
    ]
    parsed = await _feed(chunks)

    payload = json.loads(parsed.response_json)
    assert payload["content"] == [{"type": "thinking", "thinking": "Step 1. Step 2."}]


@pytest.mark.asyncio
async def test_unknown_delta_type_preserved() -> None:
    """An unrecognised delta type is captured under `_extra_deltas` (fail-open)."""
    chunks = [
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,'
        b'"content_block":{"type":"future_block","foo":""}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"future_delta","payload":"abc"}}\n\n',
        b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
    ]
    parsed = await _feed(chunks)

    payload = json.loads(parsed.response_json)
    assert payload["content"][0]["type"] == "future_block"
    assert payload["content"][0]["_extra_deltas"] == [{"type": "future_delta", "payload": "abc"}]


@pytest.mark.asyncio
async def test_malformed_input_json_preserves_raw() -> None:
    """If the accumulated `input_json` does not parse, the raw string is preserved."""
    chunks = [
        b"event: content_block_start\n"
        b'data: {"type":"content_block_start","index":0,'
        b'"content_block":{"type":"tool_use","id":"toolu_Z","name":"f","input":{}}}\n\n',
        b"event: content_block_delta\n"
        b'data: {"type":"content_block_delta","index":0,'
        b'"delta":{"type":"input_json_delta","partial_json":"{not valid"}}\n\n',
        b'event: content_block_stop\ndata: {"type":"content_block_stop","index":0}\n\n',
    ]
    parsed = await _feed(chunks)

    payload = json.loads(parsed.response_json)
    block = payload["content"][0]
    assert block["type"] == "tool_use"
    assert block["input"] == {}  # untouched from content_block_start seed
    assert block["_input_json_raw"] == "{not valid"
