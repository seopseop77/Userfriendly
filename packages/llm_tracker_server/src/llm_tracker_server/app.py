"""FastAPI application: CP1 surface is /healthz only."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI

from llm_tracker_server import __version__
from llm_tracker_server.config import Settings
from llm_tracker_server.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    # `.env` resolves before Settings so file-provided values are visible;
    # `override=False` keeps a shell-exported value authoritative.
    load_dotenv(override=False)
    resolved = settings or Settings()
    configure_logging(resolved.log_level)
    log = structlog.get_logger(__name__)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        log.info("server.startup", version=__version__)
        try:
            yield
        finally:
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

    return app


app = create_app()
