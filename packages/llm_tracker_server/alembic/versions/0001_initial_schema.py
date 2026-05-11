"""initial schema (PostgreSQL)

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-11

Consolidates the SQLite-era migrations `350b17be77ae_initial_schema` and
`b1c2d3e4f5a6_add_timing_columns` into a single PostgreSQL migration.
Greenfield server-side schema — no data to migrate (see Phase 3c plan
CP4 Decisions). Tenancy (`org_id`) and RLS land in CP4/CP5; the
`audit_log` append-only trigger lands in `0002_audit_log_triggers`.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "exchanges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("started_at", sa.BigInteger(), nullable=False),
        sa.Column("ended_at", sa.BigInteger(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column("model_requested", sa.String(), nullable=True),
        sa.Column("model_served", sa.String(), nullable=True),
        sa.Column("status_code", sa.BigInteger(), nullable=True),
        sa.Column("input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_read_tokens", sa.BigInteger(), nullable=True),
        sa.Column("cache_write_tokens", sa.BigInteger(), nullable=True),
        sa.Column("latency_ms", sa.BigInteger(), nullable=True),
        sa.Column("stop_reason", sa.String(), nullable=True),
        sa.Column("t_request_received_ms", sa.BigInteger(), nullable=True),
        sa.Column("t_upstream_first_byte_ms", sa.BigInteger(), nullable=True),
        sa.Column("t_client_first_byte_ms", sa.BigInteger(), nullable=True),
        sa.Column("tool_call_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("content_level", sa.String(), nullable=False),
        sa.Column("blocked_by", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_exchanges_started", "exchanges", ["started_at"], unique=False)

    op.create_table(
        "events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("exchange_id", sa.String(), nullable=False),
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_events_exchange", "events", ["exchange_id", "seq"], unique=False)

    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("exchange_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("input_hash", sa.String(), nullable=True),
        sa.Column("input_json", sa.Text(), nullable=True),
        sa.Column("result_hash", sa.String(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["exchange_id"], ["exchanges.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("ts", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("plugin", sa.String(), nullable=True),
        sa.Column("hook", sa.String(), nullable=True),
        sa.Column("capability", sa.String(), nullable=True),
        sa.Column("destination", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(), nullable=False),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_ts", "audit_log", ["ts"], unique=False)
    op.create_index("idx_audit_plugin", "audit_log", ["plugin"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_audit_plugin", table_name="audit_log")
    op.drop_index("idx_audit_ts", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("tool_calls")
    op.drop_index("idx_events_exchange", table_name="events")
    op.drop_table("events")
    op.drop_index("idx_exchanges_started", table_name="exchanges")
    op.drop_table("exchanges")
