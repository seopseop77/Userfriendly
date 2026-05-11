"""llm-tracker CLI: init, start, audit, plugins."""

import asyncio
from pathlib import Path

import typer

app = typer.Typer(name="llm-tracker", add_completion=False)


@app.command()
def init() -> None:
    """Initialize the config directory and database schema."""
    from alembic.config import Config

    from alembic import command as alembic_cmd

    Path("var").mkdir(exist_ok=True)
    cfg = Config("alembic.ini")
    alembic_cmd.upgrade(cfg, "head")
    typer.echo("llm-tracker initialized.")


@app.command()
def start(
    host: str = typer.Option("127.0.0.1", envvar="LLMTRACK_PROXY_HOST"),
    port: int = typer.Option(8787, envvar="LLMTRACK_PROXY_PORT"),
    mode: str = typer.Option("L", envvar="LLMTRACK_MODE"),
) -> None:
    """Start the proxy server."""
    import uvicorn

    typer.echo(f"Starting llm-tracker proxy — mode={mode} on {host}:{port}")
    uvicorn.run(
        "llm_tracker.proxy.app:app",
        host=host,
        port=port,
        log_level="info",
    )


@app.command()
def audit(
    limit: int = typer.Option(50, help="Max rows to show"),
) -> None:
    """Show recent audit log entries."""
    asyncio.run(_audit_async(limit))


async def _audit_async(limit: int) -> None:
    from sqlalchemy import select, text

    from llm_tracker.config import Settings
    from llm_tracker.storage.database import make_session_factory
    from llm_tracker.storage.models import AuditLog

    settings = Settings()
    factory = make_session_factory(settings.db_url)
    async with factory() as session:
        rows = (
            (await session.execute(select(AuditLog).order_by(text("ts DESC")).limit(limit)))
            .scalars()
            .all()
        )

    if not rows:
        typer.echo("No audit log entries yet.")
        return

    for row in reversed(rows):
        typer.echo(f"{row.ts:>15}  {row.kind:<20}  hook={row.hook or '-':<30}  {row.outcome}")


@app.command()
def plugins(
    host: str = typer.Option("127.0.0.1", envvar="LLMTRACK_PROXY_HOST"),
    port: int = typer.Option(8787, envvar="LLMTRACK_PROXY_PORT"),
) -> None:
    """List plugins currently loaded by the running proxy (ADR-0014)."""
    import httpx

    url = f"http://{host}:{port}/admin/plugins"
    try:
        resp = httpx.get(url, timeout=2.0)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        typer.echo(f"Failed to query proxy at {url}: {exc}", err=True)
        raise typer.Exit(1) from exc

    entries = resp.json()
    if not entries:
        typer.echo("No plugins loaded.")
        return

    for entry in entries:
        hooks = ",".join(entry.get("hooks", [])) or "-"
        modes = ",".join(entry.get("allowed_modes", [])) or "-"
        typer.echo(
            f"{entry['name']:<24}  v{entry['version']:<8}  "
            f"hooks={hooks:<40}  modes={modes}"
        )
