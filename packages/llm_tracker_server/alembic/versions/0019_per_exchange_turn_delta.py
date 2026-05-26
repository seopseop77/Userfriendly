"""ADR-0038 — per-exchange turn delta replaces conversation_messages

Revision ID: 0019_per_exchange_turn_delta
Revises: 0018_participant_registrations
Create Date: 2026-05-26

Adds three new columns on plugin_analytics (role, request_jsonb,
system_prompt_jsonb), tightens response_json to jsonb and renames it
to response_jsonb, backfills request_jsonb + role from
conversation_messages, then drops turn_kind, n_messages_at_request,
the plugin_analytics_with_messages helper view, and the
conversation_messages table.

system_prompt_jsonb is NOT backfilled — raw request bodies were
never retained anywhere. Historic rows keep NULL; forward writes
from this deploy onward populate the column via the variation
tracker in `AnalyticsSink._resolve_system`.

Backfill role mapping (ADR-0037 → ADR-0038):
  user_input  → user_input
  title_gen   → title_gen
  assistant + content_jsonb contains tool_result → tool_result
  assistant otherwise (string sub-prompts, wrapper-only lists) → sidecar
  system_prompt is never at msg_index = n_messages_at_request - 1
  (the split rule places it at msg_index=0).

Downgrade is best-effort: it re-creates `conversation_messages` and
the old plugin_analytics columns empty (historic content cannot be
restored — request_jsonb is now the only retained shape). Not
expected to run in production.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

revision: str = "0019_per_exchange_turn_delta"
down_revision: str | Sequence[str] | None = "0018_participant_registrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add the three new nullable columns.
    op.add_column(
        "plugin_analytics",
        sa.Column("role", sa.Text(), nullable=True),
    )
    op.add_column(
        "plugin_analytics",
        sa.Column("request_jsonb", JSONB(), nullable=True),
    )
    op.add_column(
        "plugin_analytics",
        sa.Column("system_prompt_jsonb", JSONB(), nullable=True),
    )

    # 2. response_json (text) → response_jsonb (jsonb).
    #    USING cast handles the stored raw-JSON strings; rows that
    #    are NULL or empty stay NULL/empty. The helper view depends
    #    on `pa.*` so we drop it first (it is recreated as part of
    #    the column-rename / drop sequence below — actually retired
    #    in step 4).
    op.execute("DROP VIEW IF EXISTS plugin_analytics_with_messages")
    op.execute(
        "ALTER TABLE plugin_analytics "
        "ALTER COLUMN response_json TYPE jsonb USING response_json::jsonb"
    )
    op.alter_column(
        "plugin_analytics",
        "response_json",
        new_column_name="response_jsonb",
    )

    # 3. Backfill request_jsonb + role from conversation_messages.
    #    The row at msg_index = n_messages_at_request - 1 is the
    #    API messages[-1] for that exchange. content_jsonb is
    #    already Rule-B-normalised and wrapper-free (ADR-0037 split
    #    placed wrappers at msg_index=0 in a separate system_prompt
    #    row), so it can be copied verbatim into request_jsonb.
    op.execute(
        """
        UPDATE plugin_analytics pa
        SET request_jsonb = cm.content_jsonb,
            role = CASE cm.role
                WHEN 'user_input' THEN 'user_input'
                WHEN 'title_gen'  THEN 'title_gen'
                WHEN 'assistant'  THEN
                    CASE
                        WHEN jsonb_typeof(cm.content_jsonb) = 'array'
                             AND cm.content_jsonb @> '[{"type":"tool_result"}]'::jsonb
                            THEN 'tool_result'
                        ELSE 'sidecar'
                    END
                ELSE cm.role
            END
        FROM conversation_messages cm
        WHERE cm.conversation_id = pa.conversation_id
          AND cm.msg_index = pa.n_messages_at_request - 1
        """
    )

    # 4. Drop the retired surfaces.
    op.drop_column("plugin_analytics", "turn_kind")
    op.drop_column("plugin_analytics", "n_messages_at_request")
    op.drop_index(
        "idx_conversation_messages_org_conv",
        table_name="conversation_messages",
    )
    op.drop_table("conversation_messages")


def downgrade() -> None:
    # Re-create conversation_messages empty (no data restoration —
    # request_jsonb is the only retained shape after upgrade()).
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
        sa.Column("turn_kind", sa.Text(), nullable=True),
    )
    op.add_column(
        "plugin_analytics",
        sa.Column("n_messages_at_request", sa.Integer(), nullable=True),
    )

    op.alter_column(
        "plugin_analytics",
        "response_jsonb",
        new_column_name="response_json",
    )
    op.execute(
        "ALTER TABLE plugin_analytics "
        "ALTER COLUMN response_json TYPE text USING response_json::text"
    )

    op.drop_column("plugin_analytics", "system_prompt_jsonb")
    op.drop_column("plugin_analytics", "request_jsonb")
    op.drop_column("plugin_analytics", "role")
