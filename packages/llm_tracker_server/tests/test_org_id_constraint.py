"""Tests for the CP4 `org_id NOT NULL FK` column on user-data tables.

Pins the ADR-0018 tenancy boundary at the column-constraint half of
defense-in-depth (RLS policies are the second half and land in CP5):

- Inserting an `Exchange` without `org_id` -> NOT NULL violation.
- Inserting an `Exchange` with an `org_id` that does not exist in `orgs`
  -> FK violation.

After CP5 these inserts also hit RLS WITH CHECK. To keep the test
focused on column-level enforcement (the CP4 concern), each insert
runs under the `admin` policy branch -- `app.role = 'admin'` makes the
WITH CHECK admit any `org_id`, leaving NOT NULL and FK as the only
remaining gates. Admin's "policy branch, not service-role bypass"
shape is precisely what ADR-0018 §"Enforcement" mandates; the test
shape mirrors how operator tooling will look in CP6+.

Skipped unless `LLMTRACK_TEST_DATABASE_URL` is set. The alembic
upgrade/downgrade fixture lives in `conftest.py` (hoisted in CP5).
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import sqlalchemy as sa
from llm_tracker_server.storage import Exchange

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"


async def _assume_admin(session) -> None:
    """Bypass RLS via the explicit admin policy branch (ADR-0018 §Enforcement)."""
    await session.execute(sa.text("SELECT set_config('app.role', 'admin', true)"))


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_exchange_without_org_id_rejected(session_factory) -> None:
    """Inserting an `Exchange` without `org_id` -> NOT NULL violation."""
    row_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)

    async with session_factory() as session:
        await _assume_admin(session)
        session.add(
            Exchange(
                id=row_id,
                started_at=now_ms,
                provider="anthropic",
                endpoint="/v1/messages",
                content_level="L3",
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            await session.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_exchange_with_unknown_org_id_rejected(session_factory) -> None:
    """Inserting an `Exchange` referencing a non-existent org -> FK violation."""
    row_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    bogus_org_id = uuid.uuid4()

    async with session_factory() as session:
        await _assume_admin(session)
        session.add(
            Exchange(
                id=row_id,
                org_id=bogus_org_id,
                started_at=now_ms,
                provider="anthropic",
                endpoint="/v1/messages",
                content_level="L3",
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            await session.commit()
