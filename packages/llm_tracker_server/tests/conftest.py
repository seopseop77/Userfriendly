"""Shared fixtures for `llm_tracker_server` tests.

Every PostgreSQL smoke test in this package (CP2, CP3, CP4, CP5) needs
the same shape: an async SQLAlchemy session factory bound to a real
PG, bracketed by an alembic upgrade/downgrade so each test runs
against a freshly-migrated database.

CP4 added the third copy of `_run_alembic` + the `session_factory`
fixture; CP5 adds the fourth (the RLS isolation test). The Phase 3c
plan worklog flagged the hoist as the right move once that fourth
copy was about to land (§Suggestion 6). This file is that hoist.

The fixture wraps SQLAlchemy's raw session factory so every session
opens with `SET LOCAL ROLE llm_tracker_app`. The docker-default
`POSTGRES_USER=cp2` is a Postgres superuser, and **superusers bypass
RLS unconditionally** -- `FORCE ROW LEVEL SECURITY` is not enough on
its own. Dropping to the non-superuser app role (created by migration
`0005_rls_policies`) is what makes the policies actually fire. The
SET LOCAL scoping ties the role to the current transaction, so each
session block reverts to superuser on commit -- which is what the
fixture's downgrade/teardown needs.

Per-org seeding stays in `test_rls_two_org_isolation.py` -- it is the
only test that needs the two-org shape, and pushing it into a shared
fixture would over-fit the fixture to a single test's needs.

The fixture is `function`-scoped (pytest default): each test gets its
own upgrade/downgrade cycle, which trades runtime for isolation.
"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from llm_tracker_server.storage import make_engine, make_session_factory

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"

SERVER_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(direction: str) -> None:
    """Run `alembic upgrade head` / `downgrade base` against the test DB.

    Invoked as a subprocess so alembic's own event loop does not fight
    the async engine the test is about to open against the same URL.
    """
    env = os.environ.copy()
    env["LLMTRACK_DATABASE_URL"] = TEST_DB_URL
    target = "head" if direction == "upgrade" else "base"
    subprocess.run(
        [sys.executable, "-m", "alembic", direction, target],
        cwd=SERVER_ROOT,
        env=env,
        check=True,
    )


def _wrap_with_app_role(raw_factory):
    """Wrap an async sessionmaker so every session begins as the app role.

    Returns a zero-arg callable that mirrors the sessionmaker's
    `__call__` shape (returns an async context manager yielding a
    session). Each entry issues `SET LOCAL ROLE llm_tracker_app` so
    the docker-default superuser session does not bypass RLS.
    """

    @asynccontextmanager
    async def _session_cm():
        async with raw_factory() as session:
            await session.execute(sa.text("SET LOCAL ROLE llm_tracker_app"))
            yield session

    return _session_cm


@pytest.fixture
async def session_factory():
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    _run_alembic("upgrade")
    engine = make_engine(TEST_DB_URL)
    raw_factory = make_session_factory(engine)
    try:
        yield _wrap_with_app_role(raw_factory)
    finally:
        await engine.dispose()
        _run_alembic("downgrade")
