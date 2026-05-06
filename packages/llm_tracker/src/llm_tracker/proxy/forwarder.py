"""Transparent HTTP forwarder with a tee for internal stream processing."""

import asyncio
import json
import time
from collections.abc import AsyncGenerator

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse
from llm_tracker_sdk import Abort, Block, Transform
from ulid import ULID

from ..plugin_host.host import PluginHost
from ..storage.exchanges import record_exchange_blocked, record_exchange_timing

UPSTREAM_BASE = "https://api.anthropic.com"
_HOP_BY_HOP = frozenset(
    {"host", "content-length", "transfer-encoding", "connection", "accept-encoding"}
)

_BLOCK_MODEL_TAG = "llm-tracker-block"

_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(http2=True, timeout=None)
    return _client


async def _drain(queue: asyncio.Queue[bytes | None]) -> None:
    """Phase-0 no-op consumer. Later phases replace this with the Extractor."""
    while await queue.get() is not None:
        pass


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


def _block_sse_chunks(reason: str, exchange_id: str) -> list[bytes]:
    """Synthetic Anthropic SSE block stream (ADR-0002 §3, design.md §6.3).

    The sequence is exactly:
      message_start -> content_block_start -> content_block_delta
      (single text_delta with the `[llm-tracker]` prefix and the reason)
      -> content_block_stop -> message_delta (stop_reason="end_turn")
      -> message_stop

    `tool_use` is *never* emitted: the synthetic response must not
    trigger downstream tool execution.
    """
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


def _block_response(reason: str, exchange_id: str) -> StreamingResponse:
    """Build the synthetic block SSE response (ADR-0002 §3, status 200)."""
    chunks = _block_sse_chunks(reason, exchange_id)

    async def gen() -> AsyncGenerator[bytes, None]:
        for chunk in chunks:
            yield chunk

    return StreamingResponse(
        gen(),
        status_code=200,
        media_type="text/event-stream",
    )


async def _persist_block(
    plugin_host: PluginHost,
    *,
    exchange_id: str,
    endpoint: str,
    blocked_by: str,
    started_at_ms: int,
) -> None:
    async with plugin_host.session_factory() as session:
        await record_exchange_blocked(
            session,
            exchange_id=exchange_id,
            endpoint=endpoint,
            blocked_by=blocked_by,
            started_at_ms=started_at_ms,
        )


async def forward_request(
    request: Request,
    path: str,
    plugin_host: PluginHost | None = None,
) -> StreamingResponse:
    t0_mono = time.monotonic()
    t0_epoch_ms = int(time.time() * 1000)
    exchange_id = str(ULID())

    # Read the request body once, up-front, so plugins running in
    # `on_request_received` can see it through `HookContext.request_text()`.
    # `Request.body()` is idempotent and cached on the Starlette Request,
    # so subsequent reads are free.
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    body = await request.body()

    if plugin_host is not None:
        plugin_host.begin_exchange(exchange_id, request_body=body)

        result = await plugin_host.on_request_received(exchange_id)
        if isinstance(result, Block):
            await _persist_block(
                plugin_host,
                exchange_id=exchange_id,
                endpoint=path,
                blocked_by=result.plugin,
                started_at_ms=t0_epoch_ms,
            )
            return _block_response(result.reason, exchange_id)

    url = f"{UPSTREAM_BASE}/{path}"
    if query := request.url.query:
        url = f"{url}?{query}"

    if plugin_host is not None:
        result = await plugin_host.before_forward(exchange_id)
        if isinstance(result, Block):
            await _persist_block(
                plugin_host,
                exchange_id=exchange_id,
                endpoint=path,
                blocked_by=result.plugin,
                started_at_ms=t0_epoch_ms,
            )
            return _block_response(result.reason, exchange_id)
        if isinstance(result, Transform):
            # ADR-0011: merge plugin headers into the request, plugin wins
            # on conflict. Body replace is whole-body when set.
            if result.headers is not None:
                headers.update(result.headers)
            if result.body is not None:
                body = result.body

    upstream = await get_client().send(
        get_client().build_request(request.method, url, headers=headers, content=body),
        stream=True,
    )

    if plugin_host is not None:
        result = await plugin_host.on_upstream_response_start(exchange_id)
        if isinstance(result, Abort):
            await upstream.aclose()
            await _persist_block(
                plugin_host,
                exchange_id=exchange_id,
                endpoint=path,
                blocked_by=result.plugin,
                started_at_ms=t0_epoch_ms,
            )
            return _block_response(result.reason, exchange_id)

    internal: asyncio.Queue[bytes | None] = asyncio.Queue()
    timing: dict[str, float] = {}

    async def generate() -> AsyncGenerator[bytes, None]:
        drain = asyncio.create_task(_drain(internal))
        completed = False
        first_byte = True
        try:
            async for chunk in upstream.aiter_bytes():
                if first_byte:
                    timing["t1"] = time.monotonic()
                if plugin_host is not None:
                    chunk_result = await plugin_host.on_response_chunk(exchange_id, chunk)
                    if isinstance(chunk_result, Abort):
                        break
                await internal.put(chunk)
                if first_byte:
                    timing["t2"] = time.monotonic()
                    first_byte = False
                yield chunk
            completed = True
        finally:
            await internal.put(None)
            await drain
            await upstream.aclose()

        if completed and plugin_host is not None:
            await plugin_host.on_response_complete(exchange_id)
            if "t1" in timing and "t2" in timing:
                t_req = t0_epoch_ms
                t_up = t0_epoch_ms + int((timing["t1"] - t0_mono) * 1000)
                t_cli = t0_epoch_ms + int((timing["t2"] - t0_mono) * 1000)
                async with plugin_host.session_factory() as session:
                    await record_exchange_timing(
                        session,
                        exchange_id=exchange_id,
                        endpoint=path,
                        t_request_received_ms=t_req,
                        t_upstream_first_byte_ms=t_up,
                        t_client_first_byte_ms=t_cli,
                    )
            # design.md §6.3.2: on_persisted fires *after* the DB write so
            # plugins can read the exchange row back.
            await plugin_host.on_persisted(exchange_id)

    response_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in {"transfer-encoding", "connection", "content-encoding"}
    }

    return StreamingResponse(
        generate(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )
