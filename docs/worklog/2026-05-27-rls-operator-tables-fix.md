# 2026-05-27 · RLS operator-tables migration (0020) fix

**Author**: Claude Code
**Session trigger**: User reported `claude-manage` started misbehaving after
"Supabase 테이블을 RLS로 바꾼" change. Asked to find the cause, then to roll
back the live DB and rewrite the migration.
**Related docs**: ADR-0018 (RLS posture), ADR-0020 (token axis), ADR-0030
§D8 (`scope_alerts` no-RLS), ADR-0033 (operator-only table posture),
migrations 0005 / 0010 (existing RLS pattern).

## Interpretation

The user committed migration `0020_enable_rls_operator_tables` (untracked,
local) that enabled RLS on six `public.*` tables with **no policies**, on
the assumption that the backend connects as `postgres` (which has
`BYPASSRLS`) and therefore is unaffected. They then deployed -- Fly's
`release_command = "alembic upgrade head"` (see root `fly.toml`) applied it
to production -- and `claude-manage` "started behaving weirdly".

Root cause: the *connection* is `postgres`, but the auth middleware
(`packages/llm_tracker_server/src/llm_tracker_server/auth/middleware.py:83`)
issues `SET LOCAL ROLE llm_tracker_app` on every request before doing
anything else. That role was created by migration 0005 as a plain NOLOGIN
role with no `BYPASSRLS`. Once 0020 turned RLS on for `api_tokens` with no
matching policy, the very next statement in the middleware --

```python
token_row = await lookup(session, plaintext)   # SELECT FROM api_tokens
```

-- silently returned zero rows, and the middleware short-circuited to
`403 "unknown or revoked token"`. Every authenticated request through
`claude-manage` failed the same way.

The other five tables in 0020 are not actively read under
`llm_tracker_app`:

* `orgs` is only mutated by the operator CLI (`postgres`, BYPASSRLS).
* `plugin_analytics` is written by `analytics_sink` via its own
  `create_async_engine(...)` -- no `SET LOCAL ROLE` (verified by grep
  across the sink package).
* `scope_alerts` is written by `scope_guard`, currently disabled in
  prod (`LLMTRACK_PLUGINS_DISABLED=scope_guard`, per STATUS.md).
* `participant_registrations` is written by the signup app via its own
  `postgres` engine.
* `alembic_version` is touched only by Alembic itself.

So `api_tokens` was the single live-fire breakage. The rewrite preserves
the advisor-clearing intent for five of the six tables and reverses the
inadvertent ADR-0030 §D8 violation on `scope_alerts` (see Decisions).

## What was done

- Rewrote
  `packages/llm_tracker_server/alembic/versions/0020_enable_rls_operator_tables.py`
  in place — mirrors the 0005 / 0010 pattern (enable RLS *and* attach
  the policies each access path actually needs). (commit c4e695d)
- Created this worklog. (commit c4e695d)
- Updated `packages/llm_tracker_server/alembic/versions/0018_participant_registrations.py`
  docstring to match the new 0020 behavior (was already staged by the
  user; folded into the same commit). (commit c4e695d)
- Applied the rollback + reapply SQL block live via Supabase MCP
  `execute_sql`. `alembic_version` left pinned at
  `0020_enable_rls_operator_tables` so the next `fly deploy` sees no
  pending migrations.

## Decisions

- **api_tokens gets `FOR SELECT TO llm_tracker_app USING (true)`, not an
  org-filtered policy.** The middleware's lookup happens *before* org
  binding (chicken-and-egg: the token is the thing that resolves the
  org). The SHA-256 hash is the actual secret -- if you have it, you've
  authenticated -- so an org filter would be useless gatekeeping. Writes
  (INSERT/UPDATE/DELETE) stay policy-less; only `postgres` (BYPASSRLS),
  i.e. the operator CLI, can mutate the table. This is the same
  least-privilege shape as the existing CP4 tables, just specialised for
  the auth-bootstrap table.
- **`scope_alerts` removed from the migration.** ADR-0030 §D8 fixes it
  as RLS-off and the plugin code carries an explicit `(no RLS --
  migration 0010 §D8)` comment at the insert site. The original 0020
  accidentally reversed that decision. Reversing an ADR needs its own
  ADR; out of scope for a "fix the breakage" task. Side-effect: the
  Supabase advisor warning for `scope_alerts` stays, accepted as a
  documented exception.
