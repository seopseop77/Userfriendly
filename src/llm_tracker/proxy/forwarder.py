"""Transparent HTTP forwarder with a tee for internal stream processing."""

import asyncio
from collections.abc import AsyncGenerator

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse
from ulid import ULID

from ..plugin_host.hooks import Abort, Block
from ..plugin_host.host import PluginHost

UPSTREAM_BASE = "https://api.anthropic.com"
_HOP_BY_HOP = frozenset({"host", "content-length", "transfer-encoding", "connection"})

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


def _block_response(reason: str) -> StreamingResponse:
    """Minimal block response. Phase 1 replaces with proper synthetic SSE (ADR-0002)."""

    async def gen() -> AsyncGenerator[bytes, None]:
        yield f"[llm-tracker blocked]: {reason}".encode()

    return StreamingResponse(gen(), status_code=503)


async def forward_request(
    request: Request,
    path: str,
    plugin_host: PluginHost | None = None,
) -> StreamingResponse:
    exchange_id = str(ULID())

    if plugin_host is not None:
        result = await plugin_host.on_request_received(exchange_id)
        if isinstance(result, Block):
            return _block_response(result.reason)

    url = f"{UPSTREAM_BASE}/{path}"
    if query := request.url.query:
        url = f"{url}?{query}"

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    body = await request.body()

    if plugin_host is not None:
        result = await plugin_host.before_forward(exchange_id)
        if isinstance(result, Block):
            return _block_response(result.reason)

    upstream = await get_client().send(
        get_client().build_request(request.method, url, headers=headers, content=body),
        stream=True,
    )

    if plugin_host is not None:
        result = await plugin_host.on_upstream_response_start(exchange_id)
        if isinstance(result, Abort):
            await upstream.aclose()
            return _block_response(result.reason)

    internal: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def generate() -> AsyncGenerator[bytes, None]:
        drain = asyncio.create_task(_drain(internal))
        completed = False
        try:
            async for chunk in upstream.aiter_bytes():
                if plugin_host is not None:
                    chunk_result = await plugin_host.on_response_chunk(exchange_id, chunk)
                    if isinstance(chunk_result, Abort):
                        break
                await internal.put(chunk)
                yield chunk
            completed = True
        finally:
            await internal.put(None)
            await drain
            await upstream.aclose()

        if completed and plugin_host is not None:
            await plugin_host.on_response_complete(exchange_id)
            await plugin_host.on_persisted(exchange_id)

    response_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in {"transfer-encoding", "connection"}
    }

    return StreamingResponse(
        generate(),
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )
