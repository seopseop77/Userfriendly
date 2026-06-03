"""Token issuance for the signup app.

The only callers are `app.py` (one POST handler) and the test suite.
There is no operator CLI here — the proxy server's
`llm-tracker-server` CLI already covers manual token issuance.

Token issuance duplicates the minimal logic from
`llm_tracker_server.auth.tokens.issue` as raw async SQL so this
package has no import dependency on the proxy server. The
duplicated surface is ~10 lines (sha256 + url-safe random + three
INSERTs) — the brief explicitly accepts the duplication in exchange
for an independent deploy unit.
"""

from __future__ import annotations

import hashlib
import secrets

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

PLAINTEXT_PREFIX = "lts_"


class DuplicateEmailError(Exception):
    """Raised when registration tries to reuse an email already in
    `participant_registrations`. The signup app maps this to a 400
    response with a human-readable message; the database also has a
    UNIQUE constraint on `email` as the authoritative guard against
    races.
    """

    def __init__(self, email: str) -> None:
        super().__init__(f"email already registered: {email}")
        self.email = email


async def register_participant(
    engine: AsyncEngine,
    *,
    name: str,
    email: str,
    institution: str,
) -> str:
    """Issue a token and write the registration in one transaction.

    Returns the plaintext token. Raises `DuplicateEmailError` if `email`
    already exists in `participant_registrations`. All three writes
    (`orgs`, `api_tokens`, `participant_registrations`) sit inside one
    `engine.begin()` block so a mid-flow failure rolls back cleanly —
    no orphaned org or unbacked token row.
    """
    plaintext = PLAINTEXT_PREFIX + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    org_name = f"participant:{email}"
    token_name = f"signup:{email}"

    async with engine.begin() as conn:
        existing_email = await conn.execute(
            sa.text(
                "SELECT 1 FROM participant_registrations "
                "WHERE email = :email LIMIT 1"
            ),
            {"email": email},
        )
        if existing_email.scalar_one_or_none() is not None:
            raise DuplicateEmailError(email)

        existing_org = await conn.execute(
            sa.text("SELECT id FROM orgs WHERE name = :name LIMIT 1"),
            {"name": org_name},
        )
        org_id = existing_org.scalar_one_or_none()
        if org_id is None:
            inserted = await conn.execute(
                sa.text("INSERT INTO orgs (name) VALUES (:name) RETURNING id"),
                {"name": org_name},
            )
            org_id = inserted.scalar_one()

        await conn.execute(
            sa.text(
                "INSERT INTO api_tokens (token_hash, org_id, name) "
                "VALUES (:token_hash, :org_id, :name)"
            ),
            {"token_hash": token_hash, "org_id": org_id, "name": token_name},
        )
        # research_description / proposal_text are no longer collected by the
        # form. The columns are kept (NOT NULL on research_description) and
        # written as empty/NULL so the schema is untouched.
        await conn.execute(
            sa.text(
                "INSERT INTO participant_registrations ("
                "org_id, token_hash, name, email, institution, "
                "research_description, proposal_text"
                ") VALUES ("
                ":org_id, :token_hash, :name, :email, :institution, "
                "'', NULL"
                ")"
            ),
            {
                "org_id": org_id,
                "token_hash": token_hash,
                "name": name,
                "email": email,
                "institution": institution,
            },
        )

    return plaintext
