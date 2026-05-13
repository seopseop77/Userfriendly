"""CP6 — auth middleware (ADR-0020 Axis 1).

Three assertions, end to end through ASGITransport against a real
PostgreSQL:

1. No `X-LLM-Tracker-Token` header on a non-public path → 401.
2. An `X-LLM-Tracker-Token` whose SHA-256 hex hash does not exist in
   `api_tokens` (or is revoked) → 403. The middleware deliberately
   conflates "unknown" and "revoked" so the response cannot be used to
   probe revocation state.
3. A valid token → 200 with `request.state.org_id` set and
   `current_setting('app.org_id', true)` matching that org id when the
   downstream handler reads it from `request.state.session`. This is
   the CP9 contract: storage INSERTs will run against the same session
   that carries the GUC, and RLS will see the matching org axis.

Skipped unless `LLMTRACK_TEST_DATABASE_URL` is set, so the wider suite
stays green on machines without a local PostgreSQL. Fixture lives in
`conftest.py` (CP5 hoist).
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
import sqlalchemy as sa
from llm_tracker_server.app import create_app
from llm_tracker_server.auth.tokens import generate_plaintext, hash_token
from llm_tracker_server.storage import ApiToken, Org

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_missing_authorization_returns_401(session_factory) -> None:
    """No X-LLM-Tracker-Token header → 401 before any DB lookup."""
    app = create_app(session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/whoami")

    assert response.status_code == 401
    assert "X-LLM-Tracker-Token" in response.json()["detail"]


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_unknown_token_returns_403(session_factory) -> None:
    """Token whose hash is not in `api_tokens` → 403."""
    app = create_app(session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/whoami",
            headers={"X-LLM-Tracker-Token": generate_plaintext()},
        )

    assert response.status_code == 403
    assert "unknown or revoked" in response.json()["detail"]


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_valid_token_binds_org_axis(session_factory) -> None:
    """Valid token → 200; handler sees matching `request.state.org_id`
    and `current_setting('app.org_id', true)`."""
    plaintext = generate_plaintext()
    token_hash = hash_token(plaintext)

    async with session_factory() as session:
        org = Org(name="auth-mw-org")
        session.add(org)
        await session.flush()
        org_id = org.id
        session.add(ApiToken(token_hash=token_hash, org_id=org_id, name="cp6-test"))
        await session.commit()

    app = create_app(session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/whoami",
            headers={"X-LLM-Tracker-Token": plaintext},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["org_id"] == str(org_id)
    # `current_setting` returns the GUC as a string; the middleware sets
    # it from `str(uuid.UUID)`, so compare against the canonical form.
    assert body["app_org_id_setting"] == str(uuid.UUID(str(org_id)))


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_healthz_is_public(session_factory) -> None:
    """`/healthz` must stay reachable without a token even when auth is wired."""
    app = create_app(session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_revoked_token_returns_403(session_factory) -> None:
    """A previously valid but now revoked token → 403 (same shape as unknown)."""
    plaintext = generate_plaintext()
    token_hash = hash_token(plaintext)

    async with session_factory() as session:
        org = Org(name="auth-mw-revoked-org")
        session.add(org)
        await session.flush()
        org_id = org.id
        session.add(
            ApiToken(
                token_hash=token_hash,
                org_id=org_id,
                name="cp6-revoked",
                revoked_at=sa.func.now(),
            )
        )
        await session.commit()

    app = create_app(session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/whoami",
            headers={"X-LLM-Tracker-Token": plaintext},
        )

    assert response.status_code == 403
    assert "unknown or revoked" in response.json()["detail"]
