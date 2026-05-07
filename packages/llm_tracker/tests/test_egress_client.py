"""Unit tests for `HostEgressClient` (ADR-0015).

Covers the three load-bearing behaviours:

- Happy path: guard allows -> httpx is called -> EgressResponse round-trips.
- Denied path: guard denies (e.g. Mode L, missing manifest, off-allowlist URL)
  -> `EgressDenied` raised, httpx never called.
- Cross-plugin attribution: client bound to plugin A cannot reach plugin B's
  allowlisted destination, *even though* both manifests are registered.
"""

import json

import httpx
import pytest
from llm_tracker.egress_guard.client import HostEgressClient
from llm_tracker.egress_guard.guard import EgressGuard
from llm_tracker.storage.models import AuditLog, Base
from llm_tracker_sdk.egress import EgressDenied, EgressResponse
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


def _manifest(name: str, dest: str, modes: list[str] | None = None) -> PluginManifest:
    return PluginManifest(
        name=name,
        version="0.1.0",
        capabilities=["egress_http"],
        egress_destinations=[dest],
        allowed_modes=modes or ["R"],
    )


async def _audit_rows(factory) -> list[AuditLog]:
    async with factory() as session:
        return list((await session.execute(select(AuditLog))).scalars())


async def test_fetch_happy_path_returns_egress_response(session_factory):
    """Guard allows -> httpx is called -> response materialised verbatim."""
    guard = EgressGuard(mode="R", session_factory=session_factory)
    guard.register(_manifest("plugin_a", "https://example.test/sink"))

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, headers={"x-server-id": "abc"}, content=b"ok")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ec = HostEgressClient(plugin_name="plugin_a", guard=guard, http_client=client)
        resp = await ec.fetch(
            "https://example.test/sink",
            body=b"hello",
            headers={"x-key": "v"},
        )

    assert isinstance(resp, EgressResponse)
    assert resp.status_code == 201
    assert resp.headers["x-server-id"] == "abc"
    assert resp.body == b"ok"
    assert len(seen) == 1
    assert str(seen[0].url) == "https://example.test/sink"
    assert seen[0].method == "POST"
    assert seen[0].headers["x-key"] == "v"
    assert seen[0].content == b"hello"

    rows = await _audit_rows(session_factory)
    assert any(r.kind == "egress_attempt" and r.outcome == "ok" for r in rows)


async def test_fetch_denied_in_mode_l_raises_without_calling_httpx(session_factory):
    """Mode L denies all egress; httpx must not be invoked."""
    guard = EgressGuard(mode="L", session_factory=session_factory)
    guard.register(_manifest("plugin_a", "https://example.test/sink", modes=["L", "R"]))

    httpx_hits: list[httpx.Request] = []

    def explode(request: httpx.Request) -> httpx.Response:
        httpx_hits.append(request)
        return httpx.Response(500)

    transport = httpx.MockTransport(explode)
    async with httpx.AsyncClient(transport=transport) as client:
        ec = HostEgressClient(plugin_name="plugin_a", guard=guard, http_client=client)
        with pytest.raises(EgressDenied) as excinfo:
            await ec.fetch("https://example.test/sink", body=b"hi")

    assert excinfo.value.url == "https://example.test/sink"
    assert excinfo.value.reason == "denied_by_egress_guard"
    assert httpx_hits == []  # httpx must never have been touched

    rows = await _audit_rows(session_factory)
    blocked = [r for r in rows if r.kind == "egress_blocked"]
    assert len(blocked) == 1
    assert json.loads(blocked[0].detail_json)["reason"] == "mode_L_denies_egress"


async def test_fetch_cross_plugin_destination_blocked(session_factory):
    """A client bound to plugin_a cannot reach plugin_b's allowlist entry,
    even when both manifests are registered with the guard.

    This is the structural attribution guarantee promised by ADR-0015:
    the plugin name baked into the client at construction is what the
    guard checks against, so a plugin literally cannot egress as someone
    else.
    """
    guard = EgressGuard(mode="R", session_factory=session_factory)
    guard.register(_manifest("plugin_a", "https://a.test/sink"))
    guard.register(_manifest("plugin_b", "https://b.test/sink"))

    httpx_hits: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        httpx_hits.append(request)
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ec_a = HostEgressClient(plugin_name="plugin_a", guard=guard, http_client=client)
        with pytest.raises(EgressDenied):
            await ec_a.fetch("https://b.test/sink")  # plugin_b's destination

    assert httpx_hits == []
    rows = await _audit_rows(session_factory)
    blocked = [r for r in rows if r.kind == "egress_blocked"]
    assert len(blocked) == 1
    # The audit row attributes the *attempt* to plugin_a, not plugin_b.
    assert blocked[0].plugin == "plugin_a"
    assert blocked[0].destination == "https://b.test/sink"


async def test_fetch_default_method_is_post(session_factory):
    """ADR-0015 surface: `method` defaults to POST (the dominant sink shape)."""
    guard = EgressGuard(mode="R", session_factory=session_factory)
    guard.register(_manifest("plugin_a", "https://example.test/sink"))

    seen_method: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_method.append(request.method)
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ec = HostEgressClient(plugin_name="plugin_a", guard=guard, http_client=client)
        await ec.fetch("https://example.test/sink")

    assert seen_method == ["POST"]
