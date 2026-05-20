"""FastAPI application factory.

CP1 shipped ``/healthz``. CP6 layered per-org auth + RLS binding on top
of every non-public route. CP7 added the Anthropic credential
pass-through surface. CP8 wires the full plugin-host lifecycle:

* The shared :class:`httpx.AsyncClient` lifecycle (one for upstream
  forwarding, one for plugin egress) is owned by ``lifespan``.
* The :class:`PluginHost` + :class:`EgressGuard` are constructed
  inside ``lifespan`` (when a session factory is available) and torn
  down via :meth:`PluginHost.on_shutdown` *before* the egress client
  closes so a shutdown-time flusher can still drain.
* ``/admin/plugins`` returns the introspection view (ADR-0014).
* ``/{path:path}`` is the catch-all proxy route mounted last so
  ``/healthz`` / ``/admin/*`` reach their handlers first.

Keeping the session-factory wiring optional preserves the CP1 boot
contract: ``python -c "from llm_tracker_server.app import app"`` must
succeed even with no database configured.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
import sqlalchemy as sa
import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from llm_tracker_server import __version__
from llm_tracker_server.audit_context import session_bound_audit_writer
from llm_tracker_server.auth import AuthMiddleware
from llm_tracker_server.config import Settings
from llm_tracker_server.egress_guard import EgressGuard
from llm_tracker_server.logging import configure_logging
from llm_tracker_server.plugin_host import PluginHost
from llm_tracker_server.proxy.forwarder import forward_request
from llm_tracker_server.storage import make_engine, make_session_factory


def create_app(
    settings: Settings | None = None,
    session_factory: Callable[[], object] | None = None,
) -> FastAPI:
    # `.env` resolves before Settings so file-provided values are
    # visible; `override=False` keeps a shell-exported value
    # authoritative.
    load_dotenv(override=False)
    resolved = settings or Settings()
    configure_logging(resolved.log_level)
    log = structlog.get_logger(__name__)

    owned_engine = None
    if session_factory is None and resolved.database_url:
        owned_engine = make_engine(resolved.database_url)
        session_factory = make_session_factory(owned_engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Two clients (mirrors the local sidecar): one for upstream
        # forwarding (HTTP/2-capable so Anthropic SSE streams
        # behave), one for plugin egress (default settings).
        upstream_client: httpx.AsyncClient | None = None
        egress_client: httpx.AsyncClient | None = None
        plugin_host: PluginHost | None = None
        try:
            if session_factory is not None:
                upstream_client = httpx.AsyncClient(http2=False, timeout=None)
                egress_client = httpx.AsyncClient(timeout=None)
                # CP9: the audit writer reads the per-request session
                # + org_id from a contextvar bound by the forwarder's
                # `bind_request_context` block, so audit rows land
                # under the same RLS axis as the storage writes.
                egress_guard = EgressGuard(audit_writer=session_bound_audit_writer)
                plugin_host = PluginHost(
                    egress_guard=egress_guard,
                    http_client=egress_client,
                    audit_writer=session_bound_audit_writer,
                )
                await plugin_host.on_init()
                app.state.plugin_host = plugin_host
                app.state.egress_guard = egress_guard
                app.state.upstream_client = upstream_client
                # CP9: forwarder's response generator opens a fresh
                # session from here for post-stream writes (the auth
                # middleware's session is committed before the body
                # streams under BaseHTTPMiddleware ordering).
                app.state.session_factory = session_factory
                # `content_level` is the per-row label every storage
                # helper writes — public interface per CLAUDE.md §9,
                # configurable via `LLMTRACK_CONTENT_LEVEL`.
                app.state.content_level = resolved.content_level

            log.info(
                "server.startup",
                version=__version__,
                auth_wired=session_factory is not None,
                plugin_host_wired=plugin_host is not None,
            )
            yield
        finally:
            if plugin_host is not None:
                # Drain plugins first so a shutdown-time flusher can
                # still reach the egress client.
                await plugin_host.on_shutdown()
            if egress_client is not None:
                await egress_client.aclose()
            if upstream_client is not None:
                await upstream_client.aclose()
            if owned_engine is not None:
                await owned_engine.dispose()
            log.info("server.shutdown")

    app = FastAPI(
        title="llm-tracker-server",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    if session_factory is not None:
        app.add_middleware(AuthMiddleware, session_factory=session_factory)

        @app.get("/admin/whoami")
        async def whoami(request: Request) -> dict[str, str | None]:
            # `request.state.session` is the same session the
            # middleware set the GUC on, so reading
            # `current_setting` here returns the value the
            # downstream storage layer (CP9) will see.
            session = request.state.session
            setting = (
                await session.execute(sa.text("SELECT current_setting('app.org_id', true)"))
            ).scalar()
            return {
                "org_id": str(request.state.org_id),
                "app_org_id_setting": setting,
            }

        # Admin routes registered before the catch-all so FastAPI's
        # in-order dispatch reaches them first (ADR-0014).
        @app.get("/admin/plugins")
        async def admin_plugins(request: Request) -> JSONResponse:
            host = getattr(request.app.state, "plugin_host", None)
            payload = host.loaded_plugins() if host is not None else []
            return JSONResponse(payload)

        @app.api_route(
            "/{path:path}",
            methods=["DELETE", "GET", "PATCH", "POST", "PUT"],
        )
        async def proxy(request: Request, path: str) -> StreamingResponse:
            host = getattr(request.app.state, "plugin_host", None)
            client = getattr(request.app.state, "upstream_client", None)
            if client is None:
                # Defensive: lifespan failed to wire an upstream
                # client. Return a clear error instead of crashing
                # inside `forward_request`.
                return JSONResponse(
                    {"detail": "upstream client not initialised"},
                    status_code=503,
                )
            return await forward_request(
                request,
                path,
                http_client=client,
                plugin_host=host,
            )

    return app


app = create_app()
