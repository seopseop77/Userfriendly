"""scope_chunks.embedding vector(1536) → vector(768) (ADR-0031)

Revision ID: 0012_scope_chunks_embedding_dim_768
Revises: 0011_scope_alerts_retention
Create Date: 2026-05-18

ADR-0031 swaps the scope_guard embedding provider from OpenAI
``text-embedding-3-small`` (1536d) to Gemini ``text-embedding-004``
(768d). pgvector does not permit ``ALTER COLUMN … TYPE vector(N)``
across dimensions, so the column is dropped and re-added.

**Safe to apply ONLY against an empty ``scope_chunks`` table.** ADR-0031
records the operator confirmation that no production data exists at
ADR-acceptance time (2026-05-18). Re-running this migration against
a populated table would erase every chunk's embedding; if a future
operator hits that state, the correct path is to first re-embed the
corpus under the target dimension, then run a tailored migration that
copies values across — not to re-use this drop-and-add.

NOT NULL is preserved across the drop/add so the column contract
matches migration 0010. The btree indexes on ``scope_chunks`` reference
``org_id`` / ``document_id`` (not ``embedding``), so they survive the
column drop without recreation.

RLS policies on ``scope_chunks`` and the GRANTs on the
``llm_tracker_app`` role likewise apply at the table level and are not
disturbed by the column swap.

Reversibility: downgrade drops the 768d column and re-adds a 1536d
column. Equally destructive of any populated data — by design,
mirroring upgrade.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012_scope_chunks_embedding_dim_768"
down_revision: str | Sequence[str] | None = "0011_scope_alerts_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Statements dispatched individually for the same asyncpg "no
# multi-statement prepared input" reason migration 0010 documents.
_UPGRADE_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE scope_chunks DROP COLUMN embedding",
    "ALTER TABLE scope_chunks ADD COLUMN embedding vector(768) NOT NULL",
)

_DOWNGRADE_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE scope_chunks DROP COLUMN embedding",
    "ALTER TABLE scope_chunks ADD COLUMN embedding vector(1536) NOT NULL",
)


def upgrade() -> None:
    for stmt in _UPGRADE_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in _DOWNGRADE_STATEMENTS:
        op.execute(stmt)
