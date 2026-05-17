"""DB integration tests for `record_exchange_failure` (ADR-0027 axis 2).

The forwarder-level shape (no auth middleware, no DB) is covered by
`test_proxy_forwarder_hooks.py::test_axis2_*`. This file exercises the
row-write half against a real PostgreSQL fixture, pinning the two
shapes ADR-0027 axis 2 specifies:

1. ``status_code=599`` sentinel for the network-error path
   (``httpx.RequestError``).
2. ``status_code=<upstream HTTP status>`` for the upstream-non-2xx
   path.

Both shapes must populate ``ended_at`` + ``latency_ms`` (close-out
fields shared with the blocked-row writer per ADR-0027 axis 3) and
leave ``blocked_by`` NULL (failure is not a plugin decision).

Skipped unless ``LLMTRACK_TEST_DATABASE_URL`` is set. The alembic
upgrade/downgrade fixture lives in `conftest.py`.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import sqlalchemy as sa
from llm_tracker_server.storage import Exchange, Org
from llm_tracker_server.storage.exchanges import record_exchange_failure

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"


async def _bind_org(session, org_id) -> None:
    """Issue the per-request `SET LOCAL app.org_id` AuthMiddleware issues."""
    await session.execute(
        sa.text("SELECT set_config('app.org_id', :v, true)"),
        {"v": str(org_id)},
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_record_exchange_failure_writes_network_error_row(session_factory) -> None:
    """Network-error path: row has `status_code=599`, close-out fields populated."""
    row_id = uuid.uuid4().hex
    started_ms = int(time.time() * 1000)
    ended_ms = started_ms + 42
    latency = ended_ms - started_ms

    async with session_factory() as session:
        org = Org(name="failure-net-org")
        session.add(org)
        await session.flush()
        org_id = org.id
        await _bind_org(session, org_id)
        await record_exchange_failure(
            session,
            exchange_id=row_id,
            org_id=org_id,
            endpoint="/v1/messages",
            started_at_ms=started_ms,
            ended_at_ms=ended_ms,
            latency_ms=latency,
            model_requested="claude-x",
            status_code=599,
        )
        await session.commit()

    async with session_factory() as session:
        await _bind_org(session, org_id)
        result = await session.execute(sa.select(Exchange).where(Exchange.id == row_id))
        row = result.scalar_one()
        assert row.org_id == org_id
        assert row.status_code == 599
        assert row.started_at == started_ms
        assert row.ended_at == ended_ms
        assert row.latency_ms == latency
        assert row.model_requested == "claude-x"
        assert row.blocked_by is None
        assert row.endpoint == "/v1/messages"


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_record_exchange_failure_writes_upstream_4xx_row(session_factory) -> None:
    """Upstream-non-2xx path: row carries the upstream HTTP status verbatim."""
    row_id = uuid.uuid4().hex
    started_ms = int(time.time() * 1000)
    ended_ms = started_ms + 17
    latency = ended_ms - started_ms

    async with session_factory() as session:
        org = Org(name="failure-401-org")
        session.add(org)
        await session.flush()
        org_id = org.id
        await _bind_org(session, org_id)
        await record_exchange_failure(
            session,
            exchange_id=row_id,
            org_id=org_id,
            endpoint="/v1/messages",
            started_at_ms=started_ms,
            ended_at_ms=ended_ms,
            latency_ms=latency,
            model_requested=None,
            status_code=401,
        )
        await session.commit()

    async with session_factory() as session:
        await _bind_org(session, org_id)
        result = await session.execute(sa.select(Exchange).where(Exchange.id == row_id))
        row = result.scalar_one()
        assert row.org_id == org_id
        assert row.status_code == 401
        assert row.ended_at == ended_ms
        assert row.latency_ms == latency
        assert row.model_requested is None
        assert row.blocked_by is None
