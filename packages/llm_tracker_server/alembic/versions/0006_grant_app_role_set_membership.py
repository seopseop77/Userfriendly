"""Grant SET membership on llm_tracker_app to deploy user (CP14 follow-up)

Revision ID: 0006_grant_app_role_set
Revises: 0005_rls_policies
Create Date: 2026-05-13

Production-deploy gap discovered in CP14: PG16+ split role membership
into three orthogonal options -- INHERIT (gets the privileges of the
role), SET (can `SET ROLE`), and ADMIN (can grant the role on). Supabase
auto-grants `postgres` membership of newly created roles via
INHERIT-only; the `SET` flag is not set.

The auth middleware's `SET LOCAL ROLE llm_tracker_app` (the contract
0005's RLS policies rely on, since `FORCE ROW LEVEL SECURITY` alone
does not constrain a superuser session) therefore failed in production
with `permission denied to set role "llm_tracker_app"` -- even though
`pg_auth_members` showed `postgres` was a member. The legacy
PG15-and-earlier coupling of "membership implies SET ROLE" no longer
holds.

Fix: explicitly grant `llm_tracker_app` to whoever runs migrations
(`CURRENT_USER`) with the `SET` flag.

PG version split: the `WITH SET TRUE` syntax is PG16+ only. On PG15
and earlier, membership implies SET ROLE capability unconditionally,
so the plain `GRANT role TO user` form is sufficient (and the
`WITH SET ...` qualifier is a syntax error). The migration runs a
server-version check via `server_version_num` and emits the form the
running server accepts. This keeps the local docker test fixture
(`postgres:15`) green while still doing the right thing on Supabase
(PG16+).

The migration is idempotent on PG16+ (re-issuing GRANT upserts the
option row) and effectively idempotent on PG15 (the second grant is
a no-op). On the docker-default `cp2` superuser, the grant itself is
strictly cosmetic -- superusers bypass role membership checks for
`SET ROLE` -- but emitting it keeps state symmetric across
environments.

Why `CURRENT_USER` and not a hardcoded `postgres`: keeps the migration
portable across environments where the deploy user might not be named
`postgres` (e.g. a future RDS deploy that connects as `app_admin`, or
a CI runner whose role name is generated). The migration owner is by
definition the right grantee -- they are the principal that the auth
middleware will later inherit via the same connection pool.

Downgrade on PG16+ revokes only the SET option, leaving the underlying
membership intact (Supabase's auto-grant survives). On PG15 it drops
the membership we created (the only kind it had).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_grant_app_role_set"
down_revision: str | Sequence[str] | None = "0005_rls_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF current_setting('server_version_num')::int >= 160000 THEN "
        "EXECUTE 'GRANT llm_tracker_app TO CURRENT_USER WITH SET TRUE'; "
        "ELSE "
        "EXECUTE 'GRANT llm_tracker_app TO CURRENT_USER'; "
        "END IF; "
        "END $$"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF current_setting('server_version_num')::int >= 160000 THEN "
        "EXECUTE 'REVOKE SET OPTION FOR llm_tracker_app FROM CURRENT_USER'; "
        "ELSE "
        "EXECUTE 'REVOKE llm_tracker_app FROM CURRENT_USER'; "
        "END IF; "
        "END $$"
    )
