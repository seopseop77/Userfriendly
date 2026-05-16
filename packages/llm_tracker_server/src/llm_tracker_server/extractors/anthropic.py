"""Anthropic SSE stream extractor.

Reads upstream Anthropic response bytes from an asyncio.Queue (None =
sentinel), parses standard Anthropic event types, and produces a
`ParsedResponse`. Plugins read the result via the `HookContext`
accessors per ADR-0026.

Never raises. Missing fields default to `None` per ADR-0027 axis 1
("best-effort NULL"). The forwarder runs one `parse_sse_stream` task
per request, in parallel with the SSE iter loop that feeds the queue.

Per ADR-0028, `response_json` is a faithful reassembly of Anthropic's
non-stream response shape — every block emitted by the model is
captured (text, tool_use, thinking, and future types). Unknown delta
types are preserved fail-open under `_extra_deltas` so a new Anthropic
block type does not require a server change to *store* it; curated
extraction can opt in later if a specific field needs server-side
surfacing.

Anthropic event types handled:

* `message_start` — `message.model`, `message.usage.input_tokens`,
  `message.usage.cache_read_input_tokens`,
  `message.usage.cache_creation_input_tokens`.
* `message_delta` — `delta.stop_reason`, `usage.output_tokens`.
* `content_block_start` — seeds `blocks[index]` from the event's
  `content_block` payload as-is (shallow copy).
* `content_block_delta` — dispatched by `delta.type`:
  `text_delta` / `input_json_delta` / `thinking_delta` /
  `signature_delta`. Unrecognised types append the raw delta to
  `block["_extra_deltas"]`.
* `content_block_stop` — finalises any buffered `input_json_delta` for
  the index into `block["input"]`. On parse failure the raw string is
  preserved at `block["_input_json_raw"]`.

Unknown events are ignored (forwards-compatible).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResponseUsage:
    """Structured view of the Anthropic response's usage block + model + stop_reason."""

    model_served: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    stop_reason: str | None = None


@dataclass
class ParsedResponse:
    """Extractor output handed back to the forwarder."""

    usage: ResponseUsage = field(default_factory=ResponseUsage)
    response_json: str = "{}"


@dataclass
class _StreamState:
    """Mutable accumulator threaded through `_apply` during parsing."""

    usage: ResponseUsage = field(default_factory=ResponseUsage)
    blocks: dict[int, dict[str, Any]] = field(default_factory=dict)
    input_json_buffers: dict[int, list[str]] = field(default_factory=dict)


def _parse_event(event_text: str) -> tuple[str | None, dict | None]:
    """Parse one SSE event block into (event_name, data_dict). Either may be None."""
    event_name: str | None = None
    data_str: str | None = None
    for line in event_text.split("\n"):
        if not line:
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or None
        elif line.startswith("data:"):
            data_str = line[5:].strip()
    if data_str is None:
        return event_name, None
    try:
        parsed = json.loads(data_str)
    except (ValueError, TypeError):
        return event_name, None
    return event_name, parsed if isinstance(parsed, dict) else None


def _finalize_input_json(state: _StreamState, idx: int) -> None:
    """Parse and merge the buffered `input_json_delta` for one block."""
    buf = state.input_json_buffers.pop(idx, None)
    if not buf:
        return
    block = state.blocks.get(idx)
    if block is None:
        return
    joined = "".join(buf)
    if not joined:
        return
    try:
        block["input"] = json.loads(joined)
    except (ValueError, TypeError):
        block["_input_json_raw"] = joined


def _apply(state: _StreamState, name: str, data: dict) -> None:
    """Update accumulators from one parsed event. Swallows shape mismatches."""
    if name == "message_start":
        msg = data.get("message", {})
        if not isinstance(msg, dict):
            return
        if isinstance(msg.get("model"), str):
            state.usage.model_served = msg["model"]
        u = msg.get("usage", {})
        if isinstance(u, dict):
            if isinstance(u.get("input_tokens"), int):
                state.usage.input_tokens = u["input_tokens"]
            if isinstance(u.get("cache_read_input_tokens"), int):
                state.usage.cache_read_tokens = u["cache_read_input_tokens"]
            if isinstance(u.get("cache_creation_input_tokens"), int):
                state.usage.cache_write_tokens = u["cache_creation_input_tokens"]
    elif name == "message_delta":
        delta = data.get("delta", {})
        if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
            state.usage.stop_reason = delta["stop_reason"]
        u = data.get("usage", {})
        if isinstance(u, dict) and isinstance(u.get("output_tokens"), int):
            state.usage.output_tokens = u["output_tokens"]
    elif name == "content_block_start":
        idx = data.get("index")
        block = data.get("content_block")
        if isinstance(idx, int) and isinstance(block, dict):
            state.blocks[idx] = dict(block)
    elif name == "content_block_delta":
        idx = data.get("index")
        delta = data.get("delta", {})
        if not (isinstance(idx, int) and isinstance(delta, dict)):
            return
        delta_type = delta.get("type")
        if delta_type == "text_delta":
            text = delta.get("text")
            if isinstance(text, str):
                block = state.blocks.setdefault(idx, {"type": "text", "text": ""})
                block["text"] = block.get("text", "") + text
        elif delta_type == "input_json_delta":
            partial = delta.get("partial_json")
            if isinstance(partial, str):
                state.input_json_buffers.setdefault(idx, []).append(partial)
        elif delta_type == "thinking_delta":
            thinking = delta.get("thinking")
            if isinstance(thinking, str):
                block = state.blocks.get(idx)
                if block is not None:
                    block["thinking"] = block.get("thinking", "") + thinking
        elif delta_type == "signature_delta":
            signature = delta.get("signature")
            if isinstance(signature, str):
                block = state.blocks.get(idx)
                if block is not None:
                    block["signature"] = block.get("signature", "") + signature
        else:
            block = state.blocks.get(idx)
            if block is not None:
                block.setdefault("_extra_deltas", []).append(delta)
    elif name == "content_block_stop":
        idx = data.get("index")
        if isinstance(idx, int):
            _finalize_input_json(state, idx)


async def parse_sse_stream(queue: asyncio.Queue[bytes | None]) -> ParsedResponse:
    """Consume SSE bytes until sentinel; return a `ParsedResponse`. Never raises."""
    state = _StreamState()
    buffer = b""

    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        buffer += chunk
        while b"\n\n" in buffer:
            event_bytes, buffer = buffer.split(b"\n\n", 1)
            try:
                event_text = event_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue
            name, data = _parse_event(event_text)
            if data is None:
                continue
            try:
                _apply(state, name or "", data)
            except Exception:  # pragma: no cover — defensive
                continue

    # Flush any input_json_delta buffers whose content_block_stop never arrived.
    for idx in list(state.input_json_buffers):
        _finalize_input_json(state, idx)

    content = [state.blocks[i] for i in sorted(state.blocks)]
    response = {
        "model": state.usage.model_served,
        "content": content,
        "stop_reason": state.usage.stop_reason,
        "usage": {
            "input_tokens": state.usage.input_tokens,
            "output_tokens": state.usage.output_tokens,
            "cache_read_input_tokens": state.usage.cache_read_tokens,
            "cache_creation_input_tokens": state.usage.cache_write_tokens,
        },
    }
    try:
        response_json = json.dumps(response, ensure_ascii=False)
    except (ValueError, TypeError):
        response_json = "{}"
    return ParsedResponse(usage=state.usage, response_json=response_json)
