"""Unit tests for `registration.py`.

Token-issuance tests require `LLMTRACK_TEST_DATABASE_URL` (conftest
skips them otherwise).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from llm_tracker_signup.registration import (
    PLAINTEXT_PREFIX,
    DuplicateEmailError,
    register_participant,
)
from sqlalchemy.ext.asyncio import AsyncEngine


async def test_issue_token_happy_path(db_engine: AsyncEngine) -> None:
    plaintext = await register_participant(
        db_engine,
        name="Alice",
        email="alice@example.com",
        institution="Test University",
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
    )
    with pytest.raises(DuplicateEmailError) as excinfo:
        await register_participant(
            db_engine,
            name="Bob 2",
            email="bob@example.com",
            institution="X2",
        )
    assert excinfo.value.email == "bob@example.com"
