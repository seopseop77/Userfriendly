"""Integration tests: PluginHost dispatches hooks and writes audit log entries."""

import asyncio
import json

import llm_tracker.plugin_host.host as host_mod
import pytest
from llm_tracker.egress_guard.guard import EgressGuard
from llm_tracker.plugin_host.host import PluginHost
from llm_tracker.plugin_host.signing import VerifyResult
from llm_tracker.storage.models import AuditLog, Base
from llm_tracker_sdk import BasePlugin, Block, HookContext, Pass
from llm_tracker_sdk.manifest import PluginManifest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _bypass_verifier(monkeypatch) -> None:
    """Force `_verify_manifest` to VERIFIED for tests that exercise other paths.

    The bundled `keys.toml` is intentionally empty during the cleanup pass,
    and monkeypatched fake plugins ship no `plugin.toml.sig` file. Tests
    that target manifest validation, capability policy, or guard wiring
    need the verifier short-circuited so those paths are reachable.
    """
    monkeypatch.setattr(
        PluginHost,
        "_verify_manifest",
        lambda self, _cls: (VerifyResult.VERIFIED, "test-signer"),
    )


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

    async def on_request_received(
        self, exchange_id: str, ctx: HookContext
    ) -> Pass | Block:
        raise RuntimeError("boom")


class _SlowPlugin(BasePlugin):
    name = "slower"

    async def on_request_received(
        self, exchange_id: str, ctx: HookContext
    ) -> Pass | Block:
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
    _bypass_verifier(monkeypatch)

    guard = EgressGuard(mode="R", session_factory=session_factory)
    host = PluginHost(mode="R", session_factory=session_factory, egress_guard=guard)
    await host.load_plugins()

    assert len(host._plugins) == 1
    assert await guard.check(plugin="allowed", url="https://api.example.com") is True


async def test_load_plugins_populates_egress_manifests_and_audits_attempt(
    monkeypatch, session_factory
):
    """After load_plugins(), the manifest is in `_manifests` and check() audits.

    Pins the proxy-boot wiring contract: PluginHost(..., egress_guard=guard)
    pushes every accepted manifest into the guard, and a subsequent
    EgressGuard.check() writes an `egress_attempt` row to audit_log.
    """
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
    _bypass_verifier(monkeypatch)

    guard = EgressGuard(mode="R", session_factory=session_factory)
    host = PluginHost(mode="R", session_factory=session_factory, egress_guard=guard)
    await host.load_plugins()

    assert "allowed" in guard._manifests
    assert guard._manifests["allowed"] is fake_manifest

    allowed = await guard.check(plugin="allowed", url="https://api.example.com")
    assert allowed is True
    rows = await _audit_rows(session_factory)
    attempt = next((r for r in rows if r.kind == "egress_attempt"), None)
    assert attempt is not None
    assert attempt.plugin == "allowed"
    assert attempt.destination == "https://api.example.com"
    assert attempt.outcome == "ok"


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
    _bypass_verifier(monkeypatch)

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
    _bypass_verifier(monkeypatch)

    host = PluginHost(mode="R", session_factory=session_factory)
    await host.load_plugins()

    assert len(host._plugins) == 1
    rows = await _audit_rows(session_factory)
    assert not any(r.kind == "capability_denied" for r in rows)


# -- manifest signature verification (ADR-0008) ---------------------------


class _RealHelloWorldEP:
    """Entry point that loads the real bundled HelloWorldPlugin class.

    Used by the integration test below to exercise the full
    `entry_points -> _find_manifest -> _verify_manifest` pipeline against
    the actual `plugin.toml` and `plugin.toml.sig` files that ship with
    `llm_tracker_plugin_hello_world`.
    """

    name = "hello_world"

    def load(self):
        from llm_tracker_plugin_hello_world import HelloWorldPlugin

        return HelloWorldPlugin


async def test_load_plugins_verifies_real_hello_world_signature(
    monkeypatch, session_factory
):
    """The bundled hello_world plugin loads cleanly under real registry+sig.

    ADR-0008 hard-reject contract: this test fails if either the bundled
    `keys.toml` is missing the signing developer's public key or the
    plugin's sibling `plugin.toml.sig` no longer matches the manifest.
    """
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_RealHelloWorldEP()])

    host = PluginHost(mode="L", session_factory=session_factory)
    await host.load_plugins()

    assert len(host._plugins) == 1
    rows = await _audit_rows(session_factory)
    assert not any(r.kind == "manifest_rejected" for r in rows)
    loaded = next((r for r in rows if r.kind == "plugin_loaded"), None)
    assert loaded is not None
    assert loaded.plugin == "hello_world"
    assert loaded.outcome == "ok"


async def test_load_plugins_rejects_when_signature_missing(monkeypatch, session_factory):
    """If `plugin.toml.sig` is absent, load_plugins writes manifest_rejected.

    Driven by monkeypatching `_verify_manifest` to return SIGNATURE_MISSING
    so we exercise the loader's reject path without touching the real .sig
    on disk. The verifier's own file-absent path is already covered by
    `test_signing.py`.
    """
    fake_manifest = PluginManifest(
        name="unsigned",
        version="0.1.0",
        capabilities=[],
        egress_destinations=[],
        allowed_modes=["L", "A", "R"],
    )
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_AllowedEP()])
    monkeypatch.setattr(
        PluginHost,
        "_find_manifest",
        staticmethod(lambda _cls: (fake_manifest, "")),
    )
    monkeypatch.setattr(
        PluginHost,
        "_verify_manifest",
        lambda self, _cls: (VerifyResult.SIGNATURE_MISSING, None),
    )

    host = PluginHost(mode="L", session_factory=session_factory)
    await host.load_plugins()

    assert host._plugins == []
    rows = await _audit_rows(session_factory)
    rejected = next((r for r in rows if r.kind == "manifest_rejected"), None)
    assert rejected is not None
    assert rejected.plugin == "unsigned"
    assert rejected.outcome == "denied"
    assert json.loads(rejected.detail_json) == {"reason": "signature_missing"}


