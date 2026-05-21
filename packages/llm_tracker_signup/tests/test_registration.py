"""Unit tests for `registration.py`.

PDF extraction tests run without a database (pure-function shape).
Token-issuance tests require `LLMTRACK_TEST_DATABASE_URL` (conftest
skips them otherwise).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from fpdf import FPDF
from llm_tracker_signup.registration import (
    PLAINTEXT_PREFIX,
    DuplicateEmailError,
    extract_pdf_text,
    register_participant,
)
from sqlalchemy.ext.asyncio import AsyncEngine


def _make_pdf_bytes(text: str = "Hello signup test") -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=12)
    pdf.cell(40, 10, text)
    return bytes(pdf.output())


def test_extract_pdf_text_returns_string() -> None:
    body = _make_pdf_bytes("Project proposal: anomaly detection.")
    out = extract_pdf_text(body)
    assert isinstance(out, str)
    assert "anomaly detection" in out


def test_extract_pdf_text_bad_bytes_returns_empty() -> None:
    assert extract_pdf_text(b"not a pdf at all") == ""


def test_extract_pdf_text_empty_bytes_returns_empty() -> None:
    assert extract_pdf_text(b"") == ""


async def test_issue_token_happy_path(db_engine: AsyncEngine) -> None:
    plaintext = await register_participant(
        db_engine,
        name="Alice",
        email="alice@example.com",
        institution="Test University",
        research_description="Study LLM agent traces.",
        proposal_text=None,
    )
    assert plaintext.startswith(PLAINTEXT_PREFIX)
    assert len(plaintext) > len(PLAINTEXT_PREFIX) + 30

    async with db_engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    "SELECT name, email, institution, proposal_text "
                    "FROM participant_registrations WHERE email = :email"
                ),
                {"email": "alice@example.com"},
            )
        ).one()
        org_row = (
            await conn.execute(
                sa.text("SELECT name FROM orgs WHERE name = :name"),
                {"name": "participant:alice@example.com"},
            )
        ).one()
    assert row.name == "Alice"
    assert row.institution == "Test University"
    assert row.proposal_text is None
    assert org_row.name == "participant:alice@example.com"


async def test_issue_token_duplicate_email_raises(db_engine: AsyncEngine) -> None:
    await register_participant(
        db_engine,
        name="Bob",
        email="bob@example.com",
        institution="X",
        research_description="Y",
        proposal_text=None,
    )
    with pytest.raises(DuplicateEmailError) as excinfo:
        await register_participant(
            db_engine,
            name="Bob 2",
            email="bob@example.com",
            institution="X2",
            research_description="Y2",
            proposal_text=None,
        )
    assert excinfo.value.email == "bob@example.com"
