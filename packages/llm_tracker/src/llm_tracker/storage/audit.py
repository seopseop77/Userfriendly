"""Helper for writing append-only audit log entries."""

import time

from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from .models import AuditLog


async def write_audit(
    session: AsyncSession,
    *,
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
    await session.commit()
