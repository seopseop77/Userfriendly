"""Storage layer smoke test.

Exercises the Alembic env + four-table schema end-to-end against a real
PostgreSQL instance. Skipped when `LLMTRACK_TEST_DATABASE_URL` is not
set so the wider suite stays green on developer machines without a
local PG and on CI without a Postgres service.

To run locally:

    LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://localhost:5432/llm_tracker_test \\
      .venv/bin/python3.12 -m pytest \\
      packages/llm_tracker_server/tests/test_storage_smoke.py -q
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
    AuditLog,
    Exchange,
    make_engine,
    make_session_factory,
)

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"

SERVER_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(direction: str) -> None:
    """Run `alembic upgrade head` / `downgrade base` against the test DB."""
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
async def test_exchange_round_trip(session_factory) -> None:
    """An `Exchange` row round-trips through SQLAlchemy + asyncpg + PG."""
    row_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)

    async with session_factory() as session:
        session.add(
            Exchange(
                id=row_id,
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
        result = await session.execute(sa.select(Exchange).where(Exchange.id == row_id))
        row = result.scalar_one()
        assert row.session_id == "smoke-session"
        assert row.started_at == now_ms
        assert row.provider == "anthropic"
        assert row.content_level == "L3"


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_audit_log_append_only(session_factory) -> None:
    """The PG trigger rejects UPDATE and DELETE against `audit_log`."""
    row_id = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)

    async with session_factory() as session:
        session.add(
            AuditLog(
                id=row_id,
                ts=now_ms,
                kind="smoke",
                outcome="ok",
            )
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(Exception, match="append-only"):
            await session.execute(
                sa.update(AuditLog).where(AuditLog.id == row_id).values(outcome="tampered")
            )
            await session.commit()

    async with session_factory() as session:
        with pytest.raises(Exception, match="append-only"):
            await session.execute(sa.delete(AuditLog).where(AuditLog.id == row_id))
            await session.commit()
