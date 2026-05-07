"""Tests for the `llm-tracker plugins` CLI subcommand (ADR-0014)."""

from __future__ import annotations

import httpx
import respx
from llm_tracker.cli.main import app
from typer.testing import CliRunner

runner = CliRunner()

_DEFAULT_URL = "http://127.0.0.1:8787/admin/plugins"


def test_plugins_lists_loaded_entries():
    """Happy path: subcommand pretty-prints the loaded set from `/admin/plugins`."""
    payload = [
        {
            "name": "hello_world",
            "version": "0.0.1",
            "hooks": ["on_init"],
            "capabilities": [],
            "allowed_modes": ["L", "A", "R"],
        },
        {
            "name": "token_counter",
            "version": "0.0.1",
            "hooks": ["on_persisted"],
            "capabilities": [],
            "allowed_modes": ["L", "A", "R"],
        },
    ]
    with respx.mock:
        respx.get(_DEFAULT_URL).mock(return_value=httpx.Response(200, json=payload))
        result = runner.invoke(app, ["plugins"])

    assert result.exit_code == 0, result.output
    assert "hello_world" in result.output
    assert "token_counter" in result.output
    assert "v0.0.1" in result.output
    assert "on_init" in result.output
    assert "on_persisted" in result.output


def test_plugins_reports_empty_set():
    """When `/admin/plugins` returns [], the command says so plainly."""
    with respx.mock:
        respx.get(_DEFAULT_URL).mock(return_value=httpx.Response(200, json=[]))
        result = runner.invoke(app, ["plugins"])

    assert result.exit_code == 0, result.output
    assert "No plugins loaded." in result.output


def test_plugins_exits_nonzero_when_proxy_unreachable():
    """Connection error surfaces as exit 1 with a human-readable error."""
    with respx.mock:
        respx.get(_DEFAULT_URL).mock(side_effect=httpx.ConnectError("connect refused"))
        result = runner.invoke(app, ["plugins"])

    assert result.exit_code == 1
    assert "Failed to query proxy" in result.output


def test_plugins_honours_host_port_options():
    """Custom --host/--port reaches the right URL."""
    custom_url = "http://10.0.0.5:9000/admin/plugins"
    with respx.mock:
        respx.get(custom_url).mock(return_value=httpx.Response(200, json=[]))
        result = runner.invoke(
            app, ["plugins", "--host", "10.0.0.5", "--port", "9000"]
        )

    assert result.exit_code == 0, result.output
