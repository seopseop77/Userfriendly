"""drop exchanges.tool_call_count — derive at query time instead

Revision ID: 0008_drop_tool_call_count
Revises: 0007_plugin_analytics
Create Date: 2026-05-17

ADR-0028 §Non-goals already named the policy ("stays at 0; deriving
the count from response_json.content is one SQL expression"); ADR-0027
§Open questions left the column's fate as a queued decision. The
2026-05-17 production-smoke session settled it: drop the column.

The column was never populated past the `0` placeholder seeded by
CP9. The operator query that motivated keeping it is one
``jsonb_path_query`` away on `plugin_analytics.response_json`:

    SELECT jsonb_array_length(
        response_json::jsonb -> 'content'
    ) FILTER (WHERE ...)
    FROM public.plugin_analytics ...

The `public.plugin_analytics.tool_call_count` column is a separate
plugin-owned surface and stays untouched — this migration narrows to
the server-core `public.exchanges` table only.

Reversible: the downgrade re-adds the column with the same
``NOT NULL DEFAULT 0`` shape the original 0001 migration used.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_drop_tool_call_count"
down_revision = "0007_plugin_analytics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("exchanges", "tool_call_count")


def downgrade() -> None:
    op.add_column(
        "exchanges",
        sa.Column(
            "tool_call_count",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
