"""Transparent HTTP forwarder with a tee for internal stream processing."""

import asyncio
from collections.abc import AsyncGenerator

import httpx
from fastapi import Request
from fastapi.responses import StreamingResponse

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


async def forward_request(request: Request, path: str) -> StreamingResponse:
    url = f"{UPSTREAM_BASE}/{path}"
    if query := request.url.query:
        url = f"{url}?{query}"

    headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    body = await request.body()

    upstream = await get_client().send(
        get_client().build_request(request.method, url, headers=headers, content=body),
        stream=True,
    )

    internal: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def generate() -> AsyncGenerator[bytes, None]:
        drain = asyncio.create_task(_drain(internal))
        try:
            async for chunk in upstream.aiter_bytes():
                await internal.put(chunk)
                yield chunk
        finally:
            await internal.put(None)
            await drain
            await upstream.aclose()

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