- **`plugin_analytics` gets the full org_isolation + admin_access pair
  (matching 0005), even though analytics_sink currently uses
  `postgres`.** Future-proofing: a sink rewrite that picks up the
  per-request session shouldn't silently start returning zero rows. The
  policies cost nothing today and prevent a class of future regression.
- **`participant_registrations` and `alembic_version` get RLS-on with no
  policies.** Both are operator-only: `postgres` BYPASSRLS handles all
  legitimate access, and PostgREST sees zero rows for `anon` /
  `authenticated` (no policy matches → default deny). Right shape for
  "operator-only table" per ADR-0033.

## Verification

Local code/lint/test:

```
$ .venv/bin/python3.12 -m ruff check packages/llm_tracker_server/alembic/versions/0020_enable_rls_operator_tables.py
All checks passed!

$ .venv/bin/python3.12 -m ruff format packages/llm_tracker_server/alembic/versions/0020_enable_rls_operator_tables.py
1 file reformatted

$ cd packages/llm_tracker_server && ../../.venv/bin/python3.12 -c "
from alembic.script import ScriptDirectory; from alembic.config import Config
sd = ScriptDirectory.from_config(Config('alembic.ini'))
print('heads:', sd.get_heads())
"
heads: ['0020_enable_rls_operator_tables']

$ .venv/bin/python3.12 -m pytest packages/llm_tracker_server/tests -q --no-header -x
59 passed, 18 skipped in 5.71s
```

(The 18 skips are the `LLMTRACK_TEST_DATABASE_URL`-gated PG smoke tests.
No local PG configured in this session.)

Live verification (after applying the SQL below via Supabase MCP
`execute_sql`):

```
-- Live state before:
SELECT version_num FROM public.alembic_version;
  -> "0020_enable_rls_operator_tables"
SELECT relname, relrowsecurity, (...policies...) FROM pg_class ...;
  -> all six tables: RLS on, FORCE off, policies = []   (the broken state)

-- After applying the rollback + reapply transaction:
api_tokens                 rls=t  force=t  policy api_tokens_app_lookup (SELECT TO llm_tracker_app)
orgs                       rls=t  force=t  policy orgs_org_isolation (SELECT TO llm_tracker_app, app.org_id filter)
plugin_analytics           rls=t  force=t  policies org_isolation + admin_access (ALL TO PUBLIC)
participant_registrations  rls=t  force=f  policies []           (operator-only, intended)
alembic_version            rls=t  force=f  policies []           (operator-only, intended)
scope_alerts               rls=f  force=f  policies []           (ADR-0030 §D8 restored)
alembic_version.version_num = "0020_enable_rls_operator_tables"   (unchanged)

-- Auth-path proof: visibility under the proxy's runtime role.
SELECT count(*) FROM api_tokens;                  -> 2  (as postgres)
BEGIN; SET LOCAL ROLE llm_tracker_app;
SELECT count(*) FROM api_tokens;                  -> 2  (as llm_tracker_app, was 0 before fix)
ROLLBACK;
```

Supabase advisor after the change:
- `scope_alerts` ERROR `rls_disabled_in_public` — accepted (ADR-0030 §D8).
- `alembic_version` + `participant_registrations` INFO
  `rls_enabled_no_policy` — accepted (operator-only tables, postgres
  BYPASSRLS handles every legitimate access path).
- Two unrelated pre-existing warnings: `audit_log_reject_modify`
  `function_search_path_mutable`, and `vector` extension in `public`
  schema. Not touched by this work.

A live claude-manage smoke (`claude-manage` then a single prompt) is
the final end-to-end proof and is left to the operator.

## Live DB rollback + reapply

Production is in a partial state: 0020-original ran via Fly's
`release_command`, so `alembic_version = '0020_enable_rls_operator_tables'`
and the six tables have RLS on with no policies. The fix is one
transactional SQL block that (a) tears down 0020-original's partial state
(also clears `scope_alerts` per Decisions), (b) re-applies the new 0020,
and (c) leaves `alembic_version` at `0020_enable_rls_operator_tables` so
the next `fly deploy` is a no-op for migrations.

