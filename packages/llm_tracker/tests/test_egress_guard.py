"""Unit tests: EgressGuard mode policy + manifest allowlist enforcement."""

import json

import pytest
from llm_tracker.egress_guard.guard import EgressGuard
from llm_tracker.storage.models import AuditLog, Base
from llm_tracker_sdk.manifest import PluginManifest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _manifest(
    name: str = "p",
    *,
    capabilities: list[str] | None = None,
    egress_destinations: list[str] | None = None,
    allowed_modes: list[str] | None = None,
) -> PluginManifest:
    return PluginManifest(
        name=name,
        version="0.1.0",
        capabilities=capabilities if capabilities is not None else ["egress_http"],
        egress_destinations=(
            egress_destinations
            if egress_destinations is not None
            else ["https://api.example.com"]
        ),
        allowed_modes=allowed_modes if allowed_modes is not None else ["L", "A", "R"],
    )


async def _audit_rows(factory) -> list[AuditLog]:
    async with factory() as session:
        return list((await session.execute(select(AuditLog))).scalars())


# -- denial paths ----------------------------------------------------------


async def test_mode_L_denies_even_with_valid_manifest(session_factory):
    guard = EgressGuard(mode="L", session_factory=session_factory)
    guard.register(_manifest())

    allowed = await guard.check(plugin="p", url="https://api.example.com")

    assert allowed is False
    rows = await _audit_rows(session_factory)
    assert len(rows) == 1
    assert rows[0].kind == "egress_blocked"
    assert rows[0].outcome == "denied"
    assert json.loads(rows[0].detail_json)["reason"] == "mode_L_denies_egress"


async def test_unregistered_plugin_denied(session_factory):
    guard = EgressGuard(mode="R", session_factory=session_factory)

    allowed = await guard.check(plugin="ghost", url="https://api.example.com")

    assert allowed is False
    rows = await _audit_rows(session_factory)
    assert json.loads(rows[0].detail_json)["reason"] == "no_manifest_registered"


async def test_mode_not_in_allowed_modes_denied(session_factory):
    guard = EgressGuard(mode="A", session_factory=session_factory)
    guard.register(_manifest(allowed_modes=["R"]))

    allowed = await guard.check(plugin="p", url="https://api.example.com")

    assert allowed is False
    rows = await _audit_rows(session_factory)
    assert json.loads(rows[0].detail_json)["reason"] == "mode_A_not_in_allowed_modes"


async def test_missing_capability_denied(session_factory):
    guard = EgressGuard(mode="R", session_factory=session_factory)
    guard.register(
        _manifest(capabilities=[], egress_destinations=[])
    )  # no egress_http, no destinations

    allowed = await guard.check(plugin="p", url="https://api.example.com")

    assert allowed is False
    rows = await _audit_rows(session_factory)
    assert (
        json.loads(rows[0].detail_json)["reason"]
        == "capability_not_declared:egress_http"
    )


async def test_destination_not_in_allowlist_denied(session_factory):
    guard = EgressGuard(mode="R", session_factory=session_factory)
    guard.register(_manifest(egress_destinations=["https://api.example.com"]))

    allowed = await guard.check(plugin="p", url="https://evil.example.org")

    assert allowed is False
    rows = await _audit_rows(session_factory)
    assert (
        json.loads(rows[0].detail_json)["reason"] == "destination_not_in_allowlist"
    )


async def test_mode_A_rejects_multiple_destinations(session_factory):
    guard = EgressGuard(mode="A", session_factory=session_factory)
    guard.register(
        _manifest(
            egress_destinations=[
                "https://api.example.com",
                "https://api2.example.com",
            ]
        )
    )

    allowed = await guard.check(plugin="p", url="https://api.example.com")

    assert allowed is False
    rows = await _audit_rows(session_factory)
    assert (
        json.loads(rows[0].detail_json)["reason"]
        == "mode_A_requires_single_destination"
    )


# -- allow paths -----------------------------------------------------------


async def test_mode_A_single_destination_match_allowed(session_factory):
    guard = EgressGuard(mode="A", session_factory=session_factory)
    guard.register(_manifest(egress_destinations=["https://api.example.com"]))

    allowed = await guard.check(plugin="p", url="https://api.example.com")

    assert allowed is True
    rows = await _audit_rows(session_factory)
    assert rows[0].kind == "egress_attempt"
    assert rows[0].outcome == "ok"
    assert rows[0].destination == "https://api.example.com"
    assert rows[0].capability == "egress_http"
    assert json.loads(rows[0].detail_json) == {"mode": "A"}


async def test_mode_R_multiple_destinations_match_allowed(session_factory):
    guard = EgressGuard(mode="R", session_factory=session_factory)
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
    rows = await _audit_rows(session_factory)
    assert all(r.kind == "egress_attempt" for r in rows)
    assert {r.destination for r in rows} == {
        "https://api.example.com",
        "https://api2.example.com",
    }


async def test_register_overwrites_previous_manifest(session_factory):
    guard = EgressGuard(mode="R", session_factory=session_factory)
    guard.register(_manifest(egress_destinations=["https://old.example.com"]))
    guard.register(_manifest(egress_destinations=["https://new.example.com"]))

    old = await guard.check(plugin="p", url="https://old.example.com")
    new = await guard.check(plugin="p", url="https://new.example.com")

    assert old is False
    assert new is True


async def test_exact_match_no_wildcards(session_factory):
    """Allowlist entries must be exact strings; suffix/prefix variants deny."""
    guard = EgressGuard(mode="R", session_factory=session_factory)
    guard.register(_manifest(egress_destinations=["https://api.example.com"]))

    near_misses = [
        "https://api.example.com/",
        "http://api.example.com",
        "https://api.example.com/v1",
        "https://x.api.example.com",
    ]
    for url in near_misses:
        assert await guard.check(plugin="p", url=url) is False
