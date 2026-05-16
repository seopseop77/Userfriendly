"""Helpers for writing ``exchanges`` rows (ADR-0018 + ADR-0020 + ADR-0027).

Two call sites in the forwarder:

* :func:`record_exchange_timing` — happy path. Lands after the upstream
  stream ended naturally; carries the three ``t_*_ms`` epoch
  millisecond marks the local sidecar already captures, the four
  forwarder-known close-out fields (CP14 follow-up Option A:
  ``ended_at_ms``, ``status_code``, ``model_requested``,
  ``latency_ms``), plus the six SSE-extractor response-side fields
  added by Option B / ADR-0026 (``model_served``, ``input_tokens``,
  ``output_tokens``, ``cache_read_tokens``, ``cache_write_tokens``,
  ``stop_reason``). All six default to ``None`` per ADR-0027 axis 1
  (best-effort NULL): the extractor never raises, so a request whose
  stream produced a malformed or truncated `message_start` simply
  carries fewer populated columns.
* :func:`record_exchange_blocked` — short-circuit path. Lands when a
  plugin returns ``Block`` from ``on_request_received`` /
  ``before_forward`` or ``Abort`` from ``on_upstream_response_start``;
  carries ``blocked_by = result.plugin`` so audits can attribute the
  decision. Per ADR-0027 axis 3, the three cheap close-out fields
  (``ended_at_ms``, ``latency_ms``, ``model_requested``) ride
  through this helper too so blocked rows are queryable on the same
  axes as happy rows.

Both helpers take ``session`` + ``org_id`` keyword-only. The session is
the per-request :class:`AsyncSession` opened by
:class:`~llm_tracker_server.auth.AuthMiddleware`; the GUC binding
(``set_config('app.org_id', ...)``) on that session is what makes the
CP5 RLS policy ``exchanges_org_isolation`` match this row. ``org_id``
is set on the column explicitly even though RLS ``WITH CHECK`` would
reject a wrong-org write — defense in depth (ADR-0018 §"Enforcement").

The helpers ``flush`` rather than ``commit``: the request-scoped
session retains commit control so the middleware's terminal
``session.commit()`` (after the downstream handler returns) remains
the single transaction boundary.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from .models import Exchange


async def record_exchange_timing(
    session: AsyncSession,
    *,
    exchange_id: str,
    org_id: uuid.UUID,
    endpoint: str,
    t_request_received_ms: int,
    t_upstream_first_byte_ms: int,
    t_client_first_byte_ms: int,
    ended_at_ms: int,
    status_code: int,
    model_requested: str | None,
    latency_ms: int,
    model_served: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cache_read_tokens: int | None = None,
    cache_write_tokens: int | None = None,
    stop_reason: str | None = None,
) -> None:
    """Persist a completed-exchange row scoped to ``org_id``.

    ``model_requested`` is ``None`` when the request body was not
    parseable JSON or did not carry a string ``model`` field.

    The six SSE-extractor fields (``model_served`` through
    ``stop_reason``) default to ``None``; ADR-0027 axis 1 codifies that
    `NULL` on any of them means "the extractor did not produce a value
    for this request" — not "we forgot to populate this on this path."
    """
    session.add(
        Exchange(
            id=exchange_id,
            org_id=org_id,
            session_id="server",
            started_at=t_request_received_ms,
            ended_at=ended_at_ms,
            provider="anthropic",
            endpoint=endpoint,
            model_requested=model_requested,
            model_served=model_served,
            status_code=status_code,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            latency_ms=latency_ms,
            stop_reason=stop_reason,
            content_level="L3",
            t_request_received_ms=t_request_received_ms,
            t_upstream_first_byte_ms=t_upstream_first_byte_ms,
            t_client_first_byte_ms=t_client_first_byte_ms,
        )
    )
    await session.flush()


async def record_exchange_blocked(
    session: AsyncSession,
    *,
    exchange_id: str,
    org_id: uuid.UUID,
    endpoint: str,
    blocked_by: str,
    started_at_ms: int,
    ended_at_ms: int | None = None,
    latency_ms: int | None = None,
    model_requested: str | None = None,
) -> None:
    """Persist a row for a request that never completed upstream.

    Per ADR-0027 axis 3, ``ended_at_ms`` / ``latency_ms`` /
    ``model_requested`` are forwarded here so blocked rows match
    happy-path rows on the queryable close-out axes. All three default
    to ``None`` so direct unit-test callers that omit them keep
    working; the forwarder always supplies them.
    """
    session.add(
        Exchange(
            id=exchange_id,
            org_id=org_id,
            session_id="server",
            started_at=started_at_ms,
            ended_at=ended_at_ms,
            provider="anthropic",
            endpoint=endpoint,
            model_requested=model_requested,
            latency_ms=latency_ms,
            content_level="L3",
            t_request_received_ms=started_at_ms,
            blocked_by=blocked_by,
        )
    )
    await session.flush()
