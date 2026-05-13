"""Mini local proxy: inject ``X-LLM-Tracker-Token`` and forward to central.

Fail-closed per ADR-0024: any upstream unreachability returns HTTP 503;
the agent never falls back to ``api.anthropic.com`` directly.
"""

from __future__ import annotations

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from llm_tracker_agent.config import Config

_HOP_BY_HOP = frozenset(
    {
        "host",
        "content-length",
        "transfer-encoding",
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "upgrade",
    }
)
_UNREACHABLE_ERRORS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.TimeoutException,
    httpx.ReadError,
    httpx.RemoteProtocolError,
)
_UNREACHABLE_BODY = {"detail": "llm-tracker central server unreachable"}


def make_proxy_app(
    config: Config,
    *,
    client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Build the proxy app. ``client`` is injectable for tests."""

    app = FastAPI()
    app.state.client = client or httpx.AsyncClient(
        base_url=config.server_url,
        timeout=60.0,
    )
    app.state.token = config.token

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def forward(request: Request, path: str):
        outbound_headers = {
            k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP
        }
        outbound_headers["X-LLM-Tracker-Token"] = app.state.token

        body = await request.body()
        url = f"/{path}"
        if request.url.query:
            url = f"{url}?{request.url.query}"

        upstream_client: httpx.AsyncClient = app.state.client
        upstream_request = upstream_client.build_request(
            request.method,
            url,
            headers=outbound_headers,
            content=body,
        )
        try:
            upstream_response = await upstream_client.send(upstream_request, stream=True)
        except _UNREACHABLE_ERRORS:
            return JSONResponse(_UNREACHABLE_BODY, status_code=503)

        async def body_iter():
            try:
                async for chunk in upstream_response.aiter_bytes():
                    yield chunk
            finally:
                await upstream_response.aclose()

        # aiter_bytes() returns decoded content; strip any content-encoding
        # so the downstream client does not try to decode a second time.
        response_headers = {
            k: v
            for k, v in upstream_response.headers.items()
            if k.lower() not in _HOP_BY_HOP and k.lower() != "content-encoding"
        }
        return StreamingResponse(
            body_iter(),
            status_code=upstream_response.status_code,
            headers=response_headers,
            media_type=upstream_response.headers.get("content-type"),
        )

    return app
