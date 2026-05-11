"""org_id NOT NULL on user-data tables (ADR-0018 tenancy)

Revision ID: 0004_org_id_on_user_data
Revises: 0003_orgs_and_tokens
Create Date: 2026-05-11

Adds `org_id UUID NOT NULL REFERENCES orgs(id)` to the four user-data tables
(`exchanges`, `events`, `tool_calls`, `audit_log`). Pure schema column: no
backfill is needed because the server-side schema is greenfield (Phase 3c
plan §"Greenfield server-side database, no SQLite -> Postgres data
migration"). The supabase-sink CP9 demo rows are operator data and get
dropped/recreated against the new shape, not migrated forward.

Defense-in-depth: the NOT NULL + FK constraints land here (CP4); RLS
policies land in CP5; per-request `SET LOCAL app.org_id` lands in CP6.
A wrong-org write is rejected by RLS first and the FK second; this
checkpoint is the FK half.

No index on `org_id` yet -- mirroring the CP3 decision for
`api_tokens.org_id`. The hot query paths land with CP6/CP9 and will
choose indexes against the queries they actually write.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_org_id_on_user_data"
down_revision: str | Sequence[str] | None = "0003_orgs_and_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("exchanges", "events", "tool_calls", "audit_log"):
        op.add_column(
            table,
            sa.Column(
                "org_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("orgs.id"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    for table in ("audit_log", "tool_calls", "events", "exchanges"):
        op.drop_column(table, "org_id")
