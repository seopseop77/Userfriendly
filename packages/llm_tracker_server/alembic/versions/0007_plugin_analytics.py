"""plugin_analytics — write target for the analytics_sink plugin (ADR-0026 δ)

Revision ID: 0007_plugin_analytics
Revises: 0006_grant_app_role_set
Create Date: 2026-05-14

The `analytics_sink` plugin (checkpoint δ) writes one row per
completed exchange with the full request + response payloads, the
extractor's token counts, and the stop_reason. Schema is
intentionally simpler than `public.exchanges`:

* No FK on `exchange_id`. The plugin writes from `on_persisted`
  *after* the forwarder's `record_exchange_timing` flush, but we do
  not enforce ordering across separate sessions — a FK would fail
  any time the plugin lags the forwarder's commit.
* `org_id UUID NOT NULL REFERENCES orgs(id)` keeps tenancy intact;
  the plugin reads `ctx.org_id` (ADR-0026 SDK addition) to populate
  it. The FK to `orgs(id)` is the same shape the four CP4 user-data
  tables already use.
* No RLS on this table. Analytics is internal — the plugin queries
  this directly from operator tooling without going through the
  request-scoped session. ADR-0018's RLS guarantee covers
  `exchanges` and the three sibling user-data tables; the
  `plugin_analytics` table is a separate downstream surface.
* `created_at` is server-default `now()` (TIMESTAMPTZ) — no
  application-supplied timestamp. Mirrors the `orgs` / `api_tokens`
  pattern.
* `messages_json` is NOT NULL because the plugin always has the
  request body to stash (we read `ctx.request_text()` on
  `on_request_received`). `response_json` is nullable: the
  extractor produces None on truncated streams (ADR-0027 axis 1).

Indices on `org_id` and `created_at` cover the two queries the
operator is most likely to run: "what did org X do" and "what
happened in the last hour."

The migration is idempotent on the alembic stamp axis; the table
itself is DROP'd on downgrade so the round-trip is clean.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0007_plugin_analytics"
down_revision: str | Sequence[str] | None = "0006_grant_app_role_set"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "plugin_analytics",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("exchange_id", sa.Text(), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("model_requested", sa.Text(), nullable=True),
        sa.Column("model_served", sa.Text(), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("messages_json", sa.Text(), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_write_tokens", sa.BigInteger(), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column(
            "tool_call_count",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"]),
    )
    op.create_index(
        "idx_plugin_analytics_org",
        "plugin_analytics",
        ["org_id"],
    )
    op.create_index(
        "idx_plugin_analytics_created",
        "plugin_analytics",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_plugin_analytics_created", table_name="plugin_analytics")
    op.drop_index("idx_plugin_analytics_org", table_name="plugin_analytics")
    op.drop_table("plugin_analytics")
