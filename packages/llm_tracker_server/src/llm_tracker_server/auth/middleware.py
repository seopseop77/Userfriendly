"""Per-request auth + RLS binding (ADR-0020 Axis 1, header per ADR-0023, + ADR-0018).

A FastAPI/Starlette HTTP middleware. For every request to a non-public
path:

1. Read `X-LLM-Tracker-Token: <token>` -- 401 on missing/empty.
2. Hash the plaintext (SHA-256 hex), look up `api_tokens` filtered to
   non-revoked rows -- 403 on miss.
3. Open a request-scoped `AsyncSession`, issue
   `SET LOCAL ROLE llm_tracker_app` then
   `SELECT set_config('app.org_id', '<uuid>', true)`, attach the
   session and org id to `request.state`, run the downstream handler,
   then commit.

The `SET LOCAL` pair is the contract CP5's RLS policies expect: the
role drop guarantees `FORCE ROW LEVEL SECURITY` actually applies (the
docker-default Postgres superuser would otherwise bypass it), and the
GUC populates the org axis that
`<table>_org_isolation` policies read via `current_setting`.

There is deliberately **no service-role bypass**. ADR-0018 §Decision
item 2 closes that door; the only escape hatch is the `app.role =
'admin'` policy branch, which CP10+ admin tooling will set alongside
`app.org_id` (not in place of it).

`Authorization` is **never read here**: per ADR-0023 it is reserved
for Anthropic pass-through (OAuth bearer or x-api-key, depending on
the client) and flows through the proxy untouched.

Healthz stays public so external uptime probes don't need a token. The
public set is configurable but defaults to `{"/healthz"}` so a config
mistake doesn't accidentally widen it.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import sqlalchemy as sa
import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from llm_tracker_server.auth.tokens import lookup

log = structlog.get_logger(__name__)


_DEFAULT_PUBLIC_PATHS: frozenset[str] = frozenset({"/healthz"})


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        session_factory: Callable[[], object],
        public_paths: frozenset[str] | set[str] | None = None,
    ) -> None:
        super().__init__(app)
        self._session_factory = session_factory
        self._public_paths = (
            frozenset(public_paths) if public_paths is not None else _DEFAULT_PUBLIC_PATHS
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path in self._public_paths:
            return await call_next(request)

        plaintext = request.headers.get("x-llm-tracker-token", "").strip()
        if not plaintext:
            return JSONResponse(
                {"detail": "missing X-LLM-Tracker-Token header"},
                status_code=401,
            )

        async with self._session_factory() as session:
            await session.execute(sa.text("SET LOCAL ROLE llm_tracker_app"))
            token_row = await lookup(session, plaintext)
            if token_row is None:
                # Conflated 'unknown' and 'revoked' on purpose -- see tokens.lookup.
                return JSONResponse(
                    {"detail": "unknown or revoked token"},
                    status_code=403,
                )

            org_id = token_row.org_id
            await session.execute(
                sa.text("SELECT set_config('app.org_id', :v, true)"),
                {"v": str(org_id)},
            )
            request.state.org_id = org_id
            request.state.session = session
            response = await call_next(request)
            await session.commit()
            return response
