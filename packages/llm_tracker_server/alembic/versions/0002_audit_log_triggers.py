"""audit_log append-only triggers (PostgreSQL, ADR-0006)

Revision ID: 0002_audit_log_triggers
Revises: 0001_initial_schema
Create Date: 2026-05-11

PostgreSQL port of the SQLite trigger pair shipped by the local-sidecar
migration `c2d3e4f5a6b7_audit_log_append_only_triggers`. SQLite's
`RAISE(ABORT, ...)` per-table form does not exist in PostgreSQL; we use
a single PL/pgSQL function bound to two `BEFORE` row-level triggers.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_audit_log_triggers"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AUDIT_LOG_REJECT_FN = """
CREATE OR REPLACE FUNCTION audit_log_reject_modify()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;
"""

AUDIT_LOG_NO_UPDATE_TRIGGER = """
CREATE TRIGGER audit_log_no_update
BEFORE UPDATE ON audit_log
FOR EACH ROW
EXECUTE FUNCTION audit_log_reject_modify();
"""

AUDIT_LOG_NO_DELETE_TRIGGER = """
CREATE TRIGGER audit_log_no_delete
BEFORE DELETE ON audit_log
FOR EACH ROW
EXECUTE FUNCTION audit_log_reject_modify();
"""


def upgrade() -> None:
    op.execute(AUDIT_LOG_REJECT_FN)
    op.execute(AUDIT_LOG_NO_UPDATE_TRIGGER)
    op.execute(AUDIT_LOG_NO_DELETE_TRIGGER)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete ON audit_log")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_reject_modify()")
