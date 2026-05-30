"""Capture client session id on plugin_analytics

Revision ID: 0022_plugin_analytics_session_id
Revises: 0021_restore_messages_view
Create Date: 2026-05-30

Adds a nullable `session_id` column to plugin_analytics. Claude Code
sends the CLI session id in the request's `metadata.user_id` JSON
(`{"device_id", "account_uuid", "session_id"}`); the value is stable
across every request of one session — parent and all sub-agents it
spawns share it. Capturing it gives a parent↔sub-agent link signal
that the hash-based conversation grouping does not provide on its own.

This is forward-only and grouping-neutral: `conversation_id`
derivation is unchanged. Historic rows keep NULL (raw request bodies
were never retained, so there is nothing to backfill). Whether to fold
`session_id` into the grouping key is deferred to a future ADR.

The `plugin_analytics_with_messages` view (migration 0021) froze its
column list to `pa.*` at creation time, so ADD COLUMN neither breaks
nor surfaces the new column there. Querying `session_id` reads the
base table directly.

Downgrade drops the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_plugin_analytics_session_id"
down_revision: str | Sequence[str] | None = "0021_restore_messages_view"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plugin_analytics",
        sa.Column("session_id", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("plugin_analytics", "session_id")
