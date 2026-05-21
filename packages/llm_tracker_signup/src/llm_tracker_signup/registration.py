"""PDF text extraction + token issuance for the signup app.

Both responsibilities live in one module to keep the surface area
small: the only callers are `app.py` (one POST handler) and the
test suite. There is no operator CLI here — the proxy server's
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
import io
import secrets

import pdfplumber
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


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Return the concatenated text content of every page in `pdf_bytes`.

    Returns an empty string on any parse failure: a malformed upload
    should not block registration, and image-only PDFs legitimately
    have no extractable text. The operator can follow up via email if
    the textual description on the form is insufficient.
    """
    if not pdf_bytes:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except Exception:
        return ""


async def register_participant(
    engine: AsyncEngine,
    *,
    name: str,
    email: str,
    institution: str,
    research_description: str,
    proposal_text: str | None,
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
        await conn.execute(
            sa.text(
                "INSERT INTO participant_registrations ("
                "org_id, token_hash, name, email, institution, "
                "research_description, proposal_text"
                ") VALUES ("
                ":org_id, :token_hash, :name, :email, :institution, "
                ":research_description, :proposal_text"
                ")"
            ),
            {
                "org_id": org_id,
                "token_hash": token_hash,
                "name": name,
                "email": email,
                "institution": institution,
                "research_description": research_description,
                "proposal_text": proposal_text,
            },
        )

    return plaintext
