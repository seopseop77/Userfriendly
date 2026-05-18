"""schema cleanup — drop unused tables and columns

Revision ID: 0013_schema_cleanup
Revises: 0012_scope_chunks_embed_dim_768
Create Date: 2026-05-18

Removes schema that was ported from the SQLite-era local sidecar but
never implemented (no INSERT call sites existed):

Tables dropped:
  - events       — per-exchange event log; INSERT never wired up
  - tool_calls   — per-exchange tool-use rows; INSERT never wired up

Columns dropped from `exchanges`:
  - input_tokens, output_tokens       — token counts moved to plugin_analytics
  - cache_read_tokens, cache_write_tokens — same; plugin_analytics is the
                                           authority for cost data

Columns dropped from `plugin_analytics`:
  - tool_call_count  — always 0; no fill logic existed
  - system_prompt    — redundant with messages_json; removed for simplicity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_schema_cleanup"
down_revision: str | Sequence[str] | None = "0012_scope_chunks_embed_dim_768"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop unused tables (events has an index; tool_calls has none).
    op.drop_index("idx_events_exchange", table_name="events")
    op.drop_table("events")
    op.drop_table("tool_calls")

    # Drop token columns from exchanges — plugin_analytics is authoritative.
    op.drop_column("exchanges", "input_tokens")
    op.drop_column("exchanges", "output_tokens")
    op.drop_column("exchanges", "cache_read_tokens")
    op.drop_column("exchanges", "cache_write_tokens")

    # Drop never-filled / redundant columns from plugin_analytics.
    op.drop_column("plugin_analytics", "tool_call_count")
    op.drop_column("plugin_analytics", "system_prompt")


def downgrade() -> None:
    # Restore plugin_analytics columns.
    op.add_column(
        "plugin_analytics",
        sa.Column("system_prompt", sa.Text(), nullable=True),
    )
    op.add_column(
        "plugin_analytics",
        sa.Column(
            "tool_call_count",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )

    # Restore exchanges token columns (all nullable — no data to backfill).
    op.add_column("exchanges", sa.Column("cache_write_tokens", sa.BigInteger(), nullable=True))
    op.add_column("exchanges", sa.Column("cache_read_tokens", sa.BigInteger(), nullable=True))
    op.add_column("exchanges", sa.Column("output_tokens", sa.BigInteger(), nullable=True))
    op.add_column("exchanges", sa.Column("input_tokens", sa.BigInteger(), nullable=True))

    # Restore tool_calls table.
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("input_hash", sa.String(), nullable=True),
        sa.Column("input_json", sa.Text(), nullable=True),
        sa.Column("result_hash", sa.String(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"]),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"]),
    )

    # Restore events table + index.
    op.create_table(
        "events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange_id", sa.String(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"]),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"]),
    )
    op.create_index("idx_events_exchange", "events", ["exchange_id", "seq"])
