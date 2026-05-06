"""TEST-ONLY token-counter plugin.

Parses Anthropic-shaped SSE usage events out of the streamed response and
writes a row per exchange to a **sidecar** SQLite at
`var/plugin_token_counter.db` (override with
`LLMTRACK_PLUGIN_TOKEN_COUNTER_DB`).

This package is intentionally self-contained:

- It does **not** touch the core `Exchange` table — those token columns are
  reserved for the Phase-2 Extractor.
- It does **not** rely on any host-mediated DB API (none exists yet); it
  opens its own `aiosqlite` connection.

Both choices are temporary. Once the Extractor lands, delete this plugin
along with its sidecar DB. See
`docs/worklog/2026-05-06-test-plugins.md` for context.
"""

from __future__ import annotations

from llm_tracker_sdk import BasePlugin, HookContext, Pass

from .parser import UsageAccumulator
from .storage import UsageRecord, UsageStore


class TokenCounterPlugin(BasePlugin):
    """Aggregate Anthropic SSE `usage` events and persist them per exchange."""

    name = "token_counter"

    def __init__(self, *, store: UsageStore | None = None) -> None:
        # Tests inject an in-memory store; production constructs the
        # default file-backed store on first use.
        self._store: UsageStore | None = store
        self._accumulators: dict[str, UsageAccumulator] = {}

    # -- helpers -----------------------------------------------------------

    async def _ensure_store(self) -> UsageStore:
        if self._store is None:
            self._store = UsageStore.default()
            await self._store.init()
        return self._store

    # -- hooks -------------------------------------------------------------

    async def on_response_chunk(self, exchange_id: str, chunk: bytes, ctx: HookContext) -> Pass:
        acc = self._accumulators.setdefault(exchange_id, UsageAccumulator())
        acc.feed(chunk)
        return Pass()

    async def on_response_complete(self, exchange_id: str, ctx: HookContext) -> None:
        acc = self._accumulators.pop(exchange_id, None)
        if acc is None or not acc.has_usage():
            return
        store = await self._ensure_store()
        await store.write(
            UsageRecord(
                exchange_id=exchange_id,
                model=acc.model,
                input_tokens=acc.input_tokens,
                output_tokens=acc.output_tokens,
                cache_creation_input_tokens=acc.cache_creation_input_tokens,
                cache_read_input_tokens=acc.cache_read_input_tokens,
            )
        )

    async def on_shutdown(self) -> None:
        if self._store is not None:
            await self._store.close()
            self._store = None
        self._accumulators.clear()


__all__ = ["TokenCounterPlugin"]
