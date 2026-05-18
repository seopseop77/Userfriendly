"""DB-fixture for scope_guard integration tests.

Mirrors ``packages/llm_tracker_server/tests/conftest.py`` (CP5 hoist).
Each test gets a freshly-migrated PG (alembic upgrade head → downgrade
base) and a session factory that opens every session as the
``llm_tracker_app`` non-superuser role so RLS actually fires.

We hardcode ``SERVER_ROOT`` two levels up + into the server package
because the alembic env + migrations live there, but every scope_guard
test only touches scope_guard's tables (created by migration 0010 inside
that env). Skipped unless ``LLMTRACK_TEST_DATABASE_URL`` is set; matches
the gate the rest of the DB-fixture suite uses.

Run locally against the ADR-0030 §D8 / migration 0010 image::

    LLMTRACK_TEST_DATABASE_URL=postgresql+asyncpg://localhost:5432/llm_tracker_test \\
        .venv/bin/python3.12 -m pytest \\
        packages/llm_tracker_plugin_scope_guard/tests -q
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

# .../packages/llm_tracker_plugin_scope_guard/tests/conftest.py
# parents[3] = workspace root → /packages/llm_tracker_server is the alembic root.
SERVER_ROOT = Path(__file__).resolve().parents[3] / "packages" / "llm_tracker_server"


def _run_alembic(direction: str) -> None:
    """Run alembic ``upgrade head`` / ``downgrade base`` against the test DB."""
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

    Docker-default ``POSTGRES_USER=cp2`` is a superuser and superusers
    bypass RLS unconditionally — ``FORCE ROW LEVEL SECURITY`` is not
    enough on its own. Dropping to ``llm_tracker_app`` (created by
    migration 0005) is what makes the policies fire.
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
