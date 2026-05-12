"""Storage layer smoke test.

Exercises the Alembic env + four-table schema end-to-end against a real
PostgreSQL instance. Skipped when `LLMTRACK_TEST_DATABASE_URL` is not
set so the wider suite stays green on developer machines without a
local PG and on CI without a Postgres service.

After CP5 the four user-data tables run under RLS (`exchanges`,
`events`, `tool_calls`, `audit_log`). Every INSERT/SELECT into those
tables here sets `app.org_id` first so the per-org policy admits the
write -- the same shape CP6's auth middleware will issue in
production.

To run locally:

    LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://localhost:5432/llm_tracker_test \\
      .venv/bin/python3.12 -m pytest \\
      packages/llm_tracker_server/tests/test_storage_smoke.py -q

The alembic upgrade/downgrade fixture lives in `conftest.py` (hoisted
in CP5).
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import sqlalchemy as sa
from llm_tracker_server.storage import AuditLog, Exchange, Org

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"


async def _bind_org(session, org_id) -> None:
    """Issue the per-request `SET LOCAL app.org_id` that CP6 will issue."""
    await session.execute(
        sa.text("SELECT set_config('app.org_id', :v, true)"),
        {"v": str(org_id)},
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_exchange_round_trip(session_factory) -> None:
    """An `Exchange` row round-trips through SQLAlchemy + asyncpg + PG."""
    row_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)

    async with session_factory() as session:
        org = Org(name="smoke-org")
        session.add(org)
        await session.flush()
        org_id = org.id
        await _bind_org(session, org_id)
        session.add(
            Exchange(
                id=row_id,
                org_id=org_id,
                session_id="smoke-session",
                started_at=now_ms,
                provider="anthropic",
                endpoint="/v1/messages",
                tool_call_count=0,
                content_level="L3",
            )
        )
        await session.commit()

    async with session_factory() as session:
        await _bind_org(session, org_id)
        result = await session.execute(sa.select(Exchange).where(Exchange.id == row_id))
        row = result.scalar_one()
        assert row.session_id == "smoke-session"
        assert row.started_at == now_ms
        assert row.provider == "anthropic"
        assert row.content_level == "L3"
        assert row.org_id == org_id


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_audit_log_append_only(session_factory) -> None:
    """The PG trigger rejects UPDATE and DELETE against `audit_log`."""
    row_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)

    async with session_factory() as session:
        org = Org(name="audit-smoke-org")
        session.add(org)
        await session.flush()
        org_id = org.id
        await _bind_org(session, org_id)
        session.add(
            AuditLog(
                id=row_id,
                org_id=org_id,
                ts=now_ms,
                kind="smoke",
                outcome="ok",
            )
        )
        await session.commit()

    async with session_factory() as session:
        await _bind_org(session, org_id)
        with pytest.raises(Exception, match="append-only"):
            await session.execute(
                sa.update(AuditLog).where(AuditLog.id == row_id).values(outcome="tampered")
            )
            await session.commit()

    async with session_factory() as session:
        await _bind_org(session, org_id)
        with pytest.raises(Exception, match="append-only"):
            await session.execute(sa.delete(AuditLog).where(AuditLog.id == row_id))
            await session.commit()
