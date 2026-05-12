"""EgressGuard allowlist enforcement (CP8 port).

The server-side guard no longer mode-gates anything (ADR-0019), so the
three mode-keyed denial paths from the local sidecar
(``mode_L_denies_egress``, ``mode_X_not_in_allowed_modes``,
``mode_A_requires_single_destination``) are gone. What remains is the
manifest registration + capability declaration + exact-URL match.
Audit writes route through an injected callable instead of a DB
session.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from llm_tracker_sdk.manifest import PluginManifest
from llm_tracker_server.egress_guard.guard import EgressGuard


@pytest.fixture
def captured_audit():
    rows: list[dict[str, Any]] = []

    async def writer(**kwargs: Any) -> None:
        rows.append(kwargs)

    writer.rows = rows  # type: ignore[attr-defined]
    return writer


def _manifest(
    name: str = "p",
    *,
    capabilities: list[str] | None = None,
    egress_destinations: list[str] | None = None,
) -> PluginManifest:
    return PluginManifest(
        name=name,
        version="0.1.0",
        capabilities=capabilities if capabilities is not None else ["egress_http"],
        egress_destinations=(
            egress_destinations if egress_destinations is not None else ["https://api.example.com"]
        ),
        # Field is retained on the SDK for back-compat but ignored
        # by the server guard.
        allowed_modes=["L", "A", "R"],
    )


# -- denial paths ----------------------------------------------------------


async def test_unregistered_plugin_denied(captured_audit):
    guard = EgressGuard(audit_writer=captured_audit)

    allowed = await guard.check(plugin="ghost", url="https://api.example.com")

    assert allowed is False
    row = captured_audit.rows[0]
    assert row["kind"] == "egress_blocked"
    assert json.loads(row["detail_json"])["reason"] == "no_manifest_registered"


async def test_missing_capability_denied(captured_audit):
    guard = EgressGuard(audit_writer=captured_audit)
    guard.register(_manifest(capabilities=[], egress_destinations=[]))

    allowed = await guard.check(plugin="p", url="https://api.example.com")

    assert allowed is False
    row = captured_audit.rows[0]
    assert json.loads(row["detail_json"])["reason"] == "capability_not_declared:egress_http"


async def test_destination_not_in_allowlist_denied(captured_audit):
    guard = EgressGuard(audit_writer=captured_audit)
    guard.register(_manifest(egress_destinations=["https://api.example.com"]))

    allowed = await guard.check(plugin="p", url="https://evil.example.org")

    assert allowed is False
    row = captured_audit.rows[0]
    assert json.loads(row["detail_json"])["reason"] == "destination_not_in_allowlist"


# -- allow paths -----------------------------------------------------------


async def test_single_destination_match_allowed(captured_audit):
    guard = EgressGuard(audit_writer=captured_audit)
    guard.register(_manifest(egress_destinations=["https://api.example.com"]))

    allowed = await guard.check(plugin="p", url="https://api.example.com")

    assert allowed is True
    row = captured_audit.rows[0]
    assert row["kind"] == "egress_attempt"
    assert row["outcome"] == "ok"
    assert row["destination"] == "https://api.example.com"
    assert row["capability"] == "egress_http"
    # No reason on allow -> detail_json absent.
    assert row["detail_json"] is None


async def test_multiple_destinations_each_match_allowed(captured_audit):
    """ADR-0019 retired Mode A's single-destination rule; both URLs allowed."""
    guard = EgressGuard(audit_writer=captured_audit)
    guard.register(
        _manifest(
            egress_destinations=[
                "https://api.example.com",
                "https://api2.example.com",
            ]
        )
    )

    a = await guard.check(plugin="p", url="https://api.example.com")
    b = await guard.check(plugin="p", url="https://api2.example.com")

    assert a is True
    assert b is True
    assert all(r["kind"] == "egress_attempt" for r in captured_audit.rows)


async def test_register_overwrites_previous_manifest(captured_audit):
    guard = EgressGuard(audit_writer=captured_audit)
    guard.register(_manifest(egress_destinations=["https://old.example.com"]))
    guard.register(_manifest(egress_destinations=["https://new.example.com"]))

    old = await guard.check(plugin="p", url="https://old.example.com")
    new = await guard.check(plugin="p", url="https://new.example.com")

    assert old is False
    assert new is True


async def test_exact_match_no_wildcards(captured_audit):
    """Allowlist entries must be exact strings; near-miss URLs deny."""
    guard = EgressGuard(audit_writer=captured_audit)
    guard.register(_manifest(egress_destinations=["https://api.example.com"]))

    near_misses = [
        "https://api.example.com/",
        "http://api.example.com",
        "https://api.example.com/v1",
        "https://x.api.example.com",
    ]
    for url in near_misses:
        assert await guard.check(plugin="p", url=url) is False
