"""CLI helpers: port selection + argv dispatch / pass-through behavior."""

from __future__ import annotations

import socket
import sys

import click
import pytest
from llm_tracker_agent import cli
from llm_tracker_agent.cli import _pick_port


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_pick_port_returns_preferred_when_free() -> None:
    # Kernel just handed us this port; reopening the same number is
    # almost always still free in the next instant.
    candidate = _free_loopback_port()
    assert _pick_port(candidate) == candidate


def test_pick_port_falls_back_when_preferred_taken() -> None:
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        holder.bind(("127.0.0.1", 0))
        taken = holder.getsockname()[1]
        chosen = _pick_port(taken)
        assert chosen != taken
        assert 1024 <= chosen <= 65535
    finally:
        holder.close()


def test_app_forwards_unknown_flags_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # Regression: Typer's group parsing used to reject ``--``-prefixed
    # flags as unknown subcommand names; the new ``app()`` bypasses it on
    # the default path so flags meant for ``claude`` survive intact.
    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(cli, "_run", lambda argv: captured.setdefault("argv", argv))
    monkeypatch.setattr(
        sys, "argv", ["claude-manage", "--dangerously-skip-permissions", "-p", "hi"]
    )

    cli.app()

    assert captured["argv"] == ["--dangerously-skip-permissions", "-p", "hi"]


def test_app_forwards_no_args_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, list[str]] = {}
    monkeypatch.setattr(cli, "_run", lambda argv: captured.setdefault("argv", argv))
    monkeypatch.setattr(sys, "argv", ["claude-manage"])

    cli.app()

    assert captured["argv"] == []


def test_app_dispatches_setup_subcommand(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {}

    def fake_setup_cli() -> None:
        # Typer reads sys.argv at invocation; capture what it would see.
        seen["argv"] = sys.argv[1:]

    monkeypatch.setattr(cli, "_setup_cli", fake_setup_cli)
    monkeypatch.setattr(sys, "argv", ["claude-manage", "setup", "lts_xyz", "--port", "9999"])

    cli.app()

    # The literal "setup" token is stripped so the single-command Typer
    # sees the token + options as its own arguments.
    assert seen["argv"] == ["lts_xyz", "--port", "9999"]


def test_app_translates_run_exit_to_systemexit(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv: list[str]) -> None:
        raise click.exceptions.Exit(code=42)

    monkeypatch.setattr(cli, "_run", fake_run)
    monkeypatch.setattr(sys, "argv", ["claude-manage", "--foo"])

    with pytest.raises(SystemExit) as excinfo:
        cli.app()
    assert excinfo.value.code == 42
