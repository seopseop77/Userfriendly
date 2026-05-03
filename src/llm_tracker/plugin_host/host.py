"""PluginHost: loads plugins and dispatches the 8 lifecycle hooks."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..storage.audit import write_audit
from .hooks import Abort, Block, Pass, Transform


class PluginHost:
    """Phase-0 scaffold: no plugins loaded; each hook is dispatched and audit-logged."""

    def __init__(self, mode: str, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.mode = mode
        self._session_factory = session_factory
        self._plugins: list = []

    async def _audit(self, hook: str, exchange_id: str | None = None) -> None:
        async with self._session_factory() as session:
            await write_audit(
                session,
                kind="hook_invoked",
                hook=hook,
                outcome="ok",
                detail_json=f'{{"exchange_id": "{exchange_id}"}}' if exchange_id else None,
            )

    # -- lifecycle ----------------------------------------------------------

    async def on_init(self) -> None:
        async with self._session_factory() as session:
            await write_audit(session, kind="proxy_started", outcome="ok")

    async def on_shutdown(self) -> None:
        async with self._session_factory() as session:
            await write_audit(session, kind="proxy_stopped", outcome="ok")

    # -- per-request hooks --------------------------------------------------

    async def on_request_received(self, exchange_id: str) -> Pass | Block:
        await self._audit("on_request_received", exchange_id)
        return Pass()

    async def before_forward(self, exchange_id: str) -> Pass | Block | Transform:
        await self._audit("before_forward", exchange_id)
        return Pass()

    async def on_upstream_response_start(self, exchange_id: str) -> Pass | Abort:
        await self._audit("on_upstream_response_start", exchange_id)
        return Pass()

    async def on_response_chunk(self, exchange_id: str, chunk: bytes) -> Pass | Abort:
        # No per-chunk audit write to avoid excessive DB traffic.
        return Pass()

    async def on_response_complete(self, exchange_id: str) -> None:
        await self._audit("on_response_complete", exchange_id)

    async def on_persisted(self, exchange_id: str) -> None:
        await self._audit("on_persisted", exchange_id)
