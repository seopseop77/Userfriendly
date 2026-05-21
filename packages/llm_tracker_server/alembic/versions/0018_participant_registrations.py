"""participant_registrations — write target for the signup app

Revision ID: 0018_participant_registrations
Revises: 0017_drop_exchanges_session_id
Create Date: 2026-05-21

The signup app (``packages/llm_tracker_signup``) lets research
participants register and receive an API token via a public HTML form
served from a separate Fly app. Each successful submission writes
three rows in one transaction: one ``orgs`` row (the per-participant
tenant), one ``api_tokens`` row (the bearer token), and one
``participant_registrations`` row capturing the contact form payload.

Schema mirrors the ``plugin_analytics`` (migration 0007) pattern:

* ``id`` UUID PK with ``gen_random_uuid()`` server default (PG 13+).
* ``org_id`` FK to ``orgs(id)`` — one org per participant.
* ``token_hash`` FK to ``api_tokens(token_hash)`` — the active bearer
  token issued at registration time.
* ``email`` ``TEXT NOT NULL UNIQUE`` — the UNIQUE constraint is the
  authoritative duplicate guard. The signup app pre-checks for a
  friendlier 400 response, but a concurrent insert race still hits
  the constraint here.
* ``proposal_text`` nullable — the PDF upload is optional, and even
  when supplied the extracted text may be empty (image-only PDFs).
* ``research_description`` ``NOT NULL`` — comes from the form's
  required textarea.
* ``created_at`` server-default ``now()`` matching the ``orgs`` /
  ``api_tokens`` / ``plugin_analytics`` convention.

No RLS. Operator-only table — same posture as ``plugin_analytics``
(ADR-0033): the signup app uses its own ``AsyncEngine`` from a
separate Fly service and does not go through the proxy server's
per-request session binding. Adding RLS would require every connection
to ``SET LOCAL app.org_id`` for a table that no end-user surface ever
reads.

Indexed on ``email`` so the duplicate pre-check and any operator
``WHERE email = …`` queries stay fast.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

revision: str = "0018_participant_registrations"
down_revision: str | Sequence[str] | None = "0017_drop_exchanges_session_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "participant_registrations",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("org_id", UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("institution", sa.Text(), nullable=False),
        sa.Column("research_description", sa.Text(), nullable=False),
        sa.Column("proposal_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"]),
        sa.ForeignKeyConstraint(["token_hash"], ["api_tokens.token_hash"]),
        sa.UniqueConstraint("email", name="uq_participant_registrations_email"),
    )
    op.create_index(
        "idx_participant_registrations_email",
        "participant_registrations",
        ["email"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_participant_registrations_email",
        table_name="participant_registrations",
    )
    op.drop_table("participant_registrations")
