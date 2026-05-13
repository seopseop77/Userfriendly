"""CP9 — two-org end-to-end isolation test (ADR-0018 §"Enforcement").

CP5's `test_rls_two_org_isolation.py` pins the storage-only half of
defense in depth: hand-bound `set_config('app.org_id', ...)` sessions
seeing only their own rows. CP9 pins the request-level half: a request
through the real catch-all proxy route writes an `exchanges` row tagged
with the caller's org, and a session scoped to a different org cannot
see that row.

Assertions:

1. POST `/v1/messages` as org A → 200, one `exchanges` row visible to a
   session bound to org A.
2. Same row is invisible to a session bound to org B.
3. The row's `org_id` column matches org A explicitly (defense in
   depth: CP4 NOT NULL + CP5 RLS WITH CHECK both pass).

The upstream Anthropic call is mocked via `httpx.MockTransport` +
`monkeypatch` on `forwarder.UPSTREAM_BASE`, so the test does not reach
the real API. The FastAPI lifespan is bypassed — `app.state` is seeded
manually with a `PluginHost` (no plugins loaded, just the audit
writer) + the mock upstream client.

Skipped unless `LLMTRACK_TEST_DATABASE_URL` is set.
"""

from __future__ import annotations

import os

import httpx
import pytest
import sqlalchemy as sa
from llm_tracker_server.app import create_app
from llm_tracker_server.audit_context import session_bound_audit_writer
from llm_tracker_server.auth.tokens import generate_plaintext, hash_token
from llm_tracker_server.plugin_host.host import PluginHost
from llm_tracker_server.proxy import forwarder
from llm_tracker_server.storage import ApiToken, Exchange, Org

TEST_DB_URL = os.environ.get("LLMTRACK_TEST_DATABASE_URL", "")
SKIP_REASON = "LLMTRACK_TEST_DATABASE_URL not set; PG smoke test skipped"


def _fake_anthropic(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=(
            b"event: message_start\n"
            b'data: {"type":"message_start"}\n\n'
            b"event: message_stop\n"
            b'data: {"type":"message_stop"}\n\n'
        ),
    )


@pytest.mark.skipif(not TEST_DB_URL, reason=SKIP_REASON)
async def test_two_org_e2e_isolation(session_factory, monkeypatch) -> None:
    # Redirect upstream resolution to a hostname the MockTransport
    # will intercept without touching the real Anthropic API.
    monkeypatch.setattr(forwarder, "UPSTREAM_BASE", "http://mock-upstream")

    # Seed two orgs + their tokens via the raw substrate (orgs has no
    # RLS, api_tokens insert path is the same shape `tokens issue`
    # uses).
    plaintext_a = generate_plaintext()
    plaintext_b = generate_plaintext()
    async with session_factory() as session:
        org_a = Org(name="cp9-org-a")
        org_b = Org(name="cp9-org-b")
        session.add_all([org_a, org_b])
        await session.flush()
        org_a_id = org_a.id
        org_b_id = org_b.id
        session.add(ApiToken(token_hash=hash_token(plaintext_a), org_id=org_a_id, name="cp9-a"))
        session.add(ApiToken(token_hash=hash_token(plaintext_b), org_id=org_b_id, name="cp9-b"))
        await session.commit()

    app = create_app(session_factory=session_factory)

    # Bypass FastAPI lifespan: the catch-all only needs an
    # `upstream_client` + `plugin_host` on `app.state`. The lifespan's
    # `on_init` would try to emit `proxy_started`, which the
    # session-bound audit writer no-ops outside a request anyway, but
    # opening real httpx clients per test would slow the suite without
    # adding coverage.
    upstream_client = httpx.AsyncClient(
        transport=httpx.MockTransport(_fake_anthropic),
    )
    plugin_host = PluginHost(audit_writer=session_bound_audit_writer)
    app.state.upstream_client = upstream_client
    app.state.plugin_host = plugin_host
    # The forwarder's generator opens a fresh post-stream session from
    # this factory; in production `create_app`'s lifespan sets this.
    app.state.session_factory = session_factory

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/messages",
                headers={
                    "X-LLM-Tracker-Token": plaintext_a,
                    "x-api-key": "sk-ant-test",
                    "content-type": "application/json",
                },
                content=b'{"model":"claude-x","messages":[]}',
            )
            # Drain the streamed body so the generator's
            # post-completion `record_exchange_timing` runs before
            # the ASGI cycle ends.
            assert response.status_code == 200
            assert response.content  # body iterated to completion
    finally:
        await upstream_client.aclose()

    # As org A: exactly one exchange row, tagged with org A.
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('app.org_id', :v, true)"),
            {"v": str(org_a_id)},
        )
        rows_a = (await session.execute(sa.select(Exchange))).scalars().all()
        assert len(rows_a) == 1
        assert rows_a[0].org_id == org_a_id
        assert rows_a[0].endpoint == "v1/messages"
        assert rows_a[0].blocked_by is None

    # As org B: the same row is invisible.
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('app.org_id', :v, true)"),
            {"v": str(org_b_id)},
        )
        rows_b = (await session.execute(sa.select(Exchange))).scalars().all()
        assert rows_b == []

    # Admin branch: cross-org visibility, single row total.
    async with session_factory() as session:
        await session.execute(sa.text("SELECT set_config('app.role', 'admin', true)"))
        count = await session.scalar(sa.select(sa.func.count()).select_from(Exchange))
        assert count == 1
