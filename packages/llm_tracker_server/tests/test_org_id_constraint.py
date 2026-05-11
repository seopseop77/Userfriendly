"""Tests for the CP4 `org_id NOT NULL FK` column on user-data tables.

Pins the ADR-0018 tenancy boundary at the column-constraint half of
defense-in-depth (RLS policies are the second half and land in CP5):

- Inserting an `Exchange` without `org_id` -> NOT NULL violation.
- Inserting an `Exchange` with an `org_id` that does not exist in `orgs`
  -> FK violation.

Skipped unless `LLMTRACK_TEST_DATABASE_URL` is set, mirroring the CP2/CP3
fixture shape. The alembic upgrade/downgrade subprocess wrapper is
copy-pasted again rather than hoisted into a shared `conftest.py` -- with
this third copy the duplication is now at the point where a `conftest.py`
hoist is the right next move (filed in CP3's Suggestion #6).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from llm_tracker_server.storage import (
    Exchange,
    make_engine,
    make_session_factory,
)

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"

SERVER_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(direction: str) -> None:
    env = os.environ.copy()
    env["LLMTRACK_DATABASE_URL"] = TEST_DB_URL
    target = "head" if direction == "upgrade" else "base"
    subprocess.run(
        [sys.executable, "-m", "alembic", direction, target],
        cwd=SERVER_ROOT,
        env=env,
        check=True,
    )


@pytest.fixture
async def session_factory():
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    _run_alembic("upgrade")
    engine = make_engine(TEST_DB_URL)
    factory = make_session_factory(engine)
    try:
        yield factory
    finally:
        await engine.dispose()
        _run_alembic("downgrade")


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_exchange_without_org_id_rejected(session_factory) -> None:
    """Inserting an `Exchange` without `org_id` -> NOT NULL violation."""
    row_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)

    async with session_factory() as session:
        session.add(
            Exchange(
                id=row_id,
                session_id="orgless",
                started_at=now_ms,
                provider="anthropic",
                endpoint="/v1/messages",
                tool_call_count=0,
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
        session.add(
            Exchange(
                id=row_id,
                org_id=bogus_org_id,
                session_id="ghost-org",
                started_at=now_ms,
                provider="anthropic",
                endpoint="/v1/messages",
                tool_call_count=0,
                content_level="L3",
            )
        )
        with pytest.raises(sa.exc.IntegrityError):
            await session.commit()
