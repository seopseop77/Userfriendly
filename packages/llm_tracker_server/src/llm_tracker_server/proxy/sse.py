"""Synthetic Anthropic SSE block stream (ADR-0002 §3, design.md §6.3).

Used when a plugin returns :class:`Block` from ``on_request_received``
or ``before_forward`` (or :class:`Abort` from
``on_upstream_response_start``): the upstream call is skipped, the
generator below replaces the response body, and the client sees a
well-formed Anthropic SSE stream whose body is a single text
``[llm-tracker] <reason>`` block.

The sequence is exactly::

  message_start
    -> content_block_start
    -> content_block_delta (single text_delta with the reason)
    -> content_block_stop
    -> message_delta (stop_reason="end_turn")
    -> message_stop

``tool_use`` is **never** emitted: the synthetic response must not
trigger downstream tool execution.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from llm_tracker_server.plugin_host.host import PluginHost

_BLOCK_MODEL_TAG = "llm-tracker-block"


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def block_sse_chunks(reason: str, exchange_id: str) -> list[bytes]:
    """Return the synthetic SSE block stream as a list of byte chunks."""
    text = f"[llm-tracker] {reason}"
    return [
        _sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": exchange_id,
                    "type": "message",
                    "role": "assistant",
                    "content": [],
                    "model": _BLOCK_MODEL_TAG,
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        ),
        _sse(
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        _sse(
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 0},
            },
        ),
        _sse("message_stop", {"type": "message_stop"}),
    ]


def block_response(
    reason: str,
    exchange_id: str,
    plugin_host: PluginHost,
) -> StreamingResponse:
    """Build the synthetic block SSE response (status 200, ADR-0002 §3).

    The block path is the only return path that exits
    :func:`~llm_tracker_server.proxy.forwarder.forward_request` early,
    so the per-exchange :class:`HookContext` cleanup must run from the
    generator that :class:`StreamingResponse` iterates --
    ``forward_request`` itself returns before any of ``gen()`` runs.
    """
    chunks = block_sse_chunks(reason, exchange_id)

    async def gen() -> AsyncGenerator[bytes, None]:
        try:
            for chunk in chunks:
                yield chunk
        finally:
            plugin_host.end_exchange(exchange_id)

    return StreamingResponse(
        gen(),
        status_code=200,
        media_type="text/event-stream",
    )
