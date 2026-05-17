"""6-month retention deletion via pg_cron (ADR-0029 Axis 3)

Revision ID: 0009_retention_deletion_job
Revises: 0008_drop_tool_call_count
Create Date: 2026-05-17

ADR-0029 Axis 3 set the policy: rows older than 6 months are deleted.
Until now that has been a manual operator DELETE (`docs/deploy.md`
§"Data collection & privacy"). This migration ships the automated
half via ``pg_cron``, available by default on Supabase.

Two daily jobs at 03:00 UTC:

* ``llm-tracker-retention-exchanges`` — ``public.exchanges.started_at``
  is unix milliseconds, so the cutoff is
  ``(EXTRACT(EPOCH FROM now() - INTERVAL '6 months') * 1000)::bigint``.
* ``llm-tracker-retention-plugin-analytics`` —
  ``public.plugin_analytics.created_at`` is ``timestamptz``, so the
  cutoff is ``now() - INTERVAL '6 months'`` directly.

Gated on ``pg_cron`` availability: local dev / test environments that
lack the extension (stock Postgres docker image) keep their alembic
upgrade/downgrade cycle green. In that case the deletion job simply
does not exist and the operator falls back to the manual DELETE path
documented in ``docs/deploy.md``.

Reversible: the downgrade unschedules both jobs if ``pg_cron`` is
installed. The extension itself is **not** dropped — other parts of
the Supabase project may rely on it, and dropping a project-wide
extension to revert a single migration is the wrong blast radius.
"""

from __future__ import annotations

from alembic import op

revision = "0009_retention_deletion_job"
down_revision = "0008_drop_tool_call_count"
branch_labels = None
depends_on = None


_UPGRADE_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_cron') THEN
        RAISE NOTICE 'pg_cron not available; skipping retention scheduler';
        RETURN;
    END IF;
    CREATE EXTENSION IF NOT EXISTS pg_cron;

    IF NOT EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'llm-tracker-retention-exchanges'
    ) THEN
        PERFORM cron.schedule(
            'llm-tracker-retention-exchanges',
            '0 3 * * *',
            $cron$
                DELETE FROM public.exchanges
                 WHERE started_at < (
                    EXTRACT(EPOCH FROM now() - INTERVAL '6 months') * 1000
                 )::bigint
            $cron$
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM cron.job WHERE jobname = 'llm-tracker-retention-plugin-analytics'
    ) THEN
        PERFORM cron.schedule(
            'llm-tracker-retention-plugin-analytics',
            '0 3 * * *',
            $cron$
                DELETE FROM public.plugin_analytics
                 WHERE created_at < now() - INTERVAL '6 months'
            $cron$
        );
    END IF;
END$$;
"""


_DOWNGRADE_SQL = """
DO $$
DECLARE
    j RECORD;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        RETURN;
    END IF;
    FOR j IN
        SELECT jobname FROM cron.job
         WHERE jobname IN ('llm-tracker-retention-exchanges',
                           'llm-tracker-retention-plugin-analytics')
    LOOP
        PERFORM cron.unschedule(j.jobname);
    END LOOP;
END$$;
"""


def upgrade() -> None:
    op.execute(_UPGRADE_SQL)


def downgrade() -> None:
    op.execute(_DOWNGRADE_SQL)
