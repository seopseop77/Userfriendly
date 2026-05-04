"""PluginHost: loads plugins via entry points and dispatches the 8 lifecycle hooks."""

import json
from importlib.metadata import entry_points

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..storage.audit import write_audit
from .base import BasePlugin
from .hooks import Abort, Block, Pass, Transform


class PluginHost:
    def __init__(self, mode: str, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.mode = mode
        self._session_factory = session_factory
        self._plugins: list[BasePlugin] = []

    async def _audit(self, hook: str, exchange_id: str | None = None) -> None:
        async with self._session_factory() as session:
            await write_audit(
                session,
                kind="hook_invoked",
                hook=hook,
                outcome="ok",
                detail_json=json.dumps({"exchange_id": exchange_id}) if exchange_id else None,
            )

    # -- lifecycle ----------------------------------------------------------

    async def load_plugins(self) -> None:
        for ep in entry_points(group="llm_tracker.plugins"):
            try:
                plugin: BasePlugin = ep.load()()
                self._plugins.append(plugin)
                async with self._session_factory() as session:
                    await write_audit(
                        session, kind="plugin_loaded", plugin=plugin.name, outcome="ok"
                    )
            except Exception as exc:
                async with self._session_factory() as session:
                    await write_audit(
                        session,
                        kind="plugin_loaded",
                        plugin=ep.name,
                        outcome="error",
                        detail_json=json.dumps({"error": str(exc)}),
                    )

    async def on_init(self) -> None:
        await self.load_plugins()
        for plugin in self._plugins:
            await plugin.on_init()
        async with self._session_factory() as session:
            await write_audit(session, kind="proxy_started", outcome="ok")

    async def on_shutdown(self) -> None:
        for plugin in self._plugins:
            await plugin.on_shutdown()
        async with self._session_factory() as session:
            await write_audit(session, kind="proxy_stopped", outcome="ok")

    # -- per-request hooks --------------------------------------------------

    async def on_request_received(self, exchange_id: str) -> Pass | Block:
        await self._audit("on_request_received", exchange_id)
        for plugin in self._plugins:
            result = await plugin.on_request_received(exchange_id)
            if isinstance(result, Block):
                return result
        return Pass()

    async def before_forward(self, exchange_id: str) -> Pass | Block | Transform:
        await self._audit("before_forward", exchange_id)
        for plugin in self._plugins:
            result = await plugin.before_forward(exchange_id)
            if isinstance(result, (Block, Transform)):
                return result
        return Pass()

    async def on_upstream_response_start(self, exchange_id: str) -> Pass | Abort:
        await self._audit("on_upstream_response_start", exchange_id)
        for plugin in self._plugins:
            result = await plugin.on_upstream_response_start(exchange_id)
            if isinstance(result, Abort):
                return result
        return Pass()

    async def on_response_chunk(self, exchange_id: str, chunk: bytes) -> Pass | Abort:
        for plugin in self._plugins:
            result = await plugin.on_response_chunk(exchange_id, chunk)
            if isinstance(result, Abort):
                return result
        return Pass()

    async def on_response_complete(self, exchange_id: str) -> None:
        await self._audit("on_response_complete", exchange_id)
        for plugin in self._plugins:
            await plugin.on_response_complete(exchange_id)

    async def on_persisted(self, exchange_id: str) -> None:
        await self._audit("on_persisted", exchange_id)
        for plugin in self._plugins:
            await plugin.on_persisted(exchange_id)
