"""install audit_log append-only triggers (ADR-0006)

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-06

"""

from collections.abc import Sequence

from alembic import op
from llm_tracker.storage.models import (
    AUDIT_LOG_NO_DELETE_DDL,
    AUDIT_LOG_NO_UPDATE_DDL,
)

revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(AUDIT_LOG_NO_UPDATE_DDL)
    op.execute(AUDIT_LOG_NO_DELETE_DDL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
