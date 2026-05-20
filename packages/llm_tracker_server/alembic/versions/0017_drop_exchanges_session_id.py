"""drop exchanges.session_id — obsoleted by plugin_analytics

Revision ID: 0017_drop_exchanges_session_id
Revises: 0016_drop_messages_json
Create Date: 2026-05-21

`exchanges.session_id` was hardcoded to ``"server"`` at every call site
in the forwarder (ADR-0027 §"Population matrix"). The queued
follow-up "real `session_id` populator + deletion endpoint" never
materialised because the analytics_sink plugin's
`conversation_id` (a stable, hash-derived chain identifier) and
`first_msg_hash` (the same row-key that disambiguates re-prompts)
cover every use case `session_id` was intended for:

* per-conversation grouping → ``plugin_analytics.conversation_id``
* deduplication of same-prompt retries → ``plugin_analytics.first_msg_hash``
* operator-side deletion scope → both columns above are queryable

The column has zero queries against it in the codebase and no
non-``"server"`` values in production. Dropping it removes a dead
field from every ``Exchange(...)`` constructor call and the ORM.

Downgrade re-adds the column ``NOT NULL DEFAULT 'server'`` so existing
rows backfill with the same sentinel value the helpers were writing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_drop_exchanges_session_id"
down_revision = "0016_drop_messages_json"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("exchanges", "session_id")


def downgrade() -> None:
    op.add_column(
        "exchanges",
        sa.Column(
            "session_id",
            sa.Text(),
            nullable=False,
            server_default="server",
        ),
    )
