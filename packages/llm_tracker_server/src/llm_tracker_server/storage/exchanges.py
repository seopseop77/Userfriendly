"""Helpers for writing ``exchanges`` rows (ADR-0018 + ADR-0020 wiring).

Two call sites in the forwarder:

* :func:`record_exchange_timing` — happy path. Lands after the upstream
  stream ended naturally; carries the three ``t_*_ms`` epoch
  millisecond marks the local sidecar already captures.
* :func:`record_exchange_blocked` — short-circuit path. Lands when a
  plugin returns ``Block`` from ``on_request_received`` /
  ``before_forward`` or ``Abort`` from ``on_upstream_response_start``;
  carries ``blocked_by = result.plugin`` so audits can attribute the
  decision.

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
) -> None:
    """Persist a completed-exchange row scoped to ``org_id``."""
    session.add(
        Exchange(
            id=exchange_id,
            org_id=org_id,
            session_id="server",
            started_at=t_request_received_ms,
            provider="anthropic",
            endpoint=endpoint,
            content_level="L3",
            tool_call_count=0,
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
) -> None:
    """Persist a row for a request that never completed upstream."""
    session.add(
        Exchange(
            id=exchange_id,
            org_id=org_id,
            session_id="server",
            started_at=started_at_ms,
            provider="anthropic",
            endpoint=endpoint,
            content_level="L3",
            tool_call_count=0,
            t_request_received_ms=started_at_ms,
            blocked_by=blocked_by,
        )
    )
    await session.flush()
