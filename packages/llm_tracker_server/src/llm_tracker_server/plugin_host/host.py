"""PluginHost: server-side entry-point loader + lifecycle dispatcher (ADR-0019).

CP8 port of :class:`llm_tracker.plugin_host.host.PluginHost`. The
shape differs from the local sidecar in three ways:

1. ``mode=`` is dropped (ADR-0019 §Decision item 1). The mode-keyed
   capability-denial layer (``policy.py``) is not ported either.
2. ``user_opted_in=`` is dropped (CP8 plan; supersedes ADR-0016
   §Mode-R interim consent surface). The per-org token bound by
   :class:`~llm_tracker_server.auth.AuthMiddleware` is the new
   identity anchor; the upcoming ADR-#2 will set the consent
   surface.
3. ``session_factory=`` is replaced by an injected :data:`AuditWriter`
   callable. CP9 will wire the production writer through the
   per-request :class:`AsyncSession` (already bound to ``app.org_id``
   by the auth middleware) so audit rows carry ``org_id``. For CP8
   the default writer is a no-op so the host runs without storage
   access -- the audit *call sites* land here.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from importlib.metadata import entry_points
from typing import Any

import httpx
from llm_tracker_sdk import Abort, BasePlugin, Block, ContentLevel, HookContext, Pass, Transform
from llm_tracker_sdk.manifest import PluginManifest

from llm_tracker_server.egress_guard.client import HostEgressClient
from llm_tracker_server.egress_guard.guard import EgressGuard

from .context import make_hook_context
from .hooks import HOOK_TIMEOUT, SHUTDOWN_HOOK_TIMEOUT
from .manifest import find_manifest

# Keyword-only audit writer contract. Mirrors the local-sidecar
# ``write_audit`` helper's signature so CP9's session-bound writer can
# drop in without changing any call site here.
AuditWriter = Callable[..., Awaitable[None]]


async def _noop_audit_writer(**_kwargs: object) -> None:
    """CP8 default: discard the row. CP9 replaces with a session-bound writer."""
    return None


class PluginHost:
    """Loads plugins, wires per-plugin egress clients, dispatches hooks.

    Parameters
    ----------
    egress_guard:
        The shared :class:`EgressGuard` that owns the manifest
        registrations. ``None`` is allowed for harnesses / tests that
        don't exercise the egress path.
    plugins_disabled:
        Operator-supplied denylist matched on ``manifest.name``
        (ADR-0013). Frozen so reloads can't mutate it under us.
    http_client:
        Shared :class:`httpx.AsyncClient` for plugin egress
        (ADR-0015). Owned and closed by the caller, *after* every
        plugin's :meth:`BasePlugin.on_shutdown` has run, so a
        shutdown-time flusher can still drain.
    audit_writer:
        Async callable invoked once per audit-emitting event. CP9
        will wire a session-bound writer.
    """

    def __init__(
        self,
        *,
        egress_guard: EgressGuard | None = None,
        plugins_disabled: frozenset[str] | set[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        audit_writer: AuditWriter | None = None,
    ) -> None:
        self._egress_guard = egress_guard
        self._http_client = http_client
        self._plugins_disabled: frozenset[str] = frozenset(plugins_disabled or ())
        self._audit_writer: AuditWriter = audit_writer or _noop_audit_writer
        self._plugins: list[BasePlugin] = []
        # Manifests in load order (also the dispatch order). Backs
        # `loaded_plugins()` for the `/admin/plugins` introspection
        # endpoint (ADR-0014).
        self._manifests: list[PluginManifest] = []
        # CP10: per-plugin clamp pulled from the manifest's
        # `min_content_level`. The dispatch loop sets `ctx._ceiling`
        # per plugin from this map (same pattern as `ctx.egress`).
        # A plugin missing from the map defaults to L3 so unit tests
        # that bypass `load_plugins` keep the permissive shape they
        # had before CP10 landed.
        self._min_levels: dict[str, ContentLevel] = {}
        # Per-exchange HookContext (ADR-0012). Created by
        # `begin_exchange`, reused across all per-exchange hook
        # dispatches for that exchange, cleared by `end_exchange`.
        # Dispatchers fall back to a fresh context if no exchange has
        # been begun (so unit tests calling `host.on_request_received(
        # "xid")` directly keep working).
        self._exchange_contexts: dict[str, HookContext] = {}

    # -- HookContext lifecycle (ADR-0012) ----------------------------------

    def begin_exchange(
        self,
        exchange_id: str,
        *,
        request_body: bytes | None = None,
    ) -> HookContext:
        """Open a per-exchange :class:`HookContext` and stash it for hook dispatch.

        The forwarder calls this once per request, after reading the
        body, so every subsequent hook dispatcher hands the same
        :class:`HookContext` to plugins.
        """
        ctx = make_hook_context(
            session_id="server",
            exchange_id=exchange_id,
            request_body=request_body,
        )
        self._exchange_contexts[exchange_id] = ctx
        return ctx

    def end_exchange(self, exchange_id: str) -> None:
        """Drop the stashed :class:`HookContext` for ``exchange_id``."""
        self._exchange_contexts.pop(exchange_id, None)

    def _ctx_for(self, exchange_id: str) -> HookContext:
        """Return the active context, building a default one on the fly.

        Keeps direct unit-test calls like
        ``host.on_request_received("xid")`` working without forcing
        the caller to remember ``begin_exchange``. Production callers
        (the forwarder) always call ``begin_exchange`` first.
        """
        ctx = self._exchange_contexts.get(exchange_id)
        if ctx is None:
            ctx = make_hook_context(
                session_id="server",
                exchange_id=exchange_id,
            )
        return ctx

    # -- audit helpers -----------------------------------------------------

    async def _audit(self, hook: str, exchange_id: str | None = None) -> None:
        await self._audit_writer(
            kind="hook_invoked",
            hook=hook,
            outcome="ok",
            detail_json=(json.dumps({"exchange_id": exchange_id}) if exchange_id else None),
        )

    async def _audit_fault(self, plugin_name: str, hook: str, reason: str) -> None:
        await self._audit_writer(
            kind="plugin_fault",
            plugin=plugin_name,
            hook=hook,
            outcome="error",
            detail_json=json.dumps({"reason": reason}),
        )

    # -- dispatch helper ---------------------------------------------------

    async def _call(
        self,
        plugin: BasePlugin,
        hook: str,
        coro: Any,
        default: Any,
        *,
        timeout: float = HOOK_TIMEOUT,
    ) -> Any:
        """Run one plugin hook with timeout + exception isolation.

        A fault (crash or timeout) is audit-logged and ``default`` is
        returned so the core request pipeline is never interrupted.
        ``timeout`` defaults to :data:`HOOK_TIMEOUT` for per-exchange
        hooks; ``on_shutdown`` uses :data:`SHUTDOWN_HOOK_TIMEOUT`.
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            await self._audit_fault(plugin.name, hook, "timeout")
        except Exception as exc:
            await self._audit_fault(plugin.name, hook, repr(exc))
        return default

    # -- lifecycle ---------------------------------------------------------

    async def load_plugins(self) -> None:
        for ep in entry_points(group="llm_tracker.plugins"):
            try:
                plugin_class: type[BasePlugin] = ep.load()
            except Exception as exc:
                await self._audit_writer(
                    kind="plugin_loaded",
                    plugin=ep.name,
                    outcome="error",
                    detail_json=json.dumps({"error": str(exc)}),
                )
                continue

            manifest, err = find_manifest(plugin_class)
            if manifest is None:
                await self._audit_writer(
                    kind="manifest_rejected",
                    plugin=ep.name,
                    outcome="denied",
                    detail_json=json.dumps({"reason": err}),
                )
                continue

            if manifest.name in self._plugins_disabled:
                await self._audit_writer(
                    kind="plugin_skipped",
                    plugin=manifest.name,
                    outcome="denied",
                    detail_json=json.dumps({"reason": "disabled_by_config"}),
                )
                continue

            # ADR-0019 retired the mode-keyed capability-denial layer.
            # The manifest's `capabilities` are accepted as declared;
            # runtime egress is enforced by `EgressGuard` per-request.

            if self._egress_guard is not None:
                self._egress_guard.register(manifest)

            plugin = plugin_class()
            # ADR-0015: bind a per-plugin EgressClient at load time so
            # background tasks can call `fetch` outside any hook with
            # stable attribution.
            if self._egress_guard is not None and self._http_client is not None:
                plugin.egress = HostEgressClient(
                    plugin_name=manifest.name,
                    guard=self._egress_guard,
                    http_client=self._http_client,
                )
            self._plugins.append(plugin)
            self._manifests.append(manifest)
            self._min_levels[manifest.name] = manifest.min_content_level
            await self._audit_writer(
                kind="plugin_loaded",
                plugin=plugin.name,
                outcome="ok",
            )

    # -- introspection (ADR-0014) -----------------------------------------

    def loaded_plugins(self) -> list[dict[str, Any]]:
        """Serialisable view of every plugin that passed load-time checks.

        Backs the ``/admin/plugins`` HTTP route. Order matches load
        order, which is also dispatch order. ``allowed_modes`` is
        retained in the payload for backward compatibility with
        existing manifests; the field is ignored by enforcement
        (ADR-0019) but still surfaces in introspection so manifests
        are self-describing.
        """
        return [
            {
                "name": m.name,
                "version": m.version,
                "hooks": list(m.hooks),
                "capabilities": list(m.capabilities),
                "allowed_modes": list(m.allowed_modes),
                "min_content_level": m.min_content_level.name,
            }
            for m in self._manifests
        ]

    async def on_init(self) -> None:
        await self.load_plugins()
        for plugin in self._plugins:
            await self._call(plugin, "on_init", plugin.on_init(), None)
        await self._audit_writer(kind="proxy_started", outcome="ok")

    async def on_shutdown(self) -> None:
        for plugin in self._plugins:
            # Sink plugins drain queues here; the longer
            # `SHUTDOWN_HOOK_TIMEOUT` gives them more headroom than
            # the per-exchange `HOOK_TIMEOUT`.
            await self._call(
                plugin,
                "on_shutdown",
                plugin.on_shutdown(),
                None,
                timeout=SHUTDOWN_HOOK_TIMEOUT,
            )
        await self._audit_writer(kind="proxy_stopped", outcome="ok")

    # -- per-request hooks ------------------------------------------------

    def _bind_plugin_view(self, ctx: HookContext, plugin: BasePlugin) -> None:
        """Re-point per-plugin views on the shared ctx before dispatch.

        Sets ``ctx.egress`` (ADR-0015 per-plugin client) and
        ``ctx._ceiling`` (CP10 manifest-driven clamp). Plugins loaded
        outside ``load_plugins`` (e.g. direct ``host._plugins = [...]``
        assignment in unit tests) get the permissive default
        :data:`ContentLevel.L3`.
        """
        ctx.egress = plugin.egress
        ctx._ceiling = self._min_levels.get(plugin.name, ContentLevel.L3)

    async def on_request_received(self, exchange_id: str) -> Pass | Block:
        await self._audit("on_request_received", exchange_id)
        ctx = self._ctx_for(exchange_id)
        for plugin in self._plugins:
            self._bind_plugin_view(ctx, plugin)
            result = await self._call(
                plugin,
                "on_request_received",
                plugin.on_request_received(exchange_id, ctx),
                Pass(),
            )
            if isinstance(result, Block):
                result.plugin = plugin.name
                return result
        return Pass()

    async def before_forward(self, exchange_id: str) -> Pass | Block | Transform:
        await self._audit("before_forward", exchange_id)
        ctx = self._ctx_for(exchange_id)
        for plugin in self._plugins:
            self._bind_plugin_view(ctx, plugin)
            result = await self._call(
                plugin,
                "before_forward",
                plugin.before_forward(exchange_id, ctx),
                Pass(),
            )
            if isinstance(result, Block):
                result.plugin = plugin.name
                return result
            if isinstance(result, Transform):
                return result
        return Pass()

    async def on_upstream_response_start(self, exchange_id: str) -> Pass | Abort:
        await self._audit("on_upstream_response_start", exchange_id)
        ctx = self._ctx_for(exchange_id)
        for plugin in self._plugins:
            self._bind_plugin_view(ctx, plugin)
            result = await self._call(
                plugin,
                "on_upstream_response_start",
                plugin.on_upstream_response_start(exchange_id, ctx),
                Pass(),
            )
            if isinstance(result, Abort):
                result.plugin = plugin.name
                return result
        return Pass()

    async def on_response_chunk(self, exchange_id: str, chunk: bytes) -> Pass | Abort:
        ctx = self._ctx_for(exchange_id)
        for plugin in self._plugins:
            self._bind_plugin_view(ctx, plugin)
            result = await self._call(
                plugin,
                "on_response_chunk",
                plugin.on_response_chunk(exchange_id, chunk, ctx),
                Pass(),
            )
            if isinstance(result, Abort):
                result.plugin = plugin.name
                return result
        return Pass()

    async def on_response_complete(self, exchange_id: str) -> None:
        await self._audit("on_response_complete", exchange_id)
        ctx = self._ctx_for(exchange_id)
        for plugin in self._plugins:
            self._bind_plugin_view(ctx, plugin)
            await self._call(
                plugin,
                "on_response_complete",
                plugin.on_response_complete(exchange_id, ctx),
                None,
            )

    async def on_persisted(self, exchange_id: str) -> None:
        await self._audit("on_persisted", exchange_id)
        ctx = self._ctx_for(exchange_id)
        for plugin in self._plugins:
            self._bind_plugin_view(ctx, plugin)
            await self._call(
                plugin,
                "on_persisted",
                plugin.on_persisted(exchange_id, ctx),
                None,
            )
