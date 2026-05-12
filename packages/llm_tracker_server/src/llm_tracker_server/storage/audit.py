"""Helper for writing append-only ``audit_log`` rows (ADR-0018 wiring).

Single call site: the session-bound audit writer in
:mod:`llm_tracker_server.audit_context`, which is the writer
:class:`~llm_tracker_server.plugin_host.host.PluginHost` and
:class:`~llm_tracker_server.egress_guard.guard.EgressGuard` dispatch
through. ``org_id`` is required and set on the column explicitly to
match the CP5 RLS shape and the CP4 NOT NULL FK.

Like :mod:`.exchanges`, the helper ``flush``-es rather than
``commit``-s so the per-request session remains the sole transaction
boundary.

The ``audit_log`` table has append-only triggers from migration
``0002_audit_log_triggers`` (no UPDATE / DELETE on it), so a flush
here is permanently part of the row history once the middleware
commits.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from .models import AuditLog


async def write_audit(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kind: str,
    outcome: str = "ok",
    plugin: str | None = None,
    hook: str | None = None,
    capability: str | None = None,
    destination: str | None = None,
    detail_json: str | None = None,
) -> None:
    session.add(
        AuditLog(
            id=str(ULID()),
            org_id=org_id,
            ts=int(time.time() * 1000),
            kind=kind,
            plugin=plugin,
            hook=hook,
            capability=capability,
            destination=destination,
            outcome=outcome,
            detail_json=detail_json,
        )
    )
    await session.flush()