Apply via Supabase MCP `execute_sql` (operator-side, same path that was
used for the live ADR-0038 schema work). The whole thing wraps in a
single transaction so a failure leaves no half-state.

```sql
BEGIN;

-- (a) Tear down 0020-original. Idempotent -- safe to re-run.
ALTER TABLE public.api_tokens               DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.orgs                     DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.plugin_analytics         DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.scope_alerts             DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.participant_registrations DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.alembic_version          DISABLE ROW LEVEL SECURITY;

-- Defensive: drop any policies the original 0020 might have left behind
-- if it had been hand-amended. Safe no-ops if absent.
DROP POLICY IF EXISTS api_tokens_app_lookup           ON public.api_tokens;
DROP POLICY IF EXISTS orgs_org_isolation              ON public.orgs;
DROP POLICY IF EXISTS plugin_analytics_org_isolation  ON public.plugin_analytics;
DROP POLICY IF EXISTS plugin_analytics_admin_access   ON public.plugin_analytics;

-- (b) Re-apply 0020 (rewritten).
-- api_tokens: SELECT-only for the app role.
ALTER TABLE public.api_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_tokens FORCE ROW LEVEL SECURITY;
CREATE POLICY api_tokens_app_lookup ON public.api_tokens
  AS PERMISSIVE FOR SELECT TO llm_tracker_app USING (true);

-- orgs: SELECT filtered to the bound org.
ALTER TABLE public.orgs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.orgs FORCE ROW LEVEL SECURITY;
CREATE POLICY orgs_org_isolation ON public.orgs
  AS PERMISSIVE FOR SELECT TO llm_tracker_app
  USING (id = NULLIF(current_setting('app.org_id', true), '')::uuid);

-- plugin_analytics: full 0005-shape org isolation.
ALTER TABLE public.plugin_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plugin_analytics FORCE ROW LEVEL SECURITY;
CREATE POLICY plugin_analytics_org_isolation ON public.plugin_analytics
  AS PERMISSIVE FOR ALL TO PUBLIC
  USING      (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid)
  WITH CHECK (org_id = NULLIF(current_setting('app.org_id', true), '')::uuid);
CREATE POLICY plugin_analytics_admin_access ON public.plugin_analytics
  AS PERMISSIVE FOR ALL TO PUBLIC
  USING      (NULLIF(current_setting('app.role', true), '') = 'admin')
  WITH CHECK (NULLIF(current_setting('app.role', true), '') = 'admin');

-- Operator-only, RLS-on / policy-less.
ALTER TABLE public.alembic_version          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.participant_registrations ENABLE ROW LEVEL SECURITY;

-- (c) Pin alembic version. No-op if already there.
UPDATE public.alembic_version
SET    version_num = '0020_enable_rls_operator_tables'
WHERE  version_num <> '0020_enable_rls_operator_tables';

COMMIT;
```

After applying, smoke-test from a `claude-manage` instance:

```
$ claude-manage --dangerously-skip-permissions
# enter prompt, see normal response (not 503 / not "unknown token")
```

And rerun the Supabase advisor: the five rewritten tables should drop
off the "RLS disabled" list; `scope_alerts` remains as the documented
exception.

## What's left / known limits

- **Live claude-manage end-to-end smoke is operator-side.** The DB
  evidence above shows the auth lookup path works, but the
  through-the-wire proof needs a `claude-manage` invocation against
  the fly server.
- **`scope_alerts` ERROR advisor will persist** until ADR-0030 §D8
  is revisited. Same for the two operator-only INFO warnings.
- **No local migration-apply test.** `LLMTRACK_TEST_DATABASE_URL` is
  unset in this session. The migration is shape-checked (alembic
  graph head + revision metadata + ruff) and live-DB-verified by
  replaying the same statements; a fresh PG `alembic upgrade head`
  run was not done.

## Handoff

Live DB is at the target state; alembic_version is pinned at 0020 so
the next `fly deploy` will skip migrations cleanly. Operator smoke:
run `claude-manage --dangerously-skip-permissions` and confirm a
prompt round-trips with a 200 (not 403). Then the deferred ADR-0038
deploy track (pre-incident "next single step" per STATUS.md) resumes.
