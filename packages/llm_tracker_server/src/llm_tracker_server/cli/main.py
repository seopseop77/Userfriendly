"""`llm-tracker-server` Typer entry point.

Run via the console script declared in `pyproject.toml`. Each command
opens its own engine + session, so the CLI process exits cleanly without
relying on an external event loop. All commands require
`LLMTRACK_DATABASE_URL` to be set in the environment (or `.env`).

Token issuance shows the plaintext **once** -- after a successful
commit. The operator is responsible for capturing it; the database only
stores the SHA-256 hex hash (`api_tokens.token_hash`, ADR-0020).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

import typer
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession

from llm_tracker_server.auth import tokens as auth_tokens
from llm_tracker_server.config import Settings
from llm_tracker_server.storage import make_engine, make_session_factory

app = typer.Typer(
    help="llm-tracker-server admin CLI",
    no_args_is_help=True,
    add_completion=False,
)
tokens_app = typer.Typer(
    help="Per-org bearer-token management (ADR-0020).",
    no_args_is_help=True,
)
app.add_typer(tokens_app, name="tokens")


@asynccontextmanager
async def _session_scope():
    """Yield an `AsyncSession` against `LLMTRACK_DATABASE_URL`.

    Engine disposal is bracketed so each CLI invocation terminates
    cleanly even when SQLAlchemy is mid-pool-warmup."""
    load_dotenv(override=False)
    settings = Settings()
    if not settings.database_url:
        typer.echo("LLMTRACK_DATABASE_URL is not set", err=True)
        raise typer.Exit(code=2)
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    try:
        async with factory() as session:
            yield session
    finally:
        await engine.dispose()


def _run(coro_factory: Callable[[AsyncSession], Awaitable[None]]) -> None:
    async def _outer() -> None:
        async with _session_scope() as session:
            await coro_factory(session)

    asyncio.run(_outer())


@tokens_app.command("issue")
def issue(
    org: str = typer.Option(..., "--org", help="Org name (created if missing)."),
    name: str | None = typer.Option(None, "--name", help="Optional human-readable token label."),
) -> None:
    """Mint a new bearer token for an org. Prints plaintext exactly once."""

    async def _inner(session: AsyncSession) -> None:
        plaintext, org_id, token_hash = await auth_tokens.issue(
            session, org_name=org, token_name=name
        )
        await session.commit()
        typer.echo(f"org_id={org_id}")
        typer.echo(f"token_hash={token_hash}")
        typer.echo(f"token={plaintext}")
        typer.echo("Store this token now -- it cannot be recovered.", err=True)

    _run(_inner)


@tokens_app.command("revoke")
def revoke(
    token_hash: str = typer.Option(..., "--hash", help="Full SHA-256 hex of the token (64 chars)."),
) -> None:
    """Revoke a token by its hash (sets `revoked_at = now()`)."""

    async def _inner(session: AsyncSession) -> None:
        ok = await auth_tokens.revoke(session, token_hash=token_hash)
        await session.commit()
        if not ok:
            typer.echo("no matching active token", err=True)
            raise typer.Exit(code=1)
        typer.echo("revoked")

    _run(_inner)


@tokens_app.command("list")
def list_tokens(
    org: str | None = typer.Option(None, "--org", help="Filter to one org by name."),
) -> None:
    """List tokens (hash prefix + status). Plaintext is unrecoverable."""

    async def _inner(session: AsyncSession) -> None:
        rows = await auth_tokens.list_for_org(session, org_name=org)
        for tok, org_row in rows:
            status = "revoked" if tok.revoked_at is not None else "active"
            label = tok.name or "-"
            typer.echo(
                f"{tok.token_hash[:12]}...  org={org_row.name}  name={label}  status={status}"
            )

    _run(_inner)


if __name__ == "__main__":
    app()
