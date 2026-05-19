"""drop plugin_analytics.messages_json after Candidate-1 backfill

Revision ID: 0016_drop_messages_json
Revises: 0015_conversation_messages
Create Date: 2026-05-19

Migration 0015 added `conversation_messages` and `n_messages_at_request`
but deliberately left `messages_json` in place so the backfill could run
without risk of partial-state data loss. This migration ships the
final cleanup once the backfill is verified against §6 V1-V5 of
`docs/worklog/2026-05-19-candidate-1-handoff.md`:

* DROP VIEW plugin_analytics_with_messages — recreated below; the view
  uses `SELECT pa.*` which implicitly depends on every column of
  `plugin_analytics`, so a plain `DROP COLUMN` raises
  `cannot drop column ... because other objects depend on it`.
* DROP COLUMN messages_json — the dedup table + the pointer
  `n_messages_at_request` replace it.
* CREATE VIEW plugin_analytics_with_messages — same shape as 0015 but
  bound to the smaller plugin_analytics schema.

Live apply order (operator-driven, see worklog §11):
    1. 0015 schema-extending DDL via execute_sql (atomic BEGIN/COMMIT).
    2. Backfill INSERT INTO conversation_messages ... ON CONFLICT DO
       NOTHING + UPDATE plugin_analytics SET n_messages_at_request = ...
       (one execute_sql call).
    3. Verify §6 V1-V5 against live data.
    4. **This migration** via execute_sql.

Downgrade re-adds `messages_json` as nullable text — no data restore
is possible since the source dropped out at step 4. Production is not
expected to roll back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_drop_messages_json"
down_revision: str | Sequence[str] | None = "0015_conversation_messages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP VIEW plugin_analytics_with_messages")
    op.drop_column("plugin_analytics", "messages_json")
    op.execute(
        """
        CREATE VIEW plugin_analytics_with_messages AS
        SELECT
            pa.*,
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'role', cm.role,
                        'content', cm.content_jsonb
                    )
                    ORDER BY cm.msg_index
                )
                FROM conversation_messages cm
                WHERE cm.conversation_id = pa.conversation_id
                  AND cm.msg_index < pa.n_messages_at_request
            ) AS messages_jsonb
        FROM plugin_analytics pa
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW plugin_analytics_with_messages")
    op.add_column(
        "plugin_analytics",
        sa.Column("messages_json", sa.Text(), nullable=True),
    )
    op.execute(
        """
        CREATE VIEW plugin_analytics_with_messages AS
        SELECT
            pa.*,
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'role', cm.role,
                        'content', cm.content_jsonb
                    )
                    ORDER BY cm.msg_index
                )
                FROM conversation_messages cm
                WHERE cm.conversation_id = pa.conversation_id
                  AND cm.msg_index < pa.n_messages_at_request
            ) AS messages_jsonb
        FROM plugin_analytics pa
        """
    )
