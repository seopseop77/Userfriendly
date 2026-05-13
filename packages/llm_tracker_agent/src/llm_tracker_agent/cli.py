"""``claude-manage`` CLI: ``setup`` writes config, default starts proxy+claude."""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Annotated

import typer
import uvicorn

from llm_tracker_agent.config import CONFIG_PATH, load_config, save_config
from llm_tracker_agent.proxy import make_proxy_app

DEFAULT_SERVER_URL = "https://llm-tracker-server.fly.dev"
DEFAULT_PORT = 18080
READY_TIMEOUT_SECONDS = 3.0
READY_POLL_INTERVAL = 0.05

app = typer.Typer(
    add_completion=False,
    invoke_without_command=True,
    no_args_is_help=False,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


@app.callback()
def _default(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is not None:
        return
    _run(ctx.args)


@app.command(help="Write central-server URL + token to ~/.llm-tracker/config.toml.")
def setup(
    token: Annotated[str, typer.Argument(help="Org API token, e.g. lts_xxxx.")],
    server_url: Annotated[
        str, typer.Option("--server-url", help="Central server base URL.")
    ] = DEFAULT_SERVER_URL,
    port: Annotated[
        int, typer.Option("--port", help="Local loopback port for the proxy.")
    ] = DEFAULT_PORT,
) -> None:
    if not token.strip():
        typer.echo("token must be a non-empty string", err=True)
        raise typer.Exit(code=2)
    save_config(url=server_url, token=token, local_port=port)
    typer.echo(f"Saved {CONFIG_PATH}. Run `claude-manage` to start.")


def _pick_port(preferred: int) -> int:
    """Return ``preferred`` if loopback-bindable, else a free ephemeral port.

    Lets multiple ``claude-manage`` instances coexist: the first wins the
    preferred port, every subsequent instance gets its own ephemeral port
    instead of silently sharing the first instance's proxy. There is a
    micro-race between this probe closing the socket and uvicorn re-binding
    — if it loses, uvicorn fails in its thread and ``_wait_ready`` times
    out with a clear error.
    """
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise OSError("no free loopback port available")


def _wait_ready(port: int, timeout: float = READY_TIMEOUT_SECONDS) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/healthz"
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
            last_err = exc
        time.sleep(READY_POLL_INTERVAL)
    typer.echo(
        f"proxy did not become ready on 127.0.0.1:{port} within {timeout:.1f}s "
        f"(last error: {last_err})",
        err=True,
    )
    raise typer.Exit(code=1)


def _run(extra_args: list[str]) -> None:
    config = load_config()
    port = _pick_port(config.local_port)
    if port != config.local_port:
        typer.echo(
            f"[claude-manage] preferred port {config.local_port} in use; "
            f"this instance is on {port}.",
            err=True,
        )
    proxy_app = make_proxy_app(config)
    server = uvicorn.Server(
        uvicorn.Config(
            proxy_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    )
    threading.Thread(target=server.run, daemon=True).start()
    _wait_ready(port)

    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"

    # NOTE: spec called for ``os.execvp("claude", ...)`` but exec'ing
    # replaces the current Python process image and immediately kills
    # the uvicorn thread, so the proxy disappears before Claude Code
    # can use it. ``subprocess.run`` keeps the parent Python alive (and
    # therefore the proxy) for the lifetime of the Claude session;
    # both exit together.
    try:
        completed = subprocess.run(["claude", *extra_args], env=env, check=False)
    except FileNotFoundError:
        typer.echo("`claude` not found on PATH. Install Claude Code first.", err=True)
        raise typer.Exit(code=127) from None
    raise typer.Exit(code=completed.returncode)


if __name__ == "__main__":  # pragma: no cover - direct module run
    app()
