"""Per-org token primitives (ADR-0020 Axis 1).

Only the SHA-256 hex of the token is stored. The plaintext is shown to
the operator exactly once at issuance and never persisted -- a leaked DB
dump therefore cannot reconstruct an active credential. Revocation flips
`revoked_at` rather than deleting the row, so the middleware's
`revoked_at IS NOT NULL` check remains the single source of truth for
"is this token currently valid?".

Plaintext shape: `lts_` + `secrets.token_urlsafe(32)` (~43 url-safe chars
after the prefix). The prefix is purely a self-documenting tag for
operators reading server logs of revocation requests; the lookup keys on
the hash, not the prefix.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from llm_tracker_server.storage import ApiToken, Org

PLAINTEXT_PREFIX = "lts_"


def hash_token(plaintext: str) -> str:
    """SHA-256 hex digest. The single hashing primitive used by both
    middleware lookup and CLI issuance -- if this changes, both move
    together."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_plaintext() -> str:
    """Mint a new opaque bearer token. ~43 chars of url-safe randomness
    after the `lts_` prefix; 32 bytes of entropy."""
    return PLAINTEXT_PREFIX + secrets.token_urlsafe(32)


async def lookup(session: AsyncSession, plaintext: str) -> ApiToken | None:
    """Return the active `ApiToken` matching `plaintext`, or None.

    A revoked token resolves to None (callers cannot distinguish "wrong
    token" from "revoked token", which is the right shape: don't leak
    revocation status to unauthenticated callers).
    """
    stmt = sa.select(ApiToken).where(
        ApiToken.token_hash == hash_token(plaintext),
        ApiToken.revoked_at.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def issue(
    session: AsyncSession,
    *,
    org_name: str,
    token_name: str | None = None,
) -> tuple[str, uuid.UUID, str]:
    """Issue a token for `org_name` (creating the org if missing).

    Returns `(plaintext, org_id, token_hash)`. The caller is responsible
    for committing the session -- making the persistence boundary
    explicit so the CLI can `echo` the plaintext only after a successful
    commit. The plaintext is **never returned again**: the CLI must
    surface it to the operator at this call site.
    """
    existing = (
        await session.execute(sa.select(Org).where(Org.name == org_name))
    ).scalar_one_or_none()
    if existing is None:
        org = Org(name=org_name)
        session.add(org)
        await session.flush()
    else:
        org = existing

    plaintext = generate_plaintext()
    token_hash = hash_token(plaintext)
    session.add(ApiToken(token_hash=token_hash, org_id=org.id, name=token_name))
    return plaintext, org.id, token_hash


async def revoke(session: AsyncSession, *, token_hash: str) -> bool:
    """Mark `token_hash` revoked. Returns True if exactly one active row
    was affected. Idempotent re-revocation returns False so the CLI can
    fail loudly on "no matching active token"."""
    result = await session.execute(
        sa.update(ApiToken)
        .where(ApiToken.token_hash == token_hash, ApiToken.revoked_at.is_(None))
        .values(revoked_at=sa.func.now())
    )
    return result.rowcount == 1


async def list_for_org(
    session: AsyncSession, *, org_name: str | None = None
) -> list[tuple[ApiToken, Org]]:
    """Return `(token, org)` rows, optionally filtered by org name.

    Plaintext is unrecoverable -- this is for hash-prefix / status
    listing only.
    """
    stmt = sa.select(ApiToken, Org).join(Org, ApiToken.org_id == Org.id)
    if org_name is not None:
        stmt = stmt.where(Org.name == org_name)
    stmt = stmt.order_by(Org.name, ApiToken.created_at)
    rows = (await session.execute(stmt)).all()
    return [(tok, org) for tok, org in rows]
