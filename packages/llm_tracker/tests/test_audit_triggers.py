"""Append-only enforcement tests for the audit_log table (ADR-0006).

Pins that the SQLite triggers `audit_log_no_update` /
`audit_log_no_delete` (installed both via Alembic and via the
`Base.metadata.create_all` event listeners) reject any UPDATE or
DELETE on `audit_log` rows. Insert is unaffected.
"""

import pytest
from llm_tracker.storage.audit import write_audit
from llm_tracker.storage.models import AuditLog, Base
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


async def test_insert_succeeds(session_factory):
    """Sanity: writing an audit row still works after the triggers ship."""
    async with session_factory() as session:
        await write_audit(session, kind="test_event", outcome="ok")

    async with session_factory() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].kind == "test_event"


async def test_update_raises(session_factory):
    """audit_log_no_update fires on any UPDATE; SQLAlchemy surfaces it."""
    async with session_factory() as session:
        await write_audit(session, kind="original", outcome="ok")

    async with session_factory() as session:
        with pytest.raises(IntegrityError, match="append-only"):
            await session.execute(text("UPDATE audit_log SET outcome = 'altered'"))
            await session.commit()


async def test_delete_raises(session_factory):
    """audit_log_no_delete fires on any DELETE; SQLAlchemy surfaces it."""
    async with session_factory() as session:
        await write_audit(session, kind="will_not_be_deleted", outcome="ok")

    async with session_factory() as session:
        with pytest.raises(IntegrityError, match="append-only"):
            await session.execute(text("DELETE FROM audit_log"))
            await session.commit()

    # The row is still there.
    async with session_factory() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    assert len(rows) == 1
