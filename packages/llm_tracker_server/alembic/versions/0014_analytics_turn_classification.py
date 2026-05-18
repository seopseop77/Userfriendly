"""plugin_analytics — turn classification columns

Revision ID: 0014_analytics_turn_class
Revises: 0013_schema_cleanup
Create Date: 2026-05-19

Adds five columns the `analytics_sink` plugin populates per row so
that downstream queries can distinguish user-typed prompts from
Claude Code's internal sub-prompts and tool-result continuations,
and group exchanges into conversation / turn units without scanning
`messages_json`:

* `turn_kind TEXT` — one of `user_input_turn_start`,
  `tool_continuation`, `internal_subprompt`, `claude_manage_probe`.
  Derived from the shape of `messages[-1]` (content type + block
  prefix sniff). Schema does NOT enforce the vocabulary; rule changes
  stay backfillable from `messages_json`.
* `turn_seq INT` — 1 for `user_input_turn_start`, then 2, 3, ... for
  each `tool_continuation` of the same turn. NULL for
  `internal_subprompt` / `claude_manage_probe` (out-of-band calls).
* `slash_commands JSONB` — extracted from `<command-name>/foo</command-name>`
  blocks in the last user message (e.g. `["clear"]`, `["compact"]`).
  NULL when no slash command appears.
* `first_msg_hash TEXT` — SHA-256[:16] of the concatenated text of
  `messages[0]`'s content blocks. Stable for the entire conversation
  (the first message of a conversation is fixed by the API contract).
  The chain-lookup uses this to find prior exchanges of the same
  conversation.
* `conversation_id TEXT` — the `id` of the FIRST exchange of this
  conversation. Determined at write-time via a chain-lookup: find
  the most recent same-`first_msg_hash` row; if `n_messages > prev.n`
  inherit its `conversation_id`, else mint a new one (this exchange's
  own `id`). Handles the "identical first prompt typed twice"
  collision case the simple-hash design could not.

Index `(first_msg_hash, created_at DESC)` covers the per-write
chain lookup. Conversation-grouping reads use `conversation_id`
which gets its own index.

All five columns are nullable — the plugin populates them at INSERT
time but pre-existing rows stay NULL until backfilled (see
docs/worklog/2026-05-19-turn-classification.md for the backfill
script that walks rows in `created_at` order and applies the same
algorithm offline).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0014_analytics_turn_class"
down_revision: str | Sequence[str] | None = "0013_schema_cleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plugin_analytics", sa.Column("turn_kind", sa.Text(), nullable=True))
    op.add_column("plugin_analytics", sa.Column("turn_seq", sa.Integer(), nullable=True))
    op.add_column("plugin_analytics", sa.Column("slash_commands", JSONB(), nullable=True))
    op.add_column("plugin_analytics", sa.Column("first_msg_hash", sa.Text(), nullable=True))
    op.add_column("plugin_analytics", sa.Column("conversation_id", sa.Text(), nullable=True))

    op.create_index(
        "idx_plugin_analytics_first_msg_hash",
        "plugin_analytics",
        ["first_msg_hash", sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_plugin_analytics_conversation",
        "plugin_analytics",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_plugin_analytics_conversation", table_name="plugin_analytics")
    op.drop_index("idx_plugin_analytics_first_msg_hash", table_name="plugin_analytics")
    op.drop_column("plugin_analytics", "conversation_id")
    op.drop_column("plugin_analytics", "first_msg_hash")
    op.drop_column("plugin_analytics", "slash_commands")
    op.drop_column("plugin_analytics", "turn_seq")
    op.drop_column("plugin_analytics", "turn_kind")
