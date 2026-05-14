"""Anthropic SSE stream extractor (ADR-0026 Option B).

Reads upstream Anthropic response bytes from an asyncio.Queue (None =
sentinel), parses standard Anthropic event types, and produces a
`ParsedResponse`. Plugins read the result via the `HookContext`
accessors per ADR-0026.

Never raises. Missing fields default to `None` per ADR-0027 axis 1
("best-effort NULL"). The forwarder runs one `parse_sse_stream` task
per request, in parallel with the SSE iter loop that feeds the queue.

Anthropic event types handled:

* `message_start` — `message.model`, `message.usage.input_tokens`,
  `message.usage.cache_read_input_tokens`,
  `message.usage.cache_creation_input_tokens`.
* `message_delta` — `delta.stop_reason`, `usage.output_tokens`.
* `content_block_delta` — `delta.text` accumulated per `index` so
  the assembled `response_json` mirrors the non-stream Anthropic shape.

Unknown events are ignored (forwards-compatible). Tool-use blocks are
not yet extracted; `tool_call_count` on `exchanges` stays 0 until a
follow-up checkpoint adds tool-extraction here.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field


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


def _apply(usage: ResponseUsage, text_blocks: dict[int, list[str]], name: str, data: dict) -> None:
    """Update accumulators from one parsed event. Swallows shape mismatches."""
    if name == "message_start":
        msg = data.get("message", {})
        if not isinstance(msg, dict):
            return
        if isinstance(msg.get("model"), str):
            usage.model_served = msg["model"]
        u = msg.get("usage", {})
        if isinstance(u, dict):
            if isinstance(u.get("input_tokens"), int):
                usage.input_tokens = u["input_tokens"]
            if isinstance(u.get("cache_read_input_tokens"), int):
                usage.cache_read_tokens = u["cache_read_input_tokens"]
            if isinstance(u.get("cache_creation_input_tokens"), int):
                usage.cache_write_tokens = u["cache_creation_input_tokens"]
    elif name == "message_delta":
        delta = data.get("delta", {})
        if isinstance(delta, dict) and isinstance(delta.get("stop_reason"), str):
            usage.stop_reason = delta["stop_reason"]
        u = data.get("usage", {})
        if isinstance(u, dict) and isinstance(u.get("output_tokens"), int):
            usage.output_tokens = u["output_tokens"]
    elif name == "content_block_delta":
        idx = data.get("index")
        delta = data.get("delta", {})
        if isinstance(idx, int) and isinstance(delta, dict):
            text = delta.get("text")
            if isinstance(text, str):
                text_blocks.setdefault(idx, []).append(text)


async def parse_sse_stream(queue: asyncio.Queue[bytes | None]) -> ParsedResponse:
    """Consume SSE bytes until sentinel; return a `ParsedResponse`. Never raises."""
    usage = ResponseUsage()
    text_blocks: dict[int, list[str]] = {}
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
                _apply(usage, text_blocks, name or "", data)
            except Exception:  # pragma: no cover — defensive
                continue

    content = [{"type": "text", "text": "".join(text_blocks[i])} for i in sorted(text_blocks)]
    response = {
        "model": usage.model_served,
        "content": content,
        "stop_reason": usage.stop_reason,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_input_tokens": usage.cache_read_tokens,
            "cache_creation_input_tokens": usage.cache_write_tokens,
        },
    }
    try:
        response_json = json.dumps(response, ensure_ascii=False)
    except (ValueError, TypeError):
        response_json = "{}"
    return ParsedResponse(usage=usage, response_json=response_json)
