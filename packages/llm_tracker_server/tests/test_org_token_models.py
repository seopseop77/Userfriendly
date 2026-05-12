"""Tests for the `orgs` and `api_tokens` tables (Phase 3c CP3).

Pins the ADR-0018 / ADR-0020 substrate:

- `orgs.id` is generated server-side by `gen_random_uuid()` (no app-layer
  ULID); `created_at` defaults to `now()` and lands as a tz-aware datetime.
- `api_tokens.token_hash` is the PK — duplicates are rejected.
- `api_tokens.org_id` is a NOT NULL FK to `orgs.id`; unknown FKs are
  rejected; `ON DELETE CASCADE` removes tokens when their org is dropped.

Skipped unless `LLMTRACK_TEST_DATABASE_URL` is set, so the wider suite
stays green on machines without a local PostgreSQL. CP5 hoisted the
alembic upgrade/downgrade fixture into `conftest.py`; this file used
to carry its own copy.

`orgs` and `api_tokens` carry no RLS (ADR-0018 §"Enforcement" --
"every user-data table"); they are the tenancy substrate, not user
data. So unlike the four user-data tables, these tests do not set
`app.org_id`.
"""

from __future__ import annotations

import hashlib
import os
import uuid

import pytest
import sqlalchemy as sa
from llm_tracker_server.storage import ApiToken, Org

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_org_server_side_uuid_default(session_factory) -> None:
    """Insert without supplying `id` → DB fills it via `gen_random_uuid()`."""
    async with session_factory() as session:
        org = Org(name="demo-org")
        session.add(org)
        await session.commit()
        await session.refresh(org)
        assigned_id = org.id

    assert isinstance(assigned_id, uuid.UUID)

    async with session_factory() as session:
        row = (await session.execute(sa.select(Org).where(Org.id == assigned_id))).scalar_one()
        assert row.name == "demo-org"
        assert row.created_at is not None
        assert row.created_at.tzinfo is not None


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_api_token_fk_rejects_unknown_org(session_factory) -> None:
    """An `api_token` referencing a non-existent org fails the FK check."""
    bogus_org_id = uuid.uuid4()
    bogus_hash = hashlib.sha256(b"orphan").hexdigest()

    async with session_factory() as session:
        session.add(ApiToken(token_hash=bogus_hash, org_id=bogus_org_id))
        with pytest.raises(sa.exc.IntegrityError):
            await session.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_api_token_hash_is_unique(session_factory) -> None:
    """`token_hash` is the PK — duplicate insert is rejected."""
    primary_hash = hashlib.sha256(b"plaintext-a").hexdigest()

    async with session_factory() as session:
        org = Org(name="dup-org")
        session.add(org)
        await session.flush()
        org_id = org.id
        session.add(ApiToken(token_hash=primary_hash, org_id=org_id, name="primary"))
        await session.commit()

    async with session_factory() as session:
        session.add(ApiToken(token_hash=primary_hash, org_id=org_id, name="duplicate"))
        with pytest.raises(sa.exc.IntegrityError):
            await session.commit()


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_api_token_cascade_on_org_delete(session_factory) -> None:
    """Dropping an `org` removes its `api_tokens` via ON DELETE CASCADE."""
    hash_a = hashlib.sha256(b"plaintext-a").hexdigest()
    hash_b = hashlib.sha256(b"plaintext-b").hexdigest()

    async with session_factory() as session:
        org = Org(name="cascade-org")
        session.add(org)
        await session.flush()
        org_id = org.id
        session.add(ApiToken(token_hash=hash_a, org_id=org_id, name="primary"))
        session.add(ApiToken(token_hash=hash_b, org_id=org_id, name="backup"))
        await session.commit()

    async with session_factory() as session:
        before = await session.scalar(
            sa.select(sa.func.count()).select_from(ApiToken).where(ApiToken.org_id == org_id)
        )
        assert before == 2
        await session.execute(sa.delete(Org).where(Org.id == org_id))
        await session.commit()

    async with session_factory() as session:
        after = await session.scalar(
            sa.select(sa.func.count()).select_from(ApiToken).where(ApiToken.org_id == org_id)
        )
        assert after == 0
