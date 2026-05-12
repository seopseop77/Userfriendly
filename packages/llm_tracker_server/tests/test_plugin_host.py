"""PluginHost dispatch + lifecycle (CP8 port of the local-sidecar tests).

The server-side host drops ``mode=`` / ``user_opted_in=`` (ADR-0019,
ADR-0020) and routes audit writes through an injected callable so
storage is decoupled. Tests use a list-capturing writer to assert
behaviour without needing a database (CP9 will reintroduce the
DB-coupled audit-row assertions when storage writes land).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import llm_tracker_server.plugin_host.host as host_mod
import pytest
from llm_tracker_sdk import BasePlugin, Block, HookContext, Pass
from llm_tracker_sdk.manifest import PluginManifest
from llm_tracker_server.egress_guard.guard import EgressGuard
from llm_tracker_server.plugin_host.host import PluginHost


@pytest.fixture
def captured_audit():
    rows: list[dict[str, Any]] = []

    async def writer(**kwargs: Any) -> None:
        rows.append(kwargs)

    writer.rows = rows  # type: ignore[attr-defined]
    return writer


# -- lifecycle audit emissions --------------------------------------------


async def test_on_init_emits_proxy_started(captured_audit):
    host = PluginHost(audit_writer=captured_audit)
    await host.on_init()
    kinds = {r["kind"] for r in captured_audit.rows}
    assert "proxy_started" in kinds


async def test_per_exchange_hooks_emit_hook_invoked(captured_audit):
    host = PluginHost(audit_writer=captured_audit)
    await host.on_request_received("xid-001")
    await host.before_forward("xid-001")
    await host.on_upstream_response_start("xid-001")
    await host.on_response_complete("xid-001")
    await host.on_persisted("xid-001")

    hooks = {r["hook"] for r in captured_audit.rows if r.get("hook")}
    assert hooks == {
        "on_request_received",
        "before_forward",
        "on_upstream_response_start",
        "on_response_complete",
        "on_persisted",
    }


async def test_on_shutdown_emits_proxy_stopped(captured_audit):
    host = PluginHost(audit_writer=captured_audit)
    await host.on_shutdown()
    kinds = {r["kind"] for r in captured_audit.rows}
    assert "proxy_stopped" in kinds


# -- fault isolation ------------------------------------------------------


class _CrashPlugin(BasePlugin):
    name = "crasher"

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        raise RuntimeError("boom")


class _SlowPlugin(BasePlugin):
    name = "slower"

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        await asyncio.sleep(999)
        return Pass()


async def test_crashing_plugin_does_not_propagate(captured_audit):
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [_CrashPlugin()]

    result = await host.on_request_received("xid-crash")

    assert isinstance(result, Pass)
    fault = next((r for r in captured_audit.rows if r["kind"] == "plugin_fault"), None)
    assert fault is not None
    assert fault["plugin"] == "crasher"
    assert fault["outcome"] == "error"


async def test_timeout_plugin_does_not_propagate(monkeypatch, captured_audit):
    monkeypatch.setattr(host_mod, "HOOK_TIMEOUT", 0.05)
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [_SlowPlugin()]

    result = await host.on_request_received("xid-slow")

    assert isinstance(result, Pass)
    fault = next((r for r in captured_audit.rows if r["kind"] == "plugin_fault"), None)
    assert fault is not None
    assert fault["plugin"] == "slower"


# -- on_shutdown longer timeout (CP7 sink prerequisite carried over) ------


class _SlowShutdownPlugin(BasePlugin):
    """Sleeps inside ``on_shutdown`` to mimic a sink draining its queue."""

    name = "slow-shutdown"

    def __init__(self, sleep_s: float) -> None:
        self._sleep_s = sleep_s
        self.completed = False

    async def on_shutdown(self) -> None:
        await asyncio.sleep(self._sleep_s)
        self.completed = True


async def test_on_shutdown_uses_longer_timeout_than_per_exchange_hooks(monkeypatch, captured_audit):
    """`SHUTDOWN_HOOK_TIMEOUT` covers a drain longer than `HOOK_TIMEOUT`."""
    monkeypatch.setattr(host_mod, "HOOK_TIMEOUT", 0.05)
    monkeypatch.setattr(host_mod, "SHUTDOWN_HOOK_TIMEOUT", 1.0)

    plugin = _SlowShutdownPlugin(sleep_s=0.2)
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [plugin]

    await host.on_shutdown()

    assert plugin.completed is True
    faults = [
        r
        for r in captured_audit.rows
        if r["kind"] == "plugin_fault" and r["plugin"] == "slow-shutdown"
    ]
    assert faults == []
    assert any(r["kind"] == "proxy_stopped" for r in captured_audit.rows)


async def test_on_shutdown_still_faults_past_shutdown_timeout(monkeypatch, captured_audit):
    """Past `SHUTDOWN_HOOK_TIMEOUT` the dispatcher still cuts the plugin off."""
    monkeypatch.setattr(host_mod, "HOOK_TIMEOUT", 0.05)
    monkeypatch.setattr(host_mod, "SHUTDOWN_HOOK_TIMEOUT", 0.1)

    plugin = _SlowShutdownPlugin(sleep_s=0.5)
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [plugin]

    await host.on_shutdown()

    fault = next(
        (
            r
            for r in captured_audit.rows
            if r["kind"] == "plugin_fault" and r["plugin"] == "slow-shutdown"
        ),
        None,
    )
    assert fault is not None
    assert fault["outcome"] == "error"


# -- manifest validation --------------------------------------------------


class _NoManifestPlugin(BasePlugin):
    name = "no_manifest"


class _FakeEP:
    name = "no_manifest"

    def load(self):
        return _NoManifestPlugin


async def test_load_plugins_rejects_missing_manifest(monkeypatch, captured_audit):
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_FakeEP()])
    host = PluginHost(audit_writer=captured_audit)
    await host.load_plugins()

    assert host._plugins == []
    rejected = next((r for r in captured_audit.rows if r["kind"] == "manifest_rejected"), None)
    assert rejected is not None
    assert rejected["plugin"] == "no_manifest"
    assert rejected["outcome"] == "denied"


# -- egress guard wiring --------------------------------------------------


class _AllowedPlugin(BasePlugin):
    name = "allowed"


class _AllowedEP:
    name = "allowed"

    def load(self):
        return _AllowedPlugin


async def test_load_plugins_registers_manifest_with_egress_guard(monkeypatch, captured_audit):
    fake_manifest = PluginManifest(
        name="allowed",
        version="0.1.0",
        capabilities=["egress_http"],
        egress_destinations=["https://api.example.com"],
        allowed_modes=["L", "A", "R"],
    )
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_AllowedEP()])
    monkeypatch.setattr(
        host_mod,
        "find_manifest",
        staticmethod(lambda _cls: (fake_manifest, "")),
    )
    guard = EgressGuard(audit_writer=captured_audit)
    host = PluginHost(egress_guard=guard, audit_writer=captured_audit)
    await host.load_plugins()

    assert len(host._plugins) == 1
    assert await guard.check(plugin="allowed", url="https://api.example.com") is True
    # And the egress-attempt row landed.
    attempt = next((r for r in captured_audit.rows if r["kind"] == "egress_attempt"), None)
    assert attempt is not None
    assert attempt["plugin"] == "allowed"
    assert attempt["destination"] == "https://api.example.com"


# -- ADR-0019: mode-keyed denial is gone ----------------------------------


async def test_load_plugins_no_longer_mode_gates_egress_http(monkeypatch, captured_audit):
    """ADR-0019 retired the L/A/R modes. A manifest declaring
    ``egress_http`` loads without any ``capability_denied`` audit row,
    regardless of any (now ignored) ``allowed_modes`` value."""
    fake_manifest = PluginManifest(
        name="allowed",
        version="0.1.0",
        capabilities=["egress_http"],
        egress_destinations=["https://api.example.com"],
        # `allowed_modes` is still part of the SDK schema for back-
        # compat, but the server host ignores the value entirely.
        allowed_modes=["L"],
    )
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_AllowedEP()])
    monkeypatch.setattr(
        host_mod,
        "find_manifest",
        staticmethod(lambda _cls: (fake_manifest, "")),
    )
    host = PluginHost(audit_writer=captured_audit)
    await host.load_plugins()

    assert len(host._plugins) == 1
    assert not any(r["kind"] == "capability_denied" for r in captured_audit.rows)


# -- disable-by-config (ADR-0013) -----------------------------------------


async def test_load_plugins_skips_disabled_by_config(monkeypatch, captured_audit):
    """`plugins_disabled` denylist short-circuits load with a `plugin_skipped` row."""
    fake_manifest = PluginManifest(
        name="disabled_one",
        version="0.1.0",
        capabilities=[],
        egress_destinations=[],
        allowed_modes=["L", "A", "R"],
    )
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_AllowedEP()])
    monkeypatch.setattr(
        host_mod,
        "find_manifest",
        staticmethod(lambda _cls: (fake_manifest, "")),
    )

    host = PluginHost(
        plugins_disabled=frozenset({"disabled_one"}),
        audit_writer=captured_audit,
    )
    await host.load_plugins()

    assert host._plugins == []
    skipped = next((r for r in captured_audit.rows if r["kind"] == "plugin_skipped"), None)
    assert skipped is not None
    assert skipped["plugin"] == "disabled_one"
    assert json.loads(skipped["detail_json"]) == {"reason": "disabled_by_config"}


# -- introspection (ADR-0014) ---------------------------------------------


async def test_loaded_plugins_returns_serialisable_view(monkeypatch, captured_audit):
    fake_manifest = PluginManifest(
        name="introspect_me",
        version="2.3.4",
        hooks=["on_init", "on_persisted"],
        capabilities=["egress_http"],
        egress_destinations=["https://api.example.com"],
        allowed_modes=["L", "A", "R"],
    )
    monkeypatch.setattr(host_mod, "entry_points", lambda **_kw: [_AllowedEP()])
    monkeypatch.setattr(
        host_mod,
        "find_manifest",
        staticmethod(lambda _cls: (fake_manifest, "")),
    )
    host = PluginHost(audit_writer=captured_audit)
    await host.load_plugins()

    view = host.loaded_plugins()
    assert view == [
        {
            "name": "introspect_me",
            "version": "2.3.4",
            "hooks": ["on_init", "on_persisted"],
            "capabilities": ["egress_http"],
            "allowed_modes": ["L", "A", "R"],
        }
    ]


# -- HookContext propagation (ADR-0012) -----------------------------------


class _CtxCapturePlugin(BasePlugin):
    name = "ctx_capture"

    def __init__(self) -> None:
        self.received: list[HookContext] = []

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        self.received.append(ctx)
        return Pass()

    async def before_forward(self, exchange_id: str, ctx: HookContext) -> Pass | Block:
        self.received.append(ctx)
        return Pass()

    async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
        self.received.append(ctx)


async def test_begin_exchange_passes_same_ctx_to_each_hook(captured_audit):
    """ADR-0012: ``begin_exchange`` + every per-exchange hook share the ctx."""
    plugin = _CtxCapturePlugin()
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [plugin]

    host.begin_exchange("ex-101", request_body=b"user message body")

    await host.on_request_received("ex-101")
    await host.before_forward("ex-101")
    await host.on_persisted("ex-101")

    assert len(plugin.received) == 3
    assert plugin.received[0] is plugin.received[1]
    assert plugin.received[1] is plugin.received[2]

    ctx = plugin.received[0]
    assert ctx.exchange_id == "ex-101"
    # CP8 transitional shape: permissive defaults pin L3 visibility
    # until CP10 introduces ``min_content_level`` clamping.
    from llm_tracker_sdk import ContentLevel

    assert ctx.request_text(ContentLevel.L3) == "user message body"
    assert ctx.request_length() == len(b"user message body")


async def test_dispatcher_falls_back_to_default_ctx_when_no_begin_exchange(captured_audit):
    """Direct dispatcher calls without ``begin_exchange`` still work."""
    plugin = _CtxCapturePlugin()
    host = PluginHost(audit_writer=captured_audit)
    host._plugins = [plugin]

    await host.on_request_received("ex-202")

    assert len(plugin.received) == 1
    fallback = plugin.received[0]
    assert fallback.exchange_id == "ex-202"
    # No body provided -> request_text is None at every level.
    from llm_tracker_sdk import ContentLevel

    assert fallback.request_text(ContentLevel.L3) is None


async def test_end_exchange_drops_ctx(captured_audit):
    host = PluginHost(audit_writer=captured_audit)
    host.begin_exchange("ex-404", request_body=b"x")
    assert "ex-404" in host._exchange_contexts
    host.end_exchange("ex-404")
    assert "ex-404" not in host._exchange_contexts
