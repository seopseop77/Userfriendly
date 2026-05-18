"""`AnalyticsSink` — writes one row per exchange to `plugin_analytics`."""

from __future__ import annotations

import json
import os
from typing import Any

import sqlalchemy as sa
import structlog
from llm_tracker_sdk import BasePlugin, HookContext, Pass
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from ulid import ULID

DATABASE_URL_ENV = "LLMTRACK_DATABASE_URL"

_INSERT_SQL = sa.text(
    """
    INSERT INTO plugin_analytics (
        id, exchange_id, org_id, model_requested, model_served,
        messages_json, response_json,
        input_tokens, output_tokens, cache_read_tokens,
        cache_write_tokens, stop_reason
    ) VALUES (
        :id, :exchange_id, :org_id, :model_requested, :model_served,
        :messages_json, :response_json,
        :input_tokens, :output_tokens, :cache_read_tokens,
        :cache_write_tokens, :stop_reason
    )
    """
)


def _parse_model_requested(body: str | None) -> str | None:
    """Return model string from a request body, or None if unparseable."""
    if body is None:
        return None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    model = data.get("model")
    return model if isinstance(model, str) else None


class AnalyticsSink(BasePlugin):
    """Stash request on `on_request_received`; write row on `on_persisted`."""

    name = "analytics_sink"

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        # Tests pass a pre-built engine; production constructs one in
        # `on_init` so plugin loading does not depend on the env var
        # being present at import time.
        self._engine: AsyncEngine | None = engine
        self._engine_owned: bool = False
        self._stash: dict[str, str] = {}  # exchange_id -> messages_json
        self._log = structlog.get_logger("analytics_sink")

    async def on_init(self) -> None:
        if self._engine is not None:
            return
        url = os.environ.get(DATABASE_URL_ENV)
        if not url:
            self._log.warning("analytics_sink.disabled", reason="LLMTRACK_DATABASE_URL not set")
            return
        # Match `llm_tracker_server.storage.make_engine` semantics for
        # Supabase pgbouncer transaction-mode (CP13-b).
        self._engine = create_async_engine(url, connect_args={"statement_cache_size": 0})
        self._engine_owned = True

    async def on_shutdown(self) -> None:
        if self._engine_owned and self._engine is not None:
            await self._engine.dispose()

    async def on_request_received(self, exchange_id: str, ctx: HookContext) -> Pass:
        body = ctx.request_text()
        if body is None:
            return Pass()
        self._stash[exchange_id] = body
        return Pass()

    def _build_row(
        self,
        exchange_id: str,
        ctx: HookContext,
        messages_json: str,
    ) -> dict[str, Any]:
        usage = ctx.response_usage()
        return {
            "id": str(ULID()),
            "exchange_id": exchange_id,
            "org_id": ctx.org_id,
            "model_requested": _parse_model_requested(messages_json),
            "model_served": getattr(usage, "model_served", None),
            "messages_json": messages_json,
            "response_json": ctx.response_content_json(),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_tokens": getattr(usage, "cache_read_tokens", None),
            "cache_write_tokens": getattr(usage, "cache_write_tokens", None),
            "stop_reason": getattr(usage, "stop_reason", None),
        }

    async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
        messages_json = self._stash.pop(exchange_id, None)
        if messages_json is None or self._engine is None:
            return
        if ctx.org_id is None:
            self._log.warning("analytics_sink.skip", reason="ctx.org_id missing")
            return
        row = self._build_row(exchange_id, ctx, messages_json)
        try:
            async with self._engine.begin() as conn:
                await conn.execute(_INSERT_SQL, row)
        except Exception as exc:  # pragma: no cover — defensive
            self._log.warning("analytics_sink.insert_failed", error=str(exc))
