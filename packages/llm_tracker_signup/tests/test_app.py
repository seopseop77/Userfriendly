"""Integration tests for `app.py` — the FastAPI signup routes.

httpx AsyncClient + ASGITransport drives the in-process app so the
form-to-DB path is exercised end-to-end. The DB-touching tests use
the `db_engine` fixture (skipped without `LLMTRACK_TEST_DATABASE_URL`);
the pure-template tests run unconditionally.
"""

from __future__ import annotations

import httpx
import pytest
from fpdf import FPDF
from httpx import ASGITransport
from llm_tracker_signup.app import create_app
from llm_tracker_signup.config import Settings
from llm_tracker_signup.registration import PLAINTEXT_PREFIX
from sqlalchemy.ext.asyncio import AsyncEngine


def _make_pdf_bytes(text: str = "Test research proposal") -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(40, 10, text)
    return bytes(pdf.output())


async def _client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    )


@pytest.fixture
async def app_with_engine(db_engine: AsyncEngine):
    settings = Settings(database_url="ignored-test", proxy_server_url="https://proxy.example.com")
    app = create_app(settings=settings, engine=db_engine)
    async with app.router.lifespan_context(app):
        yield app


async def test_get_root_renders_form() -> None:
    settings = Settings(database_url="ignored-test")
    app = create_app(settings=settings, engine=object())  # engine not used for GET /
    async with app.router.lifespan_context(app), await _client_for(app) as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert "<form" in body
    assert 'name="email"' in body
    assert 'name="research_description"' in body
    assert 'accept=".pdf"' in body


async def test_healthz_ok() -> None:
    settings = Settings(database_url="ignored-test")
    app = create_app(settings=settings, engine=object())
    async with app.router.lifespan_context(app), await _client_for(app) as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_get_success_renders_token() -> None:
    settings = Settings(database_url="ignored-test", proxy_server_url="https://proxy.example.com")
    app = create_app(settings=settings, engine=object())
    async with app.router.lifespan_context(app), await _client_for(app) as client:
        resp = await client.get("/success?token=lts_demo123")
    assert resp.status_code == 200
    body = resp.text
    assert "lts_demo123" in body
    assert "https://proxy.example.com" in body
    assert (
        "https://github.com/seopseop77/Userfriendly/releases/download/agent/v0.1.3/"
        "llm_tracker_agent-0.1.3-py3-none-any.whl"
    ) in body
    # ADR-0035: Step 1 recommends `uv tool install <wheel-url>`, not
    # `pip install <wheel-url>`. Lock the recommended command in.
    assert "uv tool install https://github.com/seopseop77/Userfriendly" in body
    # The uv-bootstrap line is wrapped in a `command -v uv` guard so
    # participants who already have uv installed don't shadow it with a
    # second installation (observed: brew uv → astral uv at ~/.local/bin
    # after copy-paste).
    assert (
        "command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh"
        in body
    )
    # Each of the three step blocks must have a copy button wired to its
    # code element via the data-copy-target pattern.
    for step in ("step-1-code", "step-2-code", "step-3-code"):
        assert f'id="{step}"' in body
        assert f'data-copy-target="{step}"' in body
    # ADR-0035 Step 1 also exposes the uv-install commands as their own
    # copyable blocks. The main `step-1-code` block is the agent install
    # (uv tool install <wheel>); the uv-bootstrap commands are copyable
    # but optional, so we just check they exist.
    for extra in ("step-1-uv-code", "step-1-uv-win-code"):
        assert f'id="{extra}"' in body
        assert f'data-copy-target="{extra}"' in body


async def test_register_route_creates_registration(app_with_engine) -> None:
    async with await _client_for(app_with_engine) as client:
        resp = await client.post(
            "/register",
            data={
                "name": "Carol",
                "email": "carol@example.com",
                "institution": "Carol Univ.",
                "research_description": "Studying scope guard plugin effectiveness.",
            },
            files={
                "proposal": (
                    "proposal.pdf",
                    _make_pdf_bytes("Carol's proposal."),
                    "application/pdf",
                ),
            },
        )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith(f"/success?token={PLAINTEXT_PREFIX}")


async def test_register_route_no_proposal_pdf(app_with_engine) -> None:
    async with await _client_for(app_with_engine) as client:
        resp = await client.post(
            "/register",
            data={
                "name": "Dave",
                "email": "dave@example.com",
                "institution": "Dave Univ.",
                "research_description": "No proposal attached.",
            },
        )
    assert resp.status_code == 303
    assert resp.headers["location"].startswith(f"/success?token={PLAINTEXT_PREFIX}")


async def test_register_route_duplicate_email_returns_400(app_with_engine) -> None:
    async with await _client_for(app_with_engine) as client:
        first = await client.post(
            "/register",
            data={
                "name": "Eve",
                "email": "eve@example.com",
                "institution": "Eve Univ.",
                "research_description": "First attempt.",
            },
        )
        assert first.status_code == 303

        second = await client.post(
            "/register",
            data={
                "name": "Eve Again",
                "email": "eve@example.com",
                "institution": "Eve Univ. 2",
                "research_description": "Second attempt should fail.",
            },
        )
    assert second.status_code == 400
    assert "already registered" in second.text.lower()
