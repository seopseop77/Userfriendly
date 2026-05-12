"""RLS two-org isolation test (ADR-0018 §"Enforcement").

CP5's verification surface. The CP4 column constraints (NOT NULL + FK)
prevent a *missing* tenant claim from reaching disk; the RLS policies
added in CP5's migration prevent one tenant from *reading* or
*writing into* another's rows. This file pins that second guarantee.

Four assertions, end to end against a real PostgreSQL:

1. A session bound to org A (`SET LOCAL app.org_id = '<A uuid>'`) can
   insert two `Exchange` rows naming org A.
2. A session bound to org B sees zero of those rows.
3. A session bound back to org A sees both rows.
4. A session with `app.role = 'admin'` sees both rows (the explicit
   admin policy branch the ADR mandates -- no service-role bypass).
5. A session with neither setting sees zero rows -- the default-closed
   shape that falls out of `current_setting('app.org_id', true)`
   returning NULL when unset.

And one negative path:

6. A session bound to org A cannot insert a row claiming `org_id = B`
   -- RLS WITH CHECK rejects the cross-org write.

Skipped unless `LLMTRACK_TEST_DATABASE_URL` is set. Fixture lives in
`conftest.py` (hoisted in CP5).
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import sqlalchemy as sa
from llm_tracker_server.storage import Exchange, Org

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"


async def _bind_org(session, org_id) -> None:
    """Issue the per-request `SET LOCAL app.org_id` that CP6 will issue."""
    await session.execute(
        sa.text("SELECT set_config('app.org_id', :v, true)"),
        {"v": str(org_id)},
    )


def _make_exchange(row_id: str, org_id, *, session_id: str, now_ms: int) -> Exchange:
    return Exchange(
        id=row_id,
        org_id=org_id,
        session_id=session_id,
        started_at=now_ms,
        provider="anthropic",
        endpoint="/v1/messages",
        tool_call_count=0,
        content_level="L3",
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_two_org_isolation(session_factory) -> None:
    """Org A's rows are invisible to org B and visible to admin / org A."""
    # `orgs` has no RLS -- the substrate is allowed to bootstrap without
    # a per-org context. This is the same shape CP6's CLI `tokens issue`
    # subcommand will use to create orgs.
    async with session_factory() as session:
        org_a = Org(name="iso-org-a")
        org_b = Org(name="iso-org-b")
        session.add_all([org_a, org_b])
        await session.flush()
        org_a_id = org_a.id
        org_b_id = org_b.id
        await session.commit()

    now_ms = int(time.time() * 1000)
    a_row_ids = [uuid.uuid4().hex, uuid.uuid4().hex]

    # As org A: insert two exchanges.
    async with session_factory() as session:
        await _bind_org(session, org_a_id)
        for row_id in a_row_ids:
            session.add(_make_exchange(row_id, org_a_id, session_id="iso-a", now_ms=now_ms))
        await session.commit()

    # As org B: SELECT must return zero rows from `exchanges`, even
    # though we know two rows physically exist on disk.
    async with session_factory() as session:
        await _bind_org(session, org_b_id)
        count = await session.scalar(sa.select(sa.func.count()).select_from(Exchange))
        assert count == 0
        rows = (
            (await session.execute(sa.select(Exchange).where(Exchange.id.in_(a_row_ids))))
            .scalars()
            .all()
        )
        assert rows == []

    # As org A again: both rows visible.
    async with session_factory() as session:
        await _bind_org(session, org_a_id)
        count = await session.scalar(sa.select(sa.func.count()).select_from(Exchange))
        assert count == 2

    # As admin: cross-org visibility (ADR-0018 §"Enforcement" policy branch).
    async with session_factory() as session:
        await session.execute(sa.text("SELECT set_config('app.role', 'admin', true)"))
        count = await session.scalar(sa.select(sa.func.count()).select_from(Exchange))
        assert count == 2

    # No setting at all: default-closed.
    async with session_factory() as session:
        count = await session.scalar(sa.select(sa.func.count()).select_from(Exchange))
        assert count == 0


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_cross_org_write_rejected(session_factory) -> None:
    """Org A's session cannot insert a row claiming `org_id = B` (WITH CHECK)."""
    async with session_factory() as session:
        org_a = Org(name="write-org-a")
        org_b = Org(name="write-org-b")
        session.add_all([org_a, org_b])
        await session.flush()
        org_a_id = org_a.id
        org_b_id = org_b.id
        await session.commit()

    async with session_factory() as session:
        await _bind_org(session, org_a_id)
        session.add(
            _make_exchange(
                uuid.uuid4().hex,
                org_b_id,  # claim org B while bound to org A
                session_id="cross-write",
                now_ms=int(time.time() * 1000),
            )
        )
        with pytest.raises(sa.exc.ProgrammingError, match="row-level security"):
            await session.commit()
