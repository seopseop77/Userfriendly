"""Enable RLS on operator-side public tables (Supabase advisory)

Revision ID: 0020_enable_rls_operator_tables
Revises: 0019_per_exchange_turn_delta
Create Date: 2026-05-27

Supabase's security advisor flagged five tables in the ``public``
schema with Row Level Security disabled. PostgREST exposes every
``public`` table as a REST endpoint reachable with the project's
``anon`` key, so an RLS-disabled table is effectively world-readable
(and writable) to anyone who learns that key.

This project never talks to the database through PostgREST. The
operator-side server (``llm_tracker_server``) connects as ``postgres``
over a direct PostgreSQL URL, but the request-scoped sessions run
``SET LOCAL ROLE llm_tracker_app`` (see ``auth.middleware``) and that
role does **not** carry ``BYPASSRLS`` (0005 created it as a plain
NOLOGIN role). So we cannot simply "enable RLS with no policies": the
proxy's token lookup is the first thing that would silently return
zero rows.

The fix is to mirror the 0005 / 0010 pattern: enable RLS *and* attach
the policies each access path actually needs.

Per-table treatment (read together with ADR-0018 / ADR-0033 /
ADR-0030 §D8):

* ``api_tokens`` — SELECT policy that allows ``llm_tracker_app`` to
  look up any row. The lookup is keyed on a SHA-256 of the plaintext
  bearer; knowing the hash is already proof of authentication, so an
  org filter would be useless gatekeeping. INSERT/UPDATE/DELETE stay
  policy-less, which means only ``postgres`` (BYPASSRLS) -- i.e. the
  operator CLI -- can mutate tokens.
* ``orgs`` — SELECT policy filtered on ``app.org_id``. The app role
  never has reason to read sibling-org rows. Writes again stay
  operator-only.
* ``plugin_analytics`` — full ``org_isolation`` + ``admin_access``
  pair, identical shape to 0005. ``analytics_sink`` currently writes
  as ``postgres`` (BYPASSRLS) so it is unaffected today, but the
  policies future-proof against a sink rewrite that uses the
  per-request session.
* ``participant_registrations`` — operator-only per ADR-0033. The
  signup app uses its own ``postgres`` AsyncEngine; no
  ``llm_tracker_app`` path reads or writes this table. RLS-on /
  no-policy is the right shape -- it blocks PostgREST without
  granting the app role anything.
* ``alembic_version`` — touched only by Alembic, which runs as
  ``postgres``. Same treatment as ``participant_registrations``.

``scope_alerts`` is **deliberately not** in this migration. ADR-0030
§D8 fixes it as RLS-off; reversing that requires its own ADR. The
advisor warning for ``scope_alerts`` is accepted as a documented
exception.

Downgrade drops the policies and disables RLS on all five tables.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_enable_rls_operator_tables"
down_revision: str | Sequence[str] | None = "0019_per_exchange_turn_delta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that get RLS-on with no app-role policies — operator-only
# access paths run as ``postgres`` (BYPASSRLS) so policy-less is the
# correct shape. PostgREST sees zero rows for ``anon`` /
# ``authenticated`` because no policy matches.
_RLS_NO_POLICY: tuple[str, ...] = (
    "alembic_version",
    "participant_registrations",
)


def upgrade() -> None:
    # --- api_tokens: SELECT-only for the app role ----------------------
    op.execute("ALTER TABLE public.api_tokens ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.api_tokens FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY api_tokens_app_lookup ON public.api_tokens "
        "AS PERMISSIVE FOR SELECT TO llm_tracker_app USING (true)"
    )

    # --- orgs: SELECT filtered to the bound org -------------------------
    op.execute("ALTER TABLE public.orgs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.orgs FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY orgs_org_isolation ON public.orgs "
        "AS PERMISSIVE FOR SELECT TO llm_tracker_app "
        "USING (id = NULLIF(current_setting('app.org_id', true), '')::uuid)"
    )

    # --- plugin_analytics: full 0005-shape org isolation ----------------
    op.execute("ALTER TABLE public.plugin_analytics ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.plugin_analytics FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY plugin_analytics_org_isolation ON public.plugin_analytics "
        "AS PERMISSIVE FOR ALL TO PUBLIC "
        "USING (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid) "
        "WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE POLICY plugin_analytics_admin_access ON public.plugin_analytics "
        "AS PERMISSIVE FOR ALL TO PUBLIC "
        "USING (NULLIF(current_setting('app.role', true), '') = 'admin') "
        "WITH CHECK (NULLIF(current_setting('app.role', true), '') = 'admin')"
    )

    # --- Operator-only, RLS-on / policy-less ---------------------------
    for table in _RLS_NO_POLICY:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(_RLS_NO_POLICY):
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS plugin_analytics_admin_access ON public.plugin_analytics")
    op.execute("DROP POLICY IF EXISTS plugin_analytics_org_isolation ON public.plugin_analytics")
    op.execute("ALTER TABLE public.plugin_analytics NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.plugin_analytics DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS orgs_org_isolation ON public.orgs")
    op.execute("ALTER TABLE public.orgs NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.orgs DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS api_tokens_app_lookup ON public.api_tokens")
    op.execute("ALTER TABLE public.api_tokens NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.api_tokens DISABLE ROW LEVEL SECURITY")
