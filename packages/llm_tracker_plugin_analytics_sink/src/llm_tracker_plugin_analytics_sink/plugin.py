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

from .classifier import Classification, classify_request

DATABASE_URL_ENV = "LLMTRACK_DATABASE_URL"

_INSERT_SQL = sa.text(
    """
    INSERT INTO plugin_analytics (
        id, exchange_id, org_id, model_requested, model_served,
        messages_json, response_json,
        input_tokens, output_tokens, cache_read_tokens,
        cache_write_tokens, stop_reason,
        turn_kind, turn_seq, slash_commands,
        first_msg_hash, conversation_id
    ) VALUES (
        :id, :exchange_id, :org_id, :model_requested, :model_served,
        :messages_json, :response_json,
        :input_tokens, :output_tokens, :cache_read_tokens,
        :cache_write_tokens, :stop_reason,
        :turn_kind, :turn_seq, :slash_commands,
        :first_msg_hash, :conversation_id
    )
    """
)

# Chain-lookup: most recent row with this `first_msg_hash` in this org.
# Used to (a) decide whether the new row continues an existing
# conversation (`n_messages > prev.n_messages`) or starts a new one
# (identical first-prompt typed twice), and (b) seed turn_seq via a
# follow-up lookup keyed on the resolved conversation_id.
_PREV_BY_HASH_SQL = sa.text(
    """
    SELECT conversation_id,
           length(messages_json) AS msgs_len,
           (messages_json::jsonb -> 'messages') AS msgs
    FROM plugin_analytics
    WHERE first_msg_hash = :first_msg_hash
      AND org_id = :org_id
    ORDER BY created_at DESC
    LIMIT 1
    """
)

_LAST_SEQ_IN_CONV_SQL = sa.text(
    """
    SELECT turn_seq
    FROM plugin_analytics
    WHERE conversation_id = :conversation_id
      AND org_id = :org_id
      AND turn_seq IS NOT NULL
    ORDER BY created_at DESC
    LIMIT 1
    """
)


def _parse_request(body: str | None) -> dict[str, Any] | None:
    """Parse a request body string into a dict, or return None."""
    if body is None:
        return None
    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _model_from_request(parsed: dict[str, Any] | None) -> str | None:
    if parsed is None:
        return None
    model = parsed.get("model")
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
            # The request body sometimes isn't readable yet at this hook
            # (forwarder hasn't drained the body into the context — see
            # HookContext.request_text docstring). Log loudly so the
            # follow-up miss in on_persisted is traceable. on_persisted
            # will re-try and recover when the body is available there.
            self._log.warning("analytics_sink.stash_skipped", exchange_id=exchange_id)
            return Pass()
        self._stash[exchange_id] = body
        return Pass()

    def _build_row(
        self,
        exchange_id: str,
        ctx: HookContext,
        messages_json: str,
        parsed: dict[str, Any] | None,
        classification: Classification,
    ) -> dict[str, Any]:
        usage = ctx.response_usage()
        # `slash_commands` is a list (or None) — sqlalchemy's JSONB
        # binding accepts a Python list directly.
        return {
            "id": str(ULID()),
            "exchange_id": exchange_id,
            "org_id": ctx.org_id,
            "model_requested": _model_from_request(parsed),
            "model_served": getattr(usage, "model_served", None),
            "messages_json": messages_json,
            "response_json": ctx.response_content_json(),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_tokens": getattr(usage, "cache_read_tokens", None),
            "cache_write_tokens": getattr(usage, "cache_write_tokens", None),
            "stop_reason": getattr(usage, "stop_reason", None),
            "turn_kind": classification.turn_kind,
            "turn_seq": None,  # filled by caller after conversation resolution
            "slash_commands": classification.slash_commands,
            "first_msg_hash": classification.first_msg_hash,
            "conversation_id": None,  # filled by caller
        }

    async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
        messages_json = self._stash.pop(exchange_id, None)
        if messages_json is None:
            # Fallback: if the body wasn't ready at on_request_received,
            # try once more here. The context's raw body is typically
            # populated by the forwarder before on_persisted fires.
            messages_json = ctx.request_text()
            if messages_json is None:
                self._log.warning(
                    "analytics_sink.persist_skipped",
                    exchange_id=exchange_id,
                    reason="no_request_body",
                )
                return
            self._log.info(
                "analytics_sink.persist_fallback_recovered", exchange_id=exchange_id
            )
        if self._engine is None:
            return
        if ctx.org_id is None:
            self._log.warning(
                "analytics_sink.skip",
                exchange_id=exchange_id,
                reason="ctx.org_id missing",
            )
            return

        parsed = _parse_request(messages_json)
        classification = classify_request(parsed or {})
        row = self._build_row(exchange_id, ctx, messages_json, parsed, classification)

        try:
            async with self._engine.begin() as conn:
                conv_id, turn_seq = await self._resolve_conversation(
                    conn,
                    row_id=row["id"],
                    org_id=ctx.org_id,
                    classification=classification,
                )
                row["conversation_id"] = conv_id
                row["turn_seq"] = turn_seq
                await conn.execute(_INSERT_SQL, row)
        except Exception as exc:  # pragma: no cover — defensive
            self._log.warning("analytics_sink.insert_failed", error=str(exc))

    async def _resolve_conversation(
        self,
        conn: Any,
        *,
        row_id: str,
        org_id: Any,
        classification: Classification,
    ) -> tuple[str | None, int | None]:
        """Run the chain lookup and decide `(conversation_id, turn_seq)`.

        Returns `(this_row_id, 1)` for a fresh user-input turn start
        when no prior same-hash row exists OR the prior row's
        message history is at least as long as ours (identical
        first-prompt collision after /clear or session restart).

        Inherits the prior row's `conversation_id` otherwise.
        """
        prev = (
            await conn.execute(
                _PREV_BY_HASH_SQL,
                {"first_msg_hash": classification.first_msg_hash, "org_id": org_id},
            )
        ).first()

        prev_n_msgs: int | None = None
        prev_conv_id: str | None = None
        if prev is not None:
            prev_conv_id = prev.conversation_id
            msgs = prev.msgs  # JSON array shape
            prev_n_msgs = len(msgs) if isinstance(msgs, list) else None

        starts_new_conversation = (
            prev_conv_id is None or prev_n_msgs is None or classification.n_messages <= prev_n_msgs
        )

        if starts_new_conversation:
            conv_id: str | None = row_id
        else:
            conv_id = prev_conv_id

        kind = classification.turn_kind
        if kind == "user_input_turn_start":
            turn_seq: int | None = 1
        elif kind == "tool_continuation":
            if conv_id is None:
                turn_seq = None
            else:
                last_seq_row = (
                    await conn.execute(
                        _LAST_SEQ_IN_CONV_SQL,
                        {"conversation_id": conv_id, "org_id": org_id},
                    )
                ).first()
                base = int(last_seq_row.turn_seq) if last_seq_row is not None else 0
                turn_seq = base + 1
        else:
            # internal_subprompt, claude_manage_probe — out of turn axis
            turn_seq = None

        return conv_id, turn_seq
