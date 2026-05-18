"""scope_alerts 6-month retention via pg_cron (ADR-0030 §Q3)

Revision ID: 0011_scope_alerts_retention
Revises: 0010_scope_guard_tables
Create Date: 2026-05-18

Resolves ADR-0030 §Q3. The decision was made at CP1 time to ship the
scope_alerts retention as a new migration rather than amending 0009 —
each retention concern owns its own reversible migration; mixing a
third cron row with a different table/column/unit shape into 0009
muddies the downgrade.

One daily job at 03:00 UTC:

* ``llm-tracker-retention-scope-alerts`` —
  ``public.scope_alerts.created_at`` is ``timestamptz`` (ADR-0030 §D8
  schema), so the cutoff is ``now() - INTERVAL '6 months'`` directly —
  same shape as 0009's plugin_analytics job.

``scope_documents`` and ``scope_chunks`` are **not** retention-managed
(ADR-0030 §D8: operator-curated baseline content, retained
indefinitely). Operators delete those manually via
``DELETE FROM scope_documents WHERE org_id = $1 AND title = $2`` (the
chunks cascade away via the migration-0010 ``ON DELETE CASCADE``) or
re-register over the prior corpus with the
``process-scope-document`` CLI from CP6.

Gated on ``pg_cron`` availability — local dev / test environments that
lack the extension (stock Postgres docker image) keep their alembic
upgrade/downgrade cycle green; the deletion job simply does not exist
there and the operator falls back to the manual DELETE path documented
in ``docs/deploy.md``.

Reversible: the downgrade unschedules the job if ``pg_cron`` is
installed. The extension itself is **not** dropped — same blast-radius
reasoning as 0009 and migration 0010's pgvector.
"""

from __future__ import annotations

from alembic import op

revision = "0011_scope_alerts_retention"
down_revision = "0010_scope_guard_tables"
branch_labels = None
depends_on = None


_UPGRADE_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron') THEN
        RAISE NOTICE 'pg_cron not available; skipping scope_alerts retention scheduler';
        RETURN;
    END IF;
    CREATE EXTENSION IF NOT EXISTS pg_cron;

    IF NOT EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'llm-tracker-retention-scope-alerts'
    ) THEN
        PERFORM cron.schedule(
            'llm-tracker-retention-scope-alerts',
            '0 3 * * *',
            $cron$
                DELETE FROM public.scope_alerts
                 WHERE created_at < now() - INTERVAL '6 months'
            $cron$
        );
    END IF;
END$$;
"""


_DOWNGRADE_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        RETURN;
    END IF;
    IF EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'llm-tracker-retention-scope-alerts'
    ) THEN
        PERFORM cron.unschedule('llm-tracker-retention-scope-alerts');
    END IF;
END$$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
