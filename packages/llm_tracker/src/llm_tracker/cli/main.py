"""llm-tracker CLI: init, start, audit, generate-key, sign-plugin."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(name="llm-tracker", add_completion=False)

KEYRING_SERVICE = "llm-tracker-signing"


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


@app.command(name="generate-key")
def generate_key(
    name: Annotated[str, typer.Argument(help="Signer name (matches keys.toml entry)")],
) -> None:
    """Generate an ed25519 keypair, store private key in OS keychain, print public hex.

    Per ADR-0008, each developer holds a personal signing key. The private
    half stays in the OS keychain (`keyring` library); the public half is
    pasted into `packages/llm_tracker/src/llm_tracker/trust/keys.toml`.
    """
    import keyring
    from nacl.signing import SigningKey

    existing = keyring.get_password(KEYRING_SERVICE, name)
    if existing is not None:
        typer.echo(
            f"Refusing to overwrite an existing key for signer {name!r} in the keychain.",
            err=True,
        )
        typer.echo(
            "Delete it from the keychain manually first if you really want to rotate.",
            err=True,
        )
        raise typer.Exit(1)

    sk = SigningKey.generate()
    private_hex = bytes(sk).hex()
    public_hex = bytes(sk.verify_key).hex()
    keyring.set_password(KEYRING_SERVICE, name, private_hex)

    typer.echo(f"Stored private key for {name!r} in the OS keychain.")
    typer.echo("")
    typer.echo("Add this entry to packages/llm_tracker/src/llm_tracker/trust/keys.toml:")
    typer.echo("")
    typer.echo("[[key]]")
    typer.echo(f'name        = "{name}"')
    typer.echo(f'public_key  = "{public_hex}"')


@app.command(name="sign-plugin")
def sign_plugin(
    plugin_pkg_path: Annotated[
        Path,
        typer.Argument(help="Path to the plugin package directory containing plugin.toml"),
    ],
    signer: str = typer.Option(..., "--signer", help="Signer name (matches keychain key)"),
) -> None:
    """Sign a plugin's `plugin.toml` and write a sibling `plugin.toml.sig`.

    Uses the keychain-stored private key for `--signer`. The signature
    covers the byte-exact contents of `plugin.toml` (ADR-0008
    canonicalization rule). The output blob is TOML with `signer` and
    `signature` (hex) fields, matching `plugin_host.signing.verify_manifest_signature`.
    """
    import keyring
    from nacl.signing import SigningKey

    candidates = [
        plugin_pkg_path / "plugin.toml",
        *plugin_pkg_path.glob("src/*/plugin.toml"),
    ]
    manifest_path = next((p for p in candidates if p.is_file()), None)
    if manifest_path is None:
        typer.echo(
            f"plugin.toml not found at {plugin_pkg_path / 'plugin.toml'} "
            f"or {plugin_pkg_path / 'src/*/plugin.toml'}.",
            err=True,
        )
        raise typer.Exit(1)

    private_hex = keyring.get_password(KEYRING_SERVICE, signer)
    if private_hex is None:
        typer.echo(
            f"No keychain key for signer {signer!r}. "
            f"Run `llm-tracker generate-key {signer}` first.",
            err=True,
        )
        raise typer.Exit(1)

    sk = SigningKey(bytes.fromhex(private_hex))
    manifest_bytes = manifest_path.read_bytes()
    signature = sk.sign(manifest_bytes).signature

    sig_path = manifest_path.with_name("plugin.toml.sig")
    sig_path.write_text(
        f'signer    = "{signer}"\nsignature = "{signature.hex()}"\n',
        encoding="utf-8",
    )
    typer.echo(f"Wrote {sig_path}")
