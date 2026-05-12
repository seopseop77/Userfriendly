"""RLS policies on user-data tables (ADR-0018 enforcement)

Revision ID: 0005_rls_policies
Revises: 0004_org_id_on_user_data
Create Date: 2026-05-12

Defense-in-depth, second half. CP4 landed the column-level half
(`org_id NOT NULL REFERENCES orgs(id)` on the four user-data tables).
CP5 adds the visibility half: Row Level Security policies on the same
four tables, plus the non-superuser application role they need to
actually fire.

This migration:

1. Creates `llm_tracker_app` (NOLOGIN, non-superuser, no BYPASSRLS).
   Production deploys add LOGIN to it (or create a separate login
   user that inherits it). Tests run as the docker-default superuser
   `cp2` and issue `SET LOCAL ROLE llm_tracker_app` per session to
   drop their bypass-everything privilege -- without that, `FORCE ROW
   LEVEL SECURITY` alone is not enough because PostgreSQL superusers
   bypass RLS unconditionally.
2. Grants the role `USAGE` on `public` and CRUD on the six tables it
   needs to touch (the four user-data tables plus `orgs` and
   `api_tokens` -- the latter pair are tenancy substrate, no RLS, but
   the role still needs row-level CRUD).
3. For each of `exchanges`, `events`, `tool_calls`, `audit_log`:
   - `ENABLE ROW LEVEL SECURITY` -- RLS active for non-owner sessions.
   - `FORCE ROW LEVEL SECURITY`  -- belt-and-braces; covers a future
     deploy where the app role owns the tables.
   - Two PERMISSIVE policies, OR-combined per Postgres' default:
     a. `<table>_org_isolation` (FOR ALL) -- the per-request setting
        `app.org_id` (issued by CP6's auth middleware via SET LOCAL)
        must equal the row's `org_id` on both read and write paths.
     b. `<table>_admin_access` (FOR ALL) -- when `app.role = 'admin'`,
        the row's `org_id` need not match. Mirrors ADR-0018
        §"Enforcement": no service-role bypass; admin tooling
        surfaces through an explicit policy branch.

The `audit_log` append-only trigger (migration 0002) fires BEFORE
UPDATE/DELETE only, so its concern is orthogonal to RLS-on-INSERT.
An INSERT into `audit_log` whose `org_id` matches `app.org_id` (or
whose session has `app.role = 'admin'`) is accepted; the trigger
never sees INSERTs and so cannot conflict with the policy.

Per-request invocation (added by CP6's auth middleware):

    SET LOCAL ROLE llm_tracker_app;
    SET LOCAL app.org_id = '<uuid from validated token>';

Or, equivalently and parameter-safe:

    SELECT set_config('app.org_id', :org_id, true);

`current_setting(name, missing_ok=true)` returns NULL when the GUC is
unset, so an un-bound session sees zero rows -- failed auth defaults
closed by construction.

Supabase note (CP13 follow-up): managed Postgres providers may forbid
customer migrations from `CREATE ROLE`. When CP13 wires Supabase, the
role-creation block here is gated behind a `DO $$ IF NOT EXISTS` so
re-running against a Supabase project that pre-provisions
`llm_tracker_app` (via the dashboard / Fly secret bootstrap) is a
no-op. If Supabase forbids the role entirely, swap the target to
`authenticated` in a follow-up migration -- the policy bodies are
unchanged.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_rls_policies"
down_revision: str | Sequence[str] | None = "0004_org_id_on_user_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("exchanges", "events", "tool_calls", "audit_log")
GRANT_TABLES = "exchanges, events, tool_calls, audit_log, orgs, api_tokens"


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'llm_tracker_app') THEN "
        "CREATE ROLE llm_tracker_app NOLOGIN; "
        "END IF; "
        "END $$"
    )
    op.execute("GRANT USAGE ON SCHEMA public TO llm_tracker_app")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {GRANT_TABLES} TO llm_tracker_app")

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        # NULLIF(..., '') guards against the Postgres quirk where once a
        # custom GUC has been set in any earlier transaction (LOCAL or
        # SESSION), `current_setting(name, true)` returns '' rather than
        # NULL in later transactions where it is unset. Without the
        # NULLIF, that '' would feed `''::uuid` and raise
        # `invalid input syntax for type uuid` instead of evaluating to
        # NULL (which is what default-closed semantics need).
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
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {table}_admin_access ON {table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_org_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute(f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {GRANT_TABLES} FROM llm_tracker_app")
    op.execute("REVOKE USAGE ON SCHEMA public FROM llm_tracker_app")
    op.execute("DROP ROLE IF EXISTS llm_tracker_app")
