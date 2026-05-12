"""FastAPI application factory.

CP1 shipped `/healthz`. CP6 layers per-org auth on top: when a session
factory is available (either passed in for tests, or built from
`LLMTRACK_DATABASE_URL` in production), the factory wires the
`AuthMiddleware` and a small `/admin/whoami` introspection route. The
bare `/healthz` path stays public so external probes need no token.

Keeping the session-factory wiring optional preserves the CP1 boot
contract: `python -c "from llm_tracker_server.app import app"` must
succeed even with no database configured.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import sqlalchemy as sa
import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, Request

from llm_tracker_server import __version__
from llm_tracker_server.auth import AuthMiddleware
from llm_tracker_server.config import Settings
from llm_tracker_server.logging import configure_logging
from llm_tracker_server.storage import make_engine, make_session_factory


def create_app(
    settings: Settings | None = None,
    session_factory: Callable[[], object] | None = None,
) -> FastAPI:
    # `.env` resolves before Settings so file-provided values are visible;
    # `override=False` keeps a shell-exported value authoritative.
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
        log.info("server.startup", version=__version__, auth_wired=session_factory is not None)
        try:
            yield
        finally:
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
            # `request.state.session` is the same session the middleware
            # set the GUC on, so reading `current_setting` here returns
            # the value the downstream storage layer (CP9) will see.
            session = request.state.session
            setting = (
                await session.execute(sa.text("SELECT current_setting('app.org_id', true)"))
            ).scalar()
            return {
                "org_id": str(request.state.org_id),
                "app_org_id_setting": setting,
            }

    return app


app = create_app()
