"""Operator CLI surface (`llm-tracker-server ...`).

CP6 ships only the `tokens` subcommand tree (ADR-0020 Axis 1
issuance / revocation / listing). Later checkpoints can hang
subcommands off the same Typer root without touching the entry point.

The Typer `app` lives in `.main`. Re-exporting it here would trigger a
runpy warning under `python -m llm_tracker_server.cli.main`; the
production console script targets `llm_tracker_server.cli.main:app`
directly, so the re-export gains nothing.
"""
