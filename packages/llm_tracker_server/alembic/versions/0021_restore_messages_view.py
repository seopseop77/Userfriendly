"""ADR-0039 — restore plugin_analytics_with_messages view atop the per-exchange delta schema

Revision ID: 0021_restore_messages_view
Revises: 0020_enable_rls_operator_tables
Create Date: 2026-05-27

Rebuilds the convenience view that ADR-0036 introduced and ADR-0038
(migration 0019) dropped. The new shape stitches per-exchange deltas
(`request_jsonb` + `response_jsonb`) into the alternating messages[]
array that the model saw on each request, and adds a
`system_prompt_resolved` column that carries forward ADR-0038's
variation-tracked `system_prompt_jsonb`.

Sidecar rows (`role = 'sidecar'`) contribute nothing to
`messages_jsonb` — they are framework auto-call rows whose payload is
already visible on the row's own `request_jsonb`. See ADR-0039 §Options
considered for the trade-off vs interleaving them.

The view is non-materialised — zero storage cost, read-time
recompute. At current scale (largest conversation ≈ 41 main-flow rows)
the correlated subquery is sub-second. Revisit when any single
conversation crosses ≈ 200 main-flow rows.

Downgrade: DROP VIEW. No data depends on the view.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021_restore_messages_view"
down_revision: str | Sequence[str] | None = "0020_enable_rls_operator_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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
    op.execute(_VIEW_SQL)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS plugin_analytics_with_messages")
