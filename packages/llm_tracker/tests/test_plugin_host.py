"""Integration tests: PluginHost dispatches hooks and writes audit log entries."""

import asyncio
import json

import llm_tracker.plugin_host.host as host_mod
import pytest
from llm_tracker.egress_guard.guard import EgressGuard
from llm_tracker.plugin_host.host import PluginHost
from llm_tracker.storage.models import AuditLog, Base
from llm_tracker_sdk import BasePlugin, Block, Pass
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


async def _audit_rows(factory) -> list[AuditLog]:
    async with factory() as session:
        return list((await session.execute(select(AuditLog))).scalars())


async def test_on_init_writes_proxy_started(session_factory):
    host = PluginHost(mode="L", session_factory=session_factory)
    await host.on_init()
    kinds = {r.kind for r in await _audit_rows(session_factory)}
    assert "proxy_started" in kinds


async def test_hook_invocations_logged(session_factory):
    host = PluginHost(mode="L", session_factory=session_factory)
    await host.on_request_received("xid-001")
    await host.before_forward("xid-001")
    await host.on_upstream_response_start("xid-001")
    await host.on_response_complete("xid-001")
    await host.on_persisted("xid-001")

    hooks = {r.hook for r in await _audit_rows(session_factory) if r.hook}
    assert hooks == {
        "on_request_received",
        "before_forward",
        "on_upstream_response_start",
        "on_response_complete",
        "on_persisted",
    }


async def test_on_shutdown_writes_proxy_stopped(session_factory):
    host = PluginHost(mode="L", session_factory=session_factory)
    await host.on_shutdown()
    kinds = {r.kind for r in await _audit_rows(session_factory)}
    assert "proxy_stopped" in kinds


# -- fault isolation --------------------------------------------------------


class _CrashPlugin(BasePlugin):
    name = "crasher"

    async def on_request_received(self, exchange_id: str) -> Pass | Block:
        raise RuntimeError("boom")


class _SlowPlugin(BasePlugin):
    name = "slower"

    async def on_request_received(self, exchange_id: str) -> Pass | Block:
        await asyncio.sleep(999)
        return Pass()


async def test_crashing_plugin_does_not_propagate(session_factory):
    host = PluginHost(mode="L", session_factory=session_factory)
    host._plugins = [_CrashPlugin()]

    result = await host.on_request_received("xid-crash")

    assert isinstance(result, Pass)
    rows = await _audit_rows(session_factory)
    fault = next((r for r in rows if r.kind == "plugin_fault"), None)
    assert fault is not None
    assert fault.plugin == "crasher"
    assert fault.outcome == "error"


async def test_timeout_plugin_does_not_propagate(monkeypatch, session_factory):
    monkeypatch.setattr(host_mod, "HOOK_TIMEOUT", 0.05)
    host = PluginHost(mode="L", session_factory=session_factory)
    host._plugins = [_SlowPlugin()]

    result = await host.on_request_received("xid-slow")

    assert isinstance(result, Pass)
    rows = await _audit_rows(session_factory)
    fault = next((r for r in rows if r.kind == "plugin_fault"), None)
    assert fault is not None
    assert fault.plugin == "slower"
    assert fault.outcome == "error"


# -- manifest validation ----------------------------------------------------


class _NoManifestPlugin(BasePlugin):
    name = "no_manifest"


class _FakeEP:
    name = "no_manifest"

    def load(self):
        return _NoManifestPlugin


async def test_load_plugins_rejects_missing_manifest(monkeypatch, session_factory):
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_FakeEP()])
    host = PluginHost(mode="L", session_factory=session_factory)
    await host.load_plugins()

    assert host._plugins == []
    rows = await _audit_rows(session_factory)
    rejected = next((r for r in rows if r.kind == "manifest_rejected"), None)
    assert rejected is not None
    assert rejected.plugin == "no_manifest"
    assert rejected.outcome == "denied"


# -- egress guard wiring ---------------------------------------------------


class _AllowedPlugin(BasePlugin):
    name = "allowed"


class _AllowedEP:
    name = "allowed"

    def load(self):
        return _AllowedPlugin


async def test_load_plugins_registers_manifest_with_egress_guard(
    monkeypatch, session_factory
):
    fake_manifest = PluginManifest(
        name="allowed",
        version="0.1.0",
        capabilities=["egress_http"],
        egress_destinations=["https://api.example.com"],
        allowed_modes=["L", "A", "R"],
    )
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_AllowedEP()])
    monkeypatch.setattr(
        PluginHost,
        "_find_manifest",
        staticmethod(lambda _cls: (fake_manifest, "")),
    )

    guard = EgressGuard(mode="R", session_factory=session_factory)
    host = PluginHost(mode="R", session_factory=session_factory, egress_guard=guard)
    await host.load_plugins()

    assert len(host._plugins) == 1
    assert await guard.check(plugin="allowed", url="https://api.example.com") is True


async def test_load_plugins_skips_egress_register_when_manifest_invalid(
    monkeypatch, session_factory
):
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_FakeEP()])
    guard = EgressGuard(mode="R", session_factory=session_factory)
    host = PluginHost(mode="R", session_factory=session_factory, egress_guard=guard)
    await host.load_plugins()

    assert host._plugins == []
    assert await guard.check(plugin="no_manifest", url="https://x") is False


# -- mode x capability policy at load time --------------------------------


async def test_load_plugins_rejects_egress_http_in_mode_L(monkeypatch, session_factory):
    """Mode L denies the egress_http capability at declaration time (design.md §8)."""
    fake_manifest = PluginManifest(
        name="allowed",
        version="0.1.0",
        capabilities=["egress_http"],
        egress_destinations=["https://api.example.com"],
        allowed_modes=["L", "A", "R"],
    )
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_AllowedEP()])
    monkeypatch.setattr(
        PluginHost,
        "_find_manifest",
        staticmethod(lambda _cls: (fake_manifest, "")),
    )

    guard = EgressGuard(mode="L", session_factory=session_factory)
    host = PluginHost(mode="L", session_factory=session_factory, egress_guard=guard)
    await host.load_plugins()

    assert host._plugins == []
    rows = await _audit_rows(session_factory)
    denied = next((r for r in rows if r.kind == "capability_denied"), None)
    assert denied is not None
    assert denied.plugin == "allowed"
    assert denied.outcome == "denied"
    assert json.loads(denied.detail_json) == {"mode": "L", "denied": ["egress_http"]}
    # Egress register must not have been called for a rejected plugin.
    assert "allowed" not in guard._manifests


async def test_load_plugins_accepts_egress_http_in_mode_R(monkeypatch, session_factory):
    """Same manifest that Mode L rejects loads cleanly under Mode R."""
    fake_manifest = PluginManifest(
        name="allowed",
        version="0.1.0",
        capabilities=["egress_http"],
        egress_destinations=["https://api.example.com"],
        allowed_modes=["L", "A", "R"],
    )
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_AllowedEP()])
    monkeypatch.setattr(
        PluginHost,
        "_find_manifest",
        staticmethod(lambda _cls: (fake_manifest, "")),
    )

    host = PluginHost(mode="R", session_factory=session_factory)
    await host.load_plugins()

    assert len(host._plugins) == 1
    rows = await _audit_rows(session_factory)
    assert not any(r.kind == "capability_denied" for r in rows)
