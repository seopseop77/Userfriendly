"""PluginHost: loads plugins via entry points and dispatches the 8 lifecycle hooks."""

import asyncio
import importlib.resources
import json
import tomllib
from importlib.metadata import entry_points
from typing import Any

from llm_tracker_sdk import Abort, BasePlugin, Block, Pass, Transform
from llm_tracker_sdk.manifest import PluginManifest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..egress_guard.guard import EgressGuard
from ..storage.audit import write_audit
from .policy import denied_capabilities

HOOK_TIMEOUT = 5.0  # seconds; a plugin exceeding this is treated as a fault


class PluginHost:
    def __init__(
        self,
        mode: str,
        session_factory: async_sessionmaker[AsyncSession],
        egress_guard: EgressGuard | None = None,
    ) -> None:
        self.mode = mode
        self._session_factory = session_factory
        self._egress_guard = egress_guard
        self._plugins: list[BasePlugin] = []

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

    async def _call(self, plugin: BasePlugin, hook: str, coro: Any, default: Any) -> Any:
        """Run one plugin hook with timeout + exception isolation.

        A fault (crash or timeout) is audit-logged and the safe default is
        returned so the core request pipeline is never interrupted.
        """
        try:
            return await asyncio.wait_for(coro, timeout=HOOK_TIMEOUT)
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

            denied = denied_capabilities(self.mode, manifest.capabilities)
            if denied:
                async with self._session_factory() as session:
                    await write_audit(
                        session,
                        kind="capability_denied",
                        plugin=manifest.name,
                        outcome="denied",
                        detail_json=json.dumps(
                            {"mode": self.mode, "denied": sorted(denied)}
                        ),
                    )
                continue

            if self._egress_guard is not None:
                self._egress_guard.register(manifest)

            plugin = plugin_class()
            self._plugins.append(plugin)
            async with self._session_factory() as session:
                await write_audit(session, kind="plugin_loaded", plugin=plugin.name, outcome="ok")

    async def on_init(self) -> None:
        await self.load_plugins()
        for plugin in self._plugins:
            await self._call(plugin, "on_init", plugin.on_init(), None)
        async with self._session_factory() as session:
            await write_audit(session, kind="proxy_started", outcome="ok")

    async def on_shutdown(self) -> None:
        for plugin in self._plugins:
            await self._call(plugin, "on_shutdown", plugin.on_shutdown(), None)
        async with self._session_factory() as session:
            await write_audit(session, kind="proxy_stopped", outcome="ok")

    # -- per-request hooks --------------------------------------------------

    async def on_request_received(self, exchange_id: str) -> Pass | Block:
        await self._audit("on_request_received", exchange_id)
        for plugin in self._plugins:
            result = await self._call(
                plugin,
                "on_request_received",
                plugin.on_request_received(exchange_id),
                Pass(),
            )
            if isinstance(result, Block):
                return result
        return Pass()

    async def before_forward(self, exchange_id: str) -> Pass | Block | Transform:
        await self._audit("before_forward", exchange_id)
        for plugin in self._plugins:
            result = await self._call(
                plugin,
                "before_forward",
                plugin.before_forward(exchange_id),
                Pass(),
            )
            if isinstance(result, (Block, Transform)):
                return result
        return Pass()

    async def on_upstream_response_start(self, exchange_id: str) -> Pass | Abort:
        await self._audit("on_upstream_response_start", exchange_id)
        for plugin in self._plugins:
            result = await self._call(
                plugin,
                "on_upstream_response_start",
                plugin.on_upstream_response_start(exchange_id),
                Pass(),
            )
            if isinstance(result, Abort):
                return result
        return Pass()

    async def on_response_chunk(self, exchange_id: str, chunk: bytes) -> Pass | Abort:
        for plugin in self._plugins:
            result = await self._call(
                plugin,
                "on_response_chunk",
                plugin.on_response_chunk(exchange_id, chunk),
                Pass(),
            )
            if isinstance(result, Abort):
                return result
        return Pass()

    async def on_response_complete(self, exchange_id: str) -> None:
        await self._audit("on_response_complete", exchange_id)
        for plugin in self._plugins:
            await self._call(
                plugin,
                "on_response_complete",
                plugin.on_response_complete(exchange_id),
                None,
            )

    async def on_persisted(self, exchange_id: str) -> None:
        await self._audit("on_persisted", exchange_id)
        for plugin in self._plugins:
            await self._call(
                plugin,
                "on_persisted",
                plugin.on_persisted(exchange_id),
                None,
            )
