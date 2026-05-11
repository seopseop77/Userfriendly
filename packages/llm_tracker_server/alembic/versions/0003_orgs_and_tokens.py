"""orgs + api_tokens (ADR-0018 substrate)

Revision ID: 0003_orgs_and_tokens
Revises: 0002_audit_log_triggers
Create Date: 2026-05-11

Adds the two tenancy substrate tables that anchor ADR-0018 (per-org RLS) and
ADR-0020 (per-org bearer token at the agent->server boundary):

- `orgs` — one row per tenant. UUID PK with `gen_random_uuid()` server default
  (PG 13+ ships this in core; no extension required).
- `api_tokens` — bearer-token store keyed by SHA-256 hex of the plaintext.
  Plaintext is shown once at issuance per ADR-0020 and never persisted.
  `ON DELETE CASCADE` lets an operator drop an org without orphaned tokens.

`org_id` does not land on the user-data tables here — that is CP4. RLS
policies land in CP5.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_orgs_and_tokens"
down_revision: str | Sequence[str] | None = "0002_audit_log_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orgs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )

    op.create_table(
        "api_tokens",
        sa.Column("token_hash", sa.Text(), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("api_tokens")
    op.drop_table("orgs")
