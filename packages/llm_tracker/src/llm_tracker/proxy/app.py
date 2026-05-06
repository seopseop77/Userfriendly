"""FastAPI application: catch-all proxy route."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

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
    host = PluginHost(
        mode=settings.mode,
        session_factory=factory,
        egress_guard=egress_guard,
    )
    await host.on_init()
    app.state.plugin_host = host
    app.state.egress_guard = egress_guard
    yield
    await host.on_shutdown()


app = FastAPI(
    title="llm-tracker proxy",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.api_route("/{path:path}", methods=["DELETE", "GET", "PATCH", "POST", "PUT"])
async def proxy(request: Request, path: str) -> StreamingResponse:
    plugin_host = getattr(request.app.state, "plugin_host", None)
    return await forward_request(request, path, plugin_host)
