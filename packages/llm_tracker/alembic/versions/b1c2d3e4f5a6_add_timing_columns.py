"""add timing columns to exchanges

Revision ID: b1c2d3e4f5a6
Revises: 350b17be77ae
Create Date: 2026-05-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "350b17be77ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("exchanges", sa.Column("t_request_received_ms", sa.Integer(), nullable=True))
    op.add_column("exchanges", sa.Column("t_upstream_first_byte_ms", sa.Integer(), nullable=True))
    op.add_column("exchanges", sa.Column("t_client_first_byte_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("exchanges", "t_client_first_byte_ms")
    op.drop_column("exchanges", "t_upstream_first_byte_ms")
    op.drop_column("exchanges", "t_request_received_ms")
