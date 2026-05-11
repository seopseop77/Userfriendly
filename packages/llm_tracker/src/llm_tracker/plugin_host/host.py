"""PluginHost: loads plugins via entry points and dispatches the 8 lifecycle hooks."""

import asyncio
import importlib.resources
import json
import tomllib
from importlib.metadata import entry_points
from typing import Any

import httpx
from llm_tracker_sdk import Abort, BasePlugin, Block, HookContext, Pass, Transform
from llm_tracker_sdk.manifest import PluginManifest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..egress_guard.client import HostEgressClient
from ..egress_guard.guard import EgressGuard
from ..storage.audit import write_audit
from .policy import denied_capabilities

HOOK_TIMEOUT = 5.0  # seconds; a plugin exceeding this is treated as a fault

# `on_shutdown` gets a longer dedicated timeout because background-task
# shapes (queues, flushers, retry workers) legitimately need longer than
# a per-exchange hook to drain. A sink with a non-empty queue + retry
# backoff can easily take >5 s to finish; clipping it would silently
# drop records and audit-log a misleading `plugin_fault timeout`.
SHUTDOWN_HOOK_TIMEOUT = 30.0


class PluginHost:
    def __init__(
        self,
        mode: str,
        session_factory: async_sessionmaker[AsyncSession],
        egress_guard: EgressGuard | None = None,
        plugins_disabled: frozenset[str] | set[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        user_opted_in: bool = False,
    ) -> None:
        self.mode = mode
        self._session_factory = session_factory
        self._egress_guard = egress_guard
        # Shared httpx client for plugin egress (ADR-0015). Owned and closed
        # by the proxy lifespan, *after* every plugin's `on_shutdown` so a
        # shutdown-time flusher can still drain. `None` is allowed for
        # tests / harnesses that don't exercise the egress path.
        self._http_client = http_client
        # Process-wide opt-in stance (ADR-0016). Lifted to True by the
        # operator via `LLMTRACK_USER_OPTED_IN`. Threaded into every
        # `HookContext` produced by `begin_exchange` / `_ctx_for`.
        self._user_opted_in = user_opted_in
        # Operator-supplied denylist matched on `manifest.name` (ADR-0013).
        # Frozen so reloads can't mutate it under us.
        self._plugins_disabled: frozenset[str] = frozenset(plugins_disabled or ())
        self._plugins: list[BasePlugin] = []
        # Loaded manifests in load order. Populated only for plugins that pass
        # every load-time check (ADR-0014); read by `loaded_plugins()` for the
        # `/admin/plugins` introspection endpoint.
        self._manifests: list[PluginManifest] = []
        # Per-exchange HookContext (ADR-0012). Created by `begin_exchange`,
        # reused across all per-exchange hook dispatches for that exchange,
        # and cleared by `end_exchange`. Dispatchers fall back to a fresh
        # context if no exchange has been begun (so unit tests calling
        # `host.on_request_received("xid")` directly keep working).
        self._exchange_contexts: dict[str, HookContext] = {}

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Read-only handle to the host's session factory.

        Lets the forwarder open a session for `record_exchange_timing` /
        `record_exchange_blocked` without reaching into a private
        attribute. Same factory the host uses internally for audit
        writes.
        """
        return self._session_factory

    # -- HookContext lifecycle (ADR-0012) ----------------------------------

    def begin_exchange(
        self,
        exchange_id: str,
        *,
        request_body: bytes | None = None,
    ) -> HookContext:
        """Open a per-exchange `HookContext` and stash it for hook dispatch.

        The forwarder calls this once per request, after reading the
        body, so that every subsequent hook dispatcher can hand the
        same `HookContext` to plugins. The opt-in stance comes from
        the host's startup-time field (ADR-0016) — the forwarder does
        not need to know about it.
        """
        ctx = HookContext(
            session_id="local",
            exchange_id=exchange_id,
            mode=self.mode,
            user_opted_in=self._user_opted_in,
            _raw_request_body=request_body,
        )
        self._exchange_contexts[exchange_id] = ctx
        return ctx

    def end_exchange(self, exchange_id: str) -> None:
        """Drop the stashed `HookContext` for `exchange_id`."""
        self._exchange_contexts.pop(exchange_id, None)

    def _ctx_for(self, exchange_id: str) -> HookContext:
        """Return the active context, building a default one on the fly.

        The fallback keeps direct unit-test calls like
        `host.on_request_received("xid")` working without forcing the
        caller to remember `begin_exchange`. Production callers
        (the forwarder) always call `begin_exchange` first.
        """
        ctx = self._exchange_contexts.get(exchange_id)
        if ctx is None:
            ctx = HookContext(
                session_id="local",
                exchange_id=exchange_id,
                mode=self.mode,
                user_opted_in=self._user_opted_in,
            )
        return ctx

    # -- audit helpers -------------------------------------------------------

    async def _audit(self, hook: str, exchange_id: str | None = None) -> None:
        async with self._session_factory() as session:
            await write_audit(
                session,
                kind="hook_invoked",
                hook=hook,
                outcome="ok",
                detail_json=json.dumps({"exchange_id": exchange_id}) if exchange_id else None,
            )

    async def _audit_fault(self, plugin_name: str, hook: str, reason: str) -> None:
        async with self._session_factory() as session:
            await write_audit(
                session,
                kind="plugin_fault",
                plugin=plugin_name,
                hook=hook,
                outcome="error",
                detail_json=json.dumps({"reason": reason}),
            )

    # -- dispatch helper -----------------------------------------------------

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

        A fault (crash or timeout) is audit-logged and the safe default is
        returned so the core request pipeline is never interrupted.

        `timeout` defaults to `HOOK_TIMEOUT` for per-exchange hooks; the
        `on_shutdown` dispatcher passes `SHUTDOWN_HOOK_TIMEOUT` so a
        plugin's drain (queue flush, retry backoff) can complete.
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError:
            await self._audit_fault(plugin.name, hook, "timeout")
        except Exception as exc:
            await self._audit_fault(plugin.name, hook, repr(exc))
        return default

    # -- manifest loading ----------------------------------------------------

    @staticmethod
    def _find_manifest(plugin_class: type) -> tuple[PluginManifest | None, str]:
        """Locate and parse plugin.toml from the plugin's top-level package.

        Returns (manifest, error_reason). error_reason is '' on success.
        """
        pkg_name = plugin_class.__module__.split(".")[0]
        try:
            ref = importlib.resources.files(pkg_name) / "plugin.toml"
            with ref.open("rb") as fh:
                data = tomllib.load(fh)
        except FileNotFoundError:
            return None, "plugin.toml not found"
        except Exception as exc:
            return None, f"plugin.toml unreadable: {exc}"
        try:
            return PluginManifest.model_validate(data), ""
        except ValidationError as exc:
            return None, f"invalid manifest: {exc}"

    # -- lifecycle ----------------------------------------------------------

    async def load_plugins(self) -> None:
        for ep in entry_points(group="llm_tracker.plugins"):
            try:
                plugin_class: type[BasePlugin] = ep.load()
            except Exception as exc:
                async with self._session_factory() as session:
                    await write_audit(
                        session,
                        kind="plugin_loaded",
                        plugin=ep.name,
                        outcome="error",
                        detail_json=json.dumps({"error": str(exc)}),
                    )
                continue

            manifest, err = self._find_manifest(plugin_class)
            if manifest is None:
                async with self._session_factory() as session:
                    await write_audit(
                        session,
                        kind="manifest_rejected",
                        plugin=ep.name,
                        outcome="denied",
                        detail_json=json.dumps({"reason": err}),
                    )
                continue

            if manifest.name in self._plugins_disabled:
                # ADR-0013: operator-controlled denylist gates the plugin
                # after manifest parse so we have the canonical name.
                async with self._session_factory() as session:
                    await write_audit(
                        session,
                        kind="plugin_skipped",
                        plugin=manifest.name,
                        outcome="denied",
                        detail_json=json.dumps({"reason": "disabled_by_config"}),
                    )
                continue

            denied = denied_capabilities(self.mode, manifest.capabilities)
            if denied:
                async with self._session_factory() as session:
                    await write_audit(
                        session,
                        kind="capability_denied",
                        plugin=manifest.name,
                        outcome="denied",
                        detail_json=json.dumps({"mode": self.mode, "denied": sorted(denied)}),
                    )
                continue

            if self._egress_guard is not None:
                self._egress_guard.register(manifest)

            plugin = plugin_class()
            # ADR-0015: bind a per-plugin EgressClient. Lifetime is per-plugin
            # (not per-exchange), so a background flusher can call `fetch`
            # outside any hook. Audit-log attribution is structural — the
            # plugin name is baked in at construction.
            if self._egress_guard is not None and self._http_client is not None:
                plugin.egress = HostEgressClient(
                    plugin_name=manifest.name,
                    guard=self._egress_guard,
                    http_client=self._http_client,
                )
            self._plugins.append(plugin)
            self._manifests.append(manifest)
            async with self._session_factory() as session:
                await write_audit(session, kind="plugin_loaded", plugin=plugin.name, outcome="ok")

    # -- introspection (ADR-0014) -------------------------------------------

    def loaded_plugins(self) -> list[dict[str, Any]]:
        """Serialisable view of every plugin that passed load-time checks.

        Backs the `/admin/plugins` HTTP route and the `llm-tracker plugins`
        CLI. Order matches load order, which is also dispatch order.
        """
        return [
            {
                "name": m.name,
                "version": m.version,
                "hooks": list(m.hooks),
                "capabilities": list(m.capabilities),
                "allowed_modes": list(m.allowed_modes),
            }
            for m in self._manifests
        ]

    async def on_init(self) -> None:
        await self.load_plugins()
        for plugin in self._plugins:
            await self._call(plugin, "on_init", plugin.on_init(), None)
        async with self._session_factory() as session:
            await write_audit(session, kind="proxy_started", outcome="ok")

    async def on_shutdown(self) -> None:
        for plugin in self._plugins:
            # Sink plugins drain queues here; `SHUTDOWN_HOOK_TIMEOUT` (30 s)
            # gives them more headroom than the per-exchange `HOOK_TIMEOUT`
            # (5 s).
            await self._call(
                plugin,
                "on_shutdown",
                plugin.on_shutdown(),
                None,
                timeout=SHUTDOWN_HOOK_TIMEOUT,
            )
        async with self._session_factory() as session:
            await write_audit(session, kind="proxy_stopped", outcome="ok")

    # -- per-request hooks --------------------------------------------------

    async def on_request_received(self, exchange_id: str) -> Pass | Block:
        await self._audit("on_request_received", exchange_id)
        ctx = self._ctx_for(exchange_id)
        for plugin in self._plugins:
            ctx.egress = plugin.egress  # ADR-0015: per-plugin client for this dispatch
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
            ctx.egress = plugin.egress  # ADR-0015
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
            ctx.egress = plugin.egress  # ADR-0015
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
            ctx.egress = plugin.egress  # ADR-0015
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
            ctx.egress = plugin.egress  # ADR-0015
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
            ctx.egress = plugin.egress  # ADR-0015
            await self._call(
                plugin,
                "on_persisted",
                plugin.on_persisted(exchange_id, ctx),
                None,
            )
