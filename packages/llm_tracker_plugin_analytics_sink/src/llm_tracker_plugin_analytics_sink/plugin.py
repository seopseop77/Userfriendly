"""`AnalyticsSink` — writes one row per exchange to `plugin_analytics`.

ADR-0038. Each exchange becomes a single row whose user-side delta
sits in `request_jsonb`, model response in `response_jsonb`, and
`system_prompt_jsonb` is populated only when the request's system
field differs from the most recent non-null system in this
conversation (or this is the conversation's first exchange).

The per-message dedup table (`conversation_messages`) and its helper
view (`plugin_analytics_with_messages`) introduced by ADR-0036 are
retired by ADR-0038. The `turn_kind` column on `plugin_analytics`
gives way to a per-row `role` derived from `classify_message`.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import sqlalchemy as sa
import structlog
from llm_tracker_sdk import BasePlugin, HookContext, Pass
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from ulid import ULID

from .classifier import (
    Classification,
    classify_message,
    classify_request,
    extract_request_content,
    normalize_system,
)

DATABASE_URL_ENV = "LLMTRACK_DATABASE_URL"

_INSERT_SQL = sa.text(
    """
    INSERT INTO plugin_analytics (
        id, exchange_id, org_id, session_id, model_requested, model_served,
        response_jsonb,
        input_tokens, output_tokens, cache_read_tokens,
        cache_write_tokens, stop_reason,
        role, turn_seq, slash_commands,
        first_msg_hash, conversation_id,
        request_jsonb, system_prompt_jsonb
    ) VALUES (
        :id, :exchange_id, :org_id, :session_id, :model_requested, :model_served,
        CAST(:response_jsonb AS jsonb),
        :input_tokens, :output_tokens, :cache_read_tokens,
        :cache_write_tokens, :stop_reason,
        :role, :turn_seq, CAST(:slash_commands AS jsonb),
        :first_msg_hash, :conversation_id,
        CAST(:request_jsonb AS jsonb), CAST(:system_prompt_jsonb AS jsonb)
    )
    """
)

# Chain-lookup: most recent row with this `first_msg_hash` in this
# org. Used to inherit the prior conversation_id when one exists.
# ADR-0036 (B) rule, unchanged by ADR-0038.
_PREV_BY_HASH_SQL = sa.text(
    """
    SELECT conversation_id
    FROM plugin_analytics
    WHERE first_msg_hash = :first_msg_hash
      AND org_id = :org_id
    ORDER BY created_at DESC
    LIMIT 1
    """
)

# Max turn_seq already assigned in this conversation. ADR-0038
# `turn_seq` axis is `role IN ('user_input', 'tool_result')`; other
# roles (title_gen, sidecar) stay NULL. The MAX query is identical
# to ADR-0036 — only the axis definition changed.
_LAST_SEQ_IN_CONV_SQL = sa.text(
    """
    SELECT MAX(turn_seq) AS turn_seq
    FROM plugin_analytics
    WHERE conversation_id = :conversation_id
      AND org_id = :org_id
    """
)

# Most recent non-null system_prompt_jsonb in this conversation.
# Used by the system-variation hash compare on every write.
_LAST_SYSTEM_IN_CONV_SQL = sa.text(
    """
    SELECT system_prompt_jsonb
    FROM plugin_analytics
    WHERE conversation_id = :conversation_id
      AND org_id = :org_id
      AND system_prompt_jsonb IS NOT NULL
    ORDER BY created_at DESC
    LIMIT 1
    """
)

_TURN_AXIS_ROLES: frozenset[str] = frozenset({"user_input", "tool_result"})


def _parse_request(body: str | None) -> dict[str, Any] | None:
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


def _session_id_from_request(parsed: dict[str, Any] | None) -> str | None:
    """Client session id from the request's `metadata.user_id`.

    Claude Code packs a JSON object into the Anthropic Messages API
    `metadata.user_id` string: `{"device_id", "account_uuid",
    "session_id"}`. The `session_id` is stable across all requests of
    one CLI session — parent and every sub-agent it spawns share it,
    so it is the signal that links a sub-agent exchange back to its
    originating session (captured here; grouping unchanged).

    Returns None when metadata is absent or `user_id` is not in that
    shape (e.g. another client sends an opaque string).
    """
    if parsed is None:
        return None
    metadata = parsed.get("metadata")
    if not isinstance(metadata, dict):
        return None
    user_id = metadata.get("user_id")
    if not isinstance(user_id, str):
        return None
    try:
        decoded = json.loads(user_id)
    except (ValueError, TypeError):
        return None
    if not isinstance(decoded, dict):
        return None
    session_id = decoded.get("session_id")
    return session_id if isinstance(session_id, str) else None


def _system_hash(system_field: Any) -> str | None:
    """SHA-256[:16] of the system field's flattened text.

    Drops two classes of noise before hashing so the variation
    tracker only fires on meaningful change:
      * `cache_control` keys on system text blocks (prompt-caching
        artefacts) — handled implicitly by reading only `text`.
      * `x-anthropic-billing-header:` blocks (Claude Code telemetry
        — `cc_version` / `cch` token drift) — handled by passing
        through `normalize_system`.

    Returns None when system is absent.
    """
    if system_field is None:
        return None
    normalized = normalize_system(system_field)
    if isinstance(normalized, str):
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    if isinstance(normalized, list):
        parts: list[str] = []
        for b in normalized:
            if isinstance(b, dict):
                t = b.get("text")
                if isinstance(t, str):
                    parts.append(t)
        canonical = "\n".join(parts)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return None


class AnalyticsSink(BasePlugin):
    """Stash request on `on_request_received`; write row on `on_persisted`."""

    name = "analytics_sink"

    def __init__(self, engine: AsyncEngine | None = None) -> None:
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
            self._log.warning("analytics_sink.stash_skipped", exchange_id=exchange_id)
            return Pass()
        self._stash[exchange_id] = body
        return Pass()

    def _build_row(
        self,
        exchange_id: str,
        ctx: HookContext,
        parsed: dict[str, Any] | None,
        classification: Classification,
    ) -> dict[str, Any]:
        usage = ctx.response_usage()
        slash = classification.slash_commands
        return {
            "id": str(ULID()),
            "exchange_id": exchange_id,
            "org_id": ctx.org_id,
            "session_id": _session_id_from_request(parsed),
            "model_requested": _model_from_request(parsed),
            "model_served": getattr(usage, "model_served", None),
            "response_jsonb": ctx.response_content_json(),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_tokens": getattr(usage, "cache_read_tokens", None),
            "cache_write_tokens": getattr(usage, "cache_write_tokens", None),
            "stop_reason": getattr(usage, "stop_reason", None),
            "role": None,  # filled below
            "turn_seq": None,  # filled by caller after conversation resolution
            "slash_commands": json.dumps(slash) if slash is not None else None,
            "first_msg_hash": classification.first_msg_hash,
            "conversation_id": None,  # filled by caller
            "request_jsonb": None,  # filled below
            "system_prompt_jsonb": None,  # filled below (variation tracker)
        }

    async def on_persisted(self, exchange_id: str, ctx: HookContext) -> None:
        messages_json = self._stash.pop(exchange_id, None)
        if messages_json is None:
            messages_json = ctx.request_text()
            if messages_json is None:
                self._log.warning(
                    "analytics_sink.persist_skipped",
                    exchange_id=exchange_id,
                    reason="no_request_body",
                )
                return
            self._log.info("analytics_sink.persist_fallback_recovered", exchange_id=exchange_id)
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
        row = self._build_row(exchange_id, ctx, parsed, classification)

        parsed_messages = (parsed or {}).get("messages") or []
        last_msg = (
            parsed_messages[-1]
            if parsed_messages and isinstance(parsed_messages[-1], dict)
            else None
        )

        # ADR-0038: role from messages[-1]; request_jsonb is the
        # wrapper-stripped content of that same message.
        if last_msg is not None:
            row["role"] = classify_message(last_msg)
            content = extract_request_content(last_msg)
            row["request_jsonb"] = (
                json.dumps(content, ensure_ascii=False) if content is not None else None
            )
        else:
            # Malformed request — no messages array. Still write the
            # row for observability, with NULLs in the new columns.
            row["role"] = "sidecar"

        system_field = (parsed or {}).get("system")

        try:
            async with self._engine.begin() as conn:
                conv_id, turn_seq = await self._resolve_conversation(
                    conn,
                    row_id=row["id"],
                    org_id=ctx.org_id,
                    classification=classification,
                    role=row["role"],
                )
                row["conversation_id"] = conv_id
                row["turn_seq"] = turn_seq

                # System variation tracker: store iff first exchange in
                # conv or current system hash differs from most recent
                # stored.
                row["system_prompt_jsonb"] = await self._resolve_system(
                    conn,
                    conversation_id=conv_id,
                    org_id=ctx.org_id,
                    system_field=system_field,
                )

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
        role: str | None,
    ) -> tuple[str | None, int | None]:
        """Run the chain lookup and decide `(conversation_id, turn_seq)`.

        ADR-0036 (B) rule for conversation grouping. `turn_seq` axis
        per ADR-0038: `role IN ('user_input', 'tool_result')` only.
        Other roles (title_gen, sidecar) stay off the axis.
        """
        # ADR-0040: a None hash means no user message carried real text
        # (e.g. a request whose only user content is wrapper-only). Skip
        # the chain-lookup so the row opens its own conversation_id
        # instead of collapsing onto the shared empty-text hash.
        prev = None
        if classification.first_msg_hash is not None:
            prev = (
                await conn.execute(
                    _PREV_BY_HASH_SQL,
                    {"first_msg_hash": classification.first_msg_hash, "org_id": org_id},
                )
            ).first()

        prev_conv_id = prev.conversation_id if prev is not None else None
        conv_id: str | None = prev_conv_id if prev_conv_id is not None else row_id

        if role in _TURN_AXIS_ROLES:
            last_seq_row = (
                await conn.execute(
                    _LAST_SEQ_IN_CONV_SQL,
                    {"conversation_id": conv_id, "org_id": org_id},
                )
            ).first()
            base = (
                int(last_seq_row.turn_seq)
                if last_seq_row is not None and last_seq_row.turn_seq is not None
                else 0
            )
            turn_seq: int | None = base + 1
        else:
            turn_seq = None

        return conv_id, turn_seq

    async def _resolve_system(
        self,
        conn: Any,
        *,
        conversation_id: str | None,
        org_id: Any,
        system_field: Any,
    ) -> str | None:
        """Return the JSON-encoded `system_prompt_jsonb` value, or None.

        Stores the (normalized) current system iff it is the first
        exchange in the conversation (no prior non-null system) or
        its hash differs from the most recent non-null stored
        system. Otherwise returns None so the row stores NULL.

        Both the hash compare and the stored payload go through
        `normalize_system`, so the invariant "same hash ⇒ identical
        stored bytes" holds across exchanges with drifting
        `x-anthropic-billing-header` blocks.
        """
        if system_field is None or conversation_id is None:
            if system_field is None:
                return None
            normalized = normalize_system(system_field)
            return json.dumps(normalized, ensure_ascii=False)

        prev = (
            await conn.execute(
                _LAST_SYSTEM_IN_CONV_SQL,
                {"conversation_id": conversation_id, "org_id": org_id},
            )
        ).first()

        normalized = normalize_system(system_field)
        current_hash = _system_hash(system_field)
        if prev is None or prev.system_prompt_jsonb is None:
            return json.dumps(normalized, ensure_ascii=False)

        prev_hash = _system_hash(prev.system_prompt_jsonb)
        if current_hash == prev_hash:
            return None
        return json.dumps(normalized, ensure_ascii=False)
