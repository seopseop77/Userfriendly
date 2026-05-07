"""FastAPI application: admin routes + catch-all proxy route."""

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import Settings
from ..egress_guard.guard import EgressGuard
from ..plugin_host.host import PluginHost
from ..storage.database import make_session_factory
from .forwarder import forward_request


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    factory = make_session_factory(settings.db_url)
    egress_guard = EgressGuard(mode=settings.mode, session_factory=factory)
    # ADR-0015 §Lifecycle: shared httpx client for all plugin egress.
    # Closed *after* `host.on_shutdown()` so a shutdown-time flusher can
    # still drain its queue.
    egress_http_client = httpx.AsyncClient(timeout=None)
    host = PluginHost(
        mode=settings.mode,
        session_factory=factory,
        egress_guard=egress_guard,
        plugins_disabled=frozenset(settings.plugins_disabled),
        http_client=egress_http_client,
        user_opted_in=settings.user_opted_in,
    )
    await host.on_init()
    app.state.plugin_host = host
    app.state.egress_guard = egress_guard
    try:
        yield
    finally:
        await host.on_shutdown()
        await egress_http_client.aclose()


app = FastAPI(
    title="llm-tracker proxy",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


# Admin routes are registered before the catch-all so FastAPI's
# in-order dispatch reaches them first (ADR-0014). Localhost-only by
# virtue of `proxy_host` defaulting to 127.0.0.1; no auth on purpose.
@app.get("/admin/plugins")
async def admin_plugins(request: Request) -> JSONResponse:
    plugin_host = getattr(request.app.state, "plugin_host", None)
    payload = plugin_host.loaded_plugins() if plugin_host is not None else []
    return JSONResponse(payload)


@app.api_route("/{path:path}", methods=["DELETE", "GET", "PATCH", "POST", "PUT"])
async def proxy(request: Request, path: str) -> StreamingResponse:
    plugin_host = getattr(request.app.state, "plugin_host", None)
    return await forward_request(request, path, plugin_host)
