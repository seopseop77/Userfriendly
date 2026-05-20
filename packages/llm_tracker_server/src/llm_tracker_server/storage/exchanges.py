"""Helpers for writing ``exchanges`` rows (ADR-0018 + ADR-0020 + ADR-0027).

Three call sites in the forwarder:

* :func:`record_exchange_timing` — happy path. Lands after the upstream
  stream ended naturally; carries the three ``t_*_ms`` epoch millisecond
  marks, the four forwarder-known close-out fields (``ended_at_ms``,
  ``status_code``, ``model_requested``, ``latency_ms``), plus
  ``model_served`` and ``stop_reason`` from the SSE extractor. Token
  counts were removed from ``exchanges`` in migration 0013 — they live
  in ``plugin_analytics``.
* :func:`record_exchange_blocked` — short-circuit path. Lands when a
  plugin returns ``Block`` from ``on_request_received`` /
  ``before_forward`` or ``Abort`` from ``on_upstream_response_start``;
  carries ``blocked_by = result.plugin``. Per ADR-0027 axis 3, the three
  cheap close-out fields (``ended_at_ms``, ``latency_ms``,
  ``model_requested``) ride through here so blocked rows are queryable on
  the same axes as happy rows.
* :func:`record_exchange_failure` — pre-SSE upstream failure path
  (ADR-0027 axis 2). Lands when ``http_client.send`` raises a
  network-level error or when upstream returns a non-2xx status before
  the SSE stream starts. ``status_code`` is the upstream's status when
  available; ``599`` is the documented sentinel for "upstream gave us
  nothing" (connection error / timeout). ``blocked_by`` stays NULL —
  this is not a plugin decision, this is upstream not delivering.

All helpers take ``session`` + ``org_id`` keyword-only. The session is
the per-request :class:`AsyncSession` opened by
:class:`~llm_tracker_server.auth.AuthMiddleware`; the GUC binding
(``set_config('app.org_id', ...)``) is what makes CP5 RLS match this
row. ``org_id`` is also set on the column explicitly — defense in depth.

The helpers ``flush`` rather than ``commit``: the middleware's terminal
``session.commit()`` remains the single transaction boundary.
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
    stop_reason: str | None = None,
) -> None:
    """Persist a completed-exchange row scoped to ``org_id``.

    ``model_requested`` is ``None`` when the request body was not
    parseable JSON or did not carry a string ``model`` field.

    ``model_served`` and ``stop_reason`` default to ``None``; ADR-0027
    axis 1: NULL means "the extractor did not produce a value", not
    "we forgot to populate this".
    """
    session.add(
        Exchange(
            id=exchange_id,
            org_id=org_id,
            started_at=t_request_received_ms,
            ended_at=ended_at_ms,
            provider="anthropic",
            endpoint=endpoint,
            model_requested=model_requested,
            model_served=model_served,
            status_code=status_code,
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


async def record_exchange_failure(
    session: AsyncSession,
    *,
    exchange_id: str,
    org_id: uuid.UUID,
    endpoint: str,
    started_at_ms: int,
    ended_at_ms: int,
    latency_ms: int,
    model_requested: str | None,
    status_code: int,
) -> None:
    """Persist a row for a request that failed before SSE could start.

    Per ADR-0027 axis 2, covers two upstream-failure shapes:

    1. ``http_client.send`` raised (network error, timeout, etc.).
       The forwarder passes ``status_code=599`` as the sentinel for
       "upstream gave us nothing."
    2. Upstream returned a non-2xx status before SSE could start.
       The forwarder passes ``status_code=upstream.status_code``.

    Response-side columns (``model_served``, ``stop_reason``, and the
    two SSE timing marks) stay NULL because no SSE stream ran.
    ``blocked_by`` also stays NULL — upstream failure, not a plugin
    decision.
    """
    session.add(
        Exchange(
            id=exchange_id,
            org_id=org_id,
            started_at=started_at_ms,
            ended_at=ended_at_ms,
            provider="anthropic",
            endpoint=endpoint,
            model_requested=model_requested,
            status_code=status_code,
            latency_ms=latency_ms,
            content_level="L3",
            t_request_received_ms=started_at_ms,
        )
    )
    await session.flush()
