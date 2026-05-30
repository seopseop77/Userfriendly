"""Refresh plugin_analytics_with_messages so it surfaces session_id

Revision ID: 0023_view_session_id
Revises: 0022_plugin_analytics_session_id
Create Date: 2026-05-31

The `plugin_analytics_with_messages` view (migration 0021) was created
with `SELECT pa.*`, which Postgres expands to an explicit column list
*at CREATE time*. Migration 0022 added `plugin_analytics.session_id`
afterwards, so the frozen view never picked it up. This migration drops
and re-creates the view with the identical SQL; `pa.*` now re-expands
to include `session_id` (placed after the base columns, before the
computed `messages_jsonb` / `system_prompt_resolved`).

The view body is byte-identical to migration 0021 — only the moment of
expansion changes. Grouping, RLS, and security semantics are unchanged.

Downgrade re-runs the same DROP + CREATE (best-effort, not expected in
production): `session_id` presence in the view tracks the column, not
this migration, so a downgrade that leaves the 0022 column in place
still yields a view carrying session_id.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023_view_session_id"
down_revision: str | Sequence[str] | None = "0022_plugin_analytics_session_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Verbatim copy of migration 0021's view body. `pa.*` now includes
# session_id because the column exists at this CREATE.
_VIEW_SQL = """
CREATE VIEW plugin_analytics_with_messages AS
SELECT
    pa.*,
    CASE
        WHEN pa.role IN ('user_input', 'tool_result') THEN (
            SELECT jsonb_agg(msg ORDER BY ord, kind, id_tiebreak)
            FROM (
                SELECT
                    jsonb_build_object('role', 'user',
                                       'content', prior.request_jsonb) AS msg,
                    prior.created_at AS ord,
                    0 AS kind,
                    prior.id AS id_tiebreak
                FROM plugin_analytics prior
                WHERE prior.conversation_id = pa.conversation_id
                  AND prior.role IN ('user_input', 'tool_result')
                  AND prior.created_at < pa.created_at

                UNION ALL

                SELECT
                    jsonb_build_object('role', 'assistant',
                                       'content', prior.response_jsonb -> 'content') AS msg,
                    prior.created_at AS ord,
                    1 AS kind,
                    prior.id AS id_tiebreak
                FROM plugin_analytics prior
                WHERE prior.conversation_id = pa.conversation_id
                  AND prior.role IN ('user_input', 'tool_result')
                  AND prior.created_at < pa.created_at

                UNION ALL

                SELECT
                    jsonb_build_object('role', 'user',
                                       'content', pa.request_jsonb) AS msg,
                    pa.created_at AS ord,
                    0 AS kind,
                    pa.id AS id_tiebreak
            ) m
        )
        ELSE NULL
    END AS messages_jsonb,
    (
        SELECT s.system_prompt_jsonb
        FROM plugin_analytics s
        WHERE s.conversation_id = pa.conversation_id
          AND s.created_at <= pa.created_at
          AND s.system_prompt_jsonb IS NOT NULL
        ORDER BY s.created_at DESC
        LIMIT 1
    ) AS system_prompt_resolved
FROM plugin_analytics pa
"""


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS plugin_analytics_with_messages")
    op.execute(_VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS plugin_analytics_with_messages")
    op.execute(_VIEW_SQL)
