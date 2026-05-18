"""scope_guard tables — documents, chunks (pgvector), alerts (ADR-0030 §D8)

Revision ID: 0010_scope_guard_tables
Revises: 0009_retention_deletion_job
Create Date: 2026-05-18

ADR-0030 §D8 schema. One pgvector extension + three tables:

* ``CREATE EXTENSION vector`` -- already present on Supabase. Local
  dev requires the ``pgvector/pgvector:pg15`` image; vanilla
  ``postgres:15`` fails this migration. ``docs/STATUS.md``
  §"Local dev loop revival" is updated in the same commit so a
  fresh session picks the right image.
* ``scope_documents`` -- operator-curated baseline content per org.
  ``UNIQUE(org_id, title)`` is the idempotency key for
  ``tools/process_scope_document.py`` (delete-then-insert on
  re-registration).
* ``scope_chunks`` -- one row per semantic chunk. ``embedding`` is
  ``vector(1536)`` (OpenAI ``text-embedding-3-small`` dim).
  ``ON DELETE CASCADE`` from the document keeps the
  delete-then-insert path clean.
* ``scope_alerts`` -- one row per ``on_persisted`` evaluation.
  Carries the four extra columns (``stage`` / ``stage2_verdict`` /
  ``stage2_reason`` / ``matched_chunk_id``) ADR-0030 axis 6 picked
  over the brief's minimal shape, so operators can tune thresholds
  from the alerts table without re-querying.

RLS:

* ``scope_documents`` and ``scope_chunks`` follow the migration
  0005 pattern (``exchanges`` / ``events`` / ``tool_calls`` /
  ``audit_log``): ``ENABLE`` + ``FORCE`` RLS with
  ``_org_isolation`` and ``_admin_access`` policies. The plugin
  reads these through the request-scoped session that already
  carries ``app.org_id`` from CP6's auth middleware.
* ``scope_alerts`` follows the migration 0007 ``plugin_analytics``
  pattern: no RLS. Writes from plugin code that knows the correct
  ``org_id`` (``ctx.org_id``); reads from operator tooling.

GRANT on ``llm_tracker_app``: SELECT / INSERT / UPDATE / DELETE on
all three tables (RLS-off ``scope_alerts`` still needs row CRUD).

ANN index: not created in MVP. ADR-0030 §Q2 defers it until any
org's chunk count exceeds ~10k. The btree indexes here cover the
basic lookup paths; the cosine-distance ``ORDER BY`` does a linear
scan within an org's chunks.

Reversibility: downgrade drops policies, grants, indexes, and
tables in reverse order. The ``vector`` extension itself is left
in place -- mirrors 0009's stance on ``pg_cron``: dropping a
project-wide extension to revert a single migration is the wrong
blast radius.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_scope_guard_tables"
down_revision: str | Sequence[str] | None = "0009_retention_deletion_job"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RLS_TABLES = ("scope_documents", "scope_chunks")
_GRANT_TABLES = "scope_documents, scope_chunks, scope_alerts"


# Each statement is dispatched separately so the asyncpg driver, which
# refuses multi-statement prepared inputs ("cannot insert multiple
# commands into a prepared statement"), accepts them. Same transactional
# semantics either way -- alembic wraps the whole `upgrade()` body in
# one DDL transaction.
_UPGRADE_STATEMENTS: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS vector",
    """
    CREATE TABLE scope_documents (
        id          uuid PRIMARY KEY,
        org_id      uuid NOT NULL REFERENCES orgs(id),
        title       text NOT NULL,
        content     text NOT NULL,
        created_at  timestamptz NOT NULL DEFAULT now(),
        updated_at  timestamptz NOT NULL DEFAULT now(),
        UNIQUE (org_id, title)
    )
    """,
    "CREATE INDEX idx_scope_documents_org ON scope_documents(org_id)",
    """
    CREATE TABLE scope_chunks (
        id           uuid PRIMARY KEY,
        document_id  uuid NOT NULL REFERENCES scope_documents(id) ON DELETE CASCADE,
        org_id       uuid NOT NULL REFERENCES orgs(id),
        chunk_index  int  NOT NULL,
        content      text NOT NULL,
        embedding    vector(1536) NOT NULL,
        created_at   timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX idx_scope_chunks_org ON scope_chunks(org_id)",
    "CREATE INDEX idx_scope_chunks_document ON scope_chunks(document_id)",
    """
    CREATE TABLE scope_alerts (
        id                uuid PRIMARY KEY,
        exchange_id       text NOT NULL,
        org_id            uuid NOT NULL REFERENCES orgs(id),
        stage             text NOT NULL,
        flagged           bool NOT NULL,
        max_similarity    float NOT NULL,
        matched_chunk_id  uuid NULL REFERENCES scope_chunks(id),
        stage2_verdict    text NULL,
        stage2_reason     text NULL,
        created_at        timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE INDEX idx_scope_alerts_org ON scope_alerts(org_id)",
    "CREATE INDEX idx_scope_alerts_flagged ON scope_alerts(org_id, flagged) WHERE flagged",
    "CREATE INDEX idx_scope_alerts_created ON scope_alerts(created_at)",
)


def upgrade() -> None:
    for stmt in _UPGRADE_STATEMENTS:
        op.execute(stmt)

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_GRANT_TABLES} TO llm_tracker_app")

    for table in _RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # NULLIF guards the Postgres GUC quirk where a previously-set
        # custom setting returns '' (not NULL) in later transactions
        # where it is unset -- without it ''::uuid would raise instead
        # of evaluating to NULL (default-closed semantics).
        op.execute(
            f"CREATE POLICY {table}_org_isolation ON {table} "
            "AS PERMISSIVE FOR ALL TO PUBLIC "
            "USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid) "
            "WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)"
        )
        op.execute(
            f"CREATE POLICY {table}_admin_access ON {table} "
            "AS PERMISSIVE FOR ALL TO PUBLIC "
            "USING (NULLIF(current_setting('app.role', true), '') = 'admin') "
            "WITH CHECK (NULLIF(current_setting('app.role', true), '') = 'admin')"
        )


def downgrade() -> None:
    for table in reversed(_RLS_TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_admin_access ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {_GRANT_TABLES} FROM llm_tracker_app")

    op.execute("DROP INDEX IF EXISTS idx_scope_alerts_created")
    op.execute("DROP INDEX IF EXISTS idx_scope_alerts_flagged")
    op.execute("DROP INDEX IF EXISTS idx_scope_alerts_org")
    op.execute("DROP TABLE IF EXISTS scope_alerts")

    op.execute("DROP INDEX IF EXISTS idx_scope_chunks_document")
    op.execute("DROP INDEX IF EXISTS idx_scope_chunks_org")
    op.execute("DROP TABLE IF EXISTS scope_chunks")

    op.execute("DROP INDEX IF EXISTS idx_scope_documents_org")
    op.execute("DROP TABLE IF EXISTS scope_documents")
    # Leave `vector` extension in place; mirrors 0009's stance on pg_cron.