async def test_load_plugins_records_signer_when_key_not_in_registry(
    monkeypatch, session_factory
):
    """SIGNING_KEY_NOT_IN_REGISTRY surfaces the asserted signer in audit detail."""
    fake_manifest = PluginManifest(
        name="orphan",
        version="0.1.0",
        capabilities=[],
        egress_destinations=[],
        allowed_modes=["L", "A", "R"],
    )
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_AllowedEP()])
    monkeypatch.setattr(
        PluginHost,
        "_find_manifest",
        staticmethod(lambda _cls: (fake_manifest, "")),
    )
    monkeypatch.setattr(
        PluginHost,
        "_verify_manifest",
        lambda self, _cls: (VerifyResult.SIGNING_KEY_NOT_IN_REGISTRY, "stranger"),
    )

    host = PluginHost(mode="L", session_factory=session_factory)
    await host.load_plugins()

    assert host._plugins == []
    rows = await _audit_rows(session_factory)
    rejected = next((r for r in rows if r.kind == "manifest_rejected"), None)
    assert rejected is not None
    assert json.loads(rejected.detail_json) == {
        "reason": "signing_key_not_in_registry",
        "signer": "stranger",
    }


# -- HookContext propagation (ADR-0012) -----------------------------------


class _CtxCapturePlugin(BasePlugin):
    """Records the HookContext instance handed to each hook for assertions."""

    name = "ctx_capture"

    def __init__(self) -> None:
        self.received: list[HookContext] = []

    async def on_request_received(
        self, exchange_id: str, ctx: HookContext
    ) -> Pass | Block:
        self.received.append(ctx)
        return Pass()

    async def before_forward(
        self, exchange_id: str, ctx: HookContext
    ) -> Pass | Block:
        self.received.append(ctx)
        return Pass()

    async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
        self.received.append(ctx)


async def test_begin_exchange_passes_ctx_to_each_hook(session_factory):
    """ADR-0012: begin_exchange + every per-exchange hook hands the same ctx."""
    plugin = _CtxCapturePlugin()
    host = PluginHost(mode="L", session_factory=session_factory)
    host._plugins = [plugin]

    host.begin_exchange("ex-101", request_body=b"user message body")

    await host.on_request_received("ex-101")
    await host.before_forward("ex-101")
    await host.on_persisted("ex-101")

    assert len(plugin.received) == 3
    # Same instance reused across hooks for the same exchange.
    assert plugin.received[0] is plugin.received[1]
    assert plugin.received[1] is plugin.received[2]

    ctx = plugin.received[0]
    assert ctx.exchange_id == "ex-101"
    assert ctx.mode == "L"
    assert ctx.session_id == "local"
    assert ctx.user_opted_in is False
    # Mode L: ceiling L1; L1 request returns the body text.
    from llm_tracker_sdk import ContentLevel

    assert ctx.request_text(ContentLevel.L1) == "user message body"


async def test_dispatcher_falls_back_to_default_ctx_when_no_begin_exchange(
    session_factory,
):
    """Direct dispatcher calls without begin_exchange still work.

    Production callers (the forwarder) always call `begin_exchange`, but
    unit-test callers that just dispatch a single hook should not have
    to. The host's `_ctx_for` builds a default `HookContext` on the fly.
    """
    plugin = _CtxCapturePlugin()
    host = PluginHost(mode="R", session_factory=session_factory)
    host._plugins = [plugin]

    # No begin_exchange.
    await host.on_request_received("ex-202")

    assert len(plugin.received) == 1
    fallback = plugin.received[0]
    assert fallback.exchange_id == "ex-202"
    assert fallback.mode == "R"
    # No body was provided, so request_text returns None at any level.
    from llm_tracker_sdk import ContentLevel

    assert fallback.request_text(ContentLevel.L3) is None


async def test_user_opt_in_lifts_ceiling_in_mode_r(session_factory):
    """begin_exchange with user_opted_in=True lifts the Mode R ceiling to L3."""
    plugin = _CtxCapturePlugin()
    host = PluginHost(mode="R", session_factory=session_factory)
    host._plugins = [plugin]

    host.begin_exchange("ex-303", request_body=b"deep raw text", user_opted_in=True)
    await host.on_request_received("ex-303")

    ctx = plugin.received[0]
    from llm_tracker_sdk import ContentLevel

    # Mode R + opt-in: ceiling lifts to L3, so L3 request returns full text.
    assert ctx.request_text(ContentLevel.L3) == "deep raw text"
    # Default Mode R (no opt-in) would have capped at L1; this test pins
    # that the begin_exchange-supplied flag actually propagates.
    assert ctx.user_opted_in is True


async def test_end_exchange_drops_ctx(session_factory):
    """end_exchange removes the ctx from the host's per-exchange map."""
    host = PluginHost(mode="L", session_factory=session_factory)
    host.begin_exchange("ex-404", request_body=b"x")
    assert "ex-404" in host._exchange_contexts

    host.end_exchange("ex-404")
    assert "ex-404" not in host._exchange_contexts
