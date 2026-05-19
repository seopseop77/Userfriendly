"""conversation_messages — dedup plugin_analytics.messages_json (Candidate 1)

Revision ID: 0015_conversation_messages
Revises: 0014_analytics_turn_class
Create Date: 2026-05-19

Replaces `plugin_analytics.messages_json` with a normalised row-per-message
table keyed by `(conversation_id, msg_index)`. Eliminates the
quadratic-on-conversation-length duplication where every tool-continuation
row re-stored the entire prior history. STRESS run measured 4.8x savings
on a 23-message conversation; the factor grows with chain length.

Plumbing:

* `conversation_messages` — primary-key `(conversation_id, msg_index)` so
  same-index re-writes from stream retries silently keep the first
  arrival (`ON CONFLICT DO NOTHING` in the plugin).
* `plugin_analytics.n_messages_at_request` (int) — replaces
  `messages_json`. The reconstruct path joins
  `conversation_messages` on `conversation_id` filtered by
  `msg_index < n_messages_at_request`.
* `plugin_analytics_with_messages` — convenience view that rebuilds the
  original `messages` array shape for any consumer that wanted it.

RLS posture: `conversation_messages` mirrors `plugin_analytics` — no RLS;
operator tooling only, same as the 0007 docstring precedent. Downstream
analytics queries this table directly without per-request session
binding.

Order of operations matters:
1. Create table + add `n_messages_at_request`.
2. **Backfill happens out-of-band** via a Python script that imports
   `canonical_message` (see worklog §5 — keeps the normalization rule
   single-sourced in Python). This migration does NOT do the data move.
3. Drop `messages_json` is run as a follow-up step, **after** the
   backfill is verified live. We deliberately split the column drop
   out of this migration so an interrupted backfill cannot leave the
   row pointer (`n_messages_at_request`) without the source data.

   The next session executes the drop via Supabase MCP `execute_sql`
   once verification §6 V1-V5 is green; the column-drop SQL is
   captured in the worklog handoff.

Downgrade: re-add `messages_json` as nullable text (no data to restore
— historic content lives in `conversation_messages` only after the
backfill), drop the view + table + column. Production is not expected
to downgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision: str = "0015_conversation_messages"
down_revision: str | Sequence[str] | None = "0014_analytics_turn_class"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_messages",
        sa.Column("conversation_id", sa.Text(), nullable=False),
        sa.Column("msg_index", sa.Integer(), nullable=False),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content_jsonb", JSONB(), nullable=False),
        sa.Column(
            "first_seen_at",
            TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("conversation_id", "msg_index"),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"]),
    )
    op.create_index(
        "idx_conversation_messages_org_conv",
        "conversation_messages",
        ["org_id", "conversation_id"],
    )

    op.add_column(
        "plugin_analytics",
        sa.Column("n_messages_at_request", sa.Integer(), nullable=True),
    )

    # Helper view — reconstructs the `messages` array shape from the
    # dedup table. Filtered by `msg_index < n_messages_at_request` so a
    # row that arrived mid-conversation sees only the messages that
    # existed *at the time of its request*.
    op.execute(
        """
        CREATE VIEW plugin_analytics_with_messages AS
        SELECT
            pa.*,
            (
                SELECT jsonb_agg(
                    jsonb_build_object(
                        'role', cm.role,
                        'content', cm.content_jsonb
                    )
                    ORDER BY cm.msg_index
                )
                FROM conversation_messages cm
                WHERE cm.conversation_id = pa.conversation_id
                  AND cm.msg_index < pa.n_messages_at_request
            ) AS messages_jsonb
        FROM plugin_analytics pa
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS plugin_analytics_with_messages")
    op.drop_column("plugin_analytics", "n_messages_at_request")
    op.drop_index(
        "idx_conversation_messages_org_conv",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")
    # Re-add messages_json as nullable text — no data to backfill on
    # downgrade. Production is not expected to roll back.
    op.add_column(
        "plugin_analytics",
        sa.Column("messages_json", sa.Text(), nullable=True),
    )
