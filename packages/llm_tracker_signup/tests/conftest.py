"""Shared fixtures for `llm_tracker_signup` tests.

The signup app shares the proxy server's PostgreSQL schema, so the
test DB needs the same alembic-managed shape. We invoke alembic via
subprocess against the `llm_tracker_server` package's `alembic.ini`
(running alembic in a separate process avoids the async-engine /
event-loop conflict the server's own conftest also dodges).

This is **not** an import dependency on the proxy server package —
the subprocess invocation is a filesystem path lookup, not a Python
import.

Tests that need a real DB request the `db_engine` fixture; tests
without that dependency (the pure-template render tests) run
unconditionally. The fixture skips cleanly when
`LLMTRACK_TEST_DATABASE_URL` is unset, matching the proxy server's
conftest convention.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"

# alembic.ini lives in the proxy server package — same schema.
SERVER_ROOT = Path(__file__).resolve().parents[2] / "llm_tracker_server"


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
async def db_engine():
    if not TEST_DB_URL:
        pytest.skip(SKIP_REASON)
    _run_alembic("upgrade")
    engine = create_async_engine(TEST_DB_URL)
    try:
        yield engine
    finally:
        await engine.dispose()
        _run_alembic("downgrade")
