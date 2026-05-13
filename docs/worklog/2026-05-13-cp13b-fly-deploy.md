# 2026-05-13 · Phase 3c CP13-b — Fly.io + Supabase first deploy

**Author**: Claude Code
**Session trigger**: User ran `fly deploy` against the just-merged CP13-a
`fly.toml`, hit two release-command failures in sequence, and asked
Claude Code to diagnose and fix.
**Related docs**: `docs/deploy.md` (CP13-b runbook), ADR-0017, ADR-0022,
prior worklog `docs/worklog/2026-05-11-phase3c-plan.md`.

## Interpretation

CP13-b is operator-executed by design (per `docs/STATUS.md` §"Next single
step" at the time of CP13-a close). The operator hit two failures during
the first deploy attempt against real Fly.io + Supabase:

1. `release_command` failed with `DuplicateTableError: relation
   "exchanges" already exists`. The Supabase project had previously been
   used by the (now-closed) `llm_tracker_plugin_supabase_sink`
   workstream, which had created `public.exchanges` with a *completely
   different* schema (`exchange_id` PK, `ts_started_ms`, `mode`, `source`,
   `request_text`/`response_text`/`raw_request`/`raw_response`). The new
   server's `0001_initial_schema` collided immediately.
2. After the migration-table conflict was cleared and a second deploy
   succeeded (all five migrations applied, both app Machines healthy on
   `/healthz`), follow-up commands like `alembic current` failed with
   `asyncpg.exceptions.DuplicatePreparedStatementError: prepared
   statement "__asyncpg_stmt_1__" already exists` — a known
   incompatibility between asyncpg's prepared-statement cache and
   Supabase's pgbouncer transaction-mode pooler. The hint in the error
   message itself ("pgbouncer with pool_mode 'transaction' does not
   support prepared statements properly") pointed straight at it.

The fix-and-deploy scope was explicitly authorised by the user
("그냥 supabase mcp 이용해서 너가 적절히 수정하고 deploy까지 해줘") —
Claude Code to fix the engine, drop the stale Supabase table via MCP,
and re-deploy.

## What was done

- Dropped `public.exchanges` (7 rows, stale `supabase_sink` schema) on
  Supabase via MCP `execute_sql` after confirming via
  `information_schema` that it was the only stale object (no
  `alembic_version`, no `audit_log_reject_modify` function from a
  half-applied migration). First `fly deploy` after the drop succeeded;
  all five migrations applied (`0001_initial_schema` →
  `0005_rls_policies`); two app Machines launched in `nrt`; `/healthz`
  returned `HTTP 200`.
- Identified the asyncpg + pgbouncer transaction-mode conflict via the
  error message's explicit hint. Verified the symptom was asyncpg's own
  cache (`__asyncpg_stmt_N__` naming) rather than SQLAlchemy's compiled
  cache.
- Modified `packages/llm_tracker_server/src/llm_tracker_server/storage/engine.py`
  — `make_engine()` now passes `connect_args={"statement_cache_size":
  0}` to `create_async_engine`. Disables asyncpg's prepared-statement
  cache, which pgbouncer transaction-mode pooling cannot preserve. No-op
  against direct PG (the local Docker test fixture). One-line `# why`
  comment in the body. Single point of effect, since all callers
  (`app.py:57`, `cli/main.py:50`, `tests/conftest.py:89`) go through
  `make_engine` (commit 3050bcc).
- Modified `packages/llm_tracker_server/alembic/env.py` — same
  `connect_args` change on the migration-runner engine. Migrations
  happened to pass in single-transaction mode without this on the first
  successful run, but `alembic current` (which opens a separate session)
  failed without it; future re-runs need this for robustness (commit
  TBD).
- One false-start: initial attempt also passed `prepared_statement_cache_size=0`
  as a top-level `create_async_engine` kwarg — invalid argument for the
  asyncpg dialect (`TypeError: Invalid argument(s)
  'prepared_statement_cache_size' sent to create_engine()`, deploy
  release-command exited 1). Reverted to `connect_args`-only; the
  SQLAlchemy compiled prepared-statement cache is a URL-level parameter,
  not a top-level engine kwarg, and the *root-cause* error was asyncpg's
  own cache — disabling that alone is sufficient (verified below).
- Re-deployed; release_command succeeded; both app Machines updated via
  rolling deploy with the `/healthz` check passing on both.

## Decisions

- **Same Supabase project, drop the stale plugin table; do not spin up
  a new project**. The old `supabase_sink` plugin workstream is closed
  (per `docs/STATUS.md:250` and ADR-0007 superseded by ADR-0017), so its
  7 rows are not load-bearing. If the plugin is ever revived under the
  post-ADR-0017 framing, that checkpoint can choose a different target
  table/schema (or a different project) — the plugin's `schema.sql` is
  checked in for reproducibility. Saves one Supabase project slot + one
  set of secrets.
- **Disable asyncpg cache at the engine layer, not via URL query
  parameter**. The `connect_args` path is portable across all
  `make_engine` callers (server, CLI, tests, alembic env). The URL-query
  path would require touching the `LLMTRACK_DATABASE_URL` secret on
  every deploy environment and would not affect the test fixture's
  local-Docker URL.
- **Do not also disable the SQLAlchemy-level prepared-statement cache.**
  The reproducible error was asyncpg's `__asyncpg_stmt_N__`, not
  SQLAlchemy's `_sa_*`. Verified post-fix by hitting `/v1/messages`
  (without a token, so auth middleware runs and exits with 401) three
  times in a row — `HTTP 401` on each, stable across connection reuse.
  If a SQLAlchemy-cache-driven duplicate surfaces later, the fix is
  `?prepared_statement_cache_size=0` on the URL.
- **Did not auto-apply the Supabase RLS advisor remediation SQL.** The
  advisor flagged `public.alembic_version`, `public.orgs`,
  `public.api_tokens` as RLS-disabled. `alembic_version` is
  alembic-internal (no app data); `orgs` + `api_tokens` are
  *intentionally* RLS-disabled per the 0005 docstring ("tenancy
  substrate, no RLS, but the role still needs row-level CRUD"). The
  advisor's concern is Supabase's anon/authenticated PostgREST roles,
  which this server does not use. But a follow-up
  `REVOKE ... FROM anon, authenticated` (or RLS + restrictive policy)
  is a defense-in-depth win and is owed as a separate CP/ADR. Surfaced
  to the operator; left untouched.

## Verification

```
$ fly ssh console -C "alembic current"
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
0005_rls_policies (head)

$ curl -s -i https://llm-tracker-server.fly.dev/healthz | head -3
HTTP/2 200
date: Wed, 13 May 2026 03:14:02 GMT
server: Fly/8829d9560 (2026-05-12)
{"status":"ok","version":"0.0.1"}

$ for i in 1 2 3; do curl -s -o /dev/null -w "HTTP %{http_code}\n" \
    -X POST https://llm-tracker-server.fly.dev/v1/messages \
    -H "Content-Type: application/json" \
    -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'; done
HTTP 401
HTTP 401
HTTP 401
```

Supabase schema state (via MCP `list_tables`, post-deploy):

```
public.alembic_version  (1 row, version_num = 0005_rls_policies)
public.exchanges        (RLS on,  0 rows)
public.events           (RLS on,  0 rows)
public.tool_calls       (RLS on,  0 rows)
public.audit_log        (RLS on,  0 rows)
public.orgs             (RLS off — substrate, by design 0005)
public.api_tokens       (RLS off — substrate, by design 0005)
```

Fly Machines (post-rolling deploy):

```
- 9080d15ec93278 [app]  region=nrt  state=started  /healthz=passing
- 9185de3db97108 [app]  region=nrt  state=started  /healthz=passing
- release_command machines (148ee23ef4d348 then e28627e2b36918)
  both ran alembic and exited 0
```

## What's left / known limits

- **CP14 — operator-only end-to-end smoke**. The deployed server has not
  yet been hit with a real `/v1/messages` request bearing a valid
  Anthropic API key; that is CP14's job. The bearer token has not yet
  been minted (`fly ssh console -C "llm-tracker-server tokens issue
  --org demo"` is owed).
- **Auth-middleware path was tested only without a token (401)**. Once
  CP14 mints a real token, the prepared-statement-cache fix should be
  re-verified under that load — the auth middleware reads `api_tokens`
  on every request, which is the exact path that would have hit the
  original error.
- **Supabase anon-key exposure on `orgs` + `api_tokens` is not
  mitigated**. The server does not use PostgREST, so this is not a
  current-build vulnerability — but it is a future foot-gun if anyone
  ever ships the Supabase anon key in a client. Owed: a small follow-up
  CP that either `REVOKE`s anon/authenticated from these tables, or
  wraps them in RLS + an `llm_tracker_app`-only policy.
- **`docs/deploy.md` Troubleshooting** did not anticipate either failure
  encountered in this session. See §Suggestions.

## Handoff

CP13-b is **closed**. Server live at `https://llm-tracker-server.fly.dev/`,
alembic head = `0005_rls_policies`, RLS on for the four user-data
tables, two `nrt` Machines passing the `/healthz` check, asyncpg+pgbouncer
compat shipped.

**Next single step**: **CP14 — operator-only end-to-end smoke**. Mint
the demo bearer token (`fly ssh console -C "llm-tracker-server tokens
issue --org demo"`), capture the once-shown token, send one real
`/v1/messages` request through the deployed server with a valid
Anthropic `x-api-key`, and verify (a) the response stream returns
unchanged, (b) one row lands in `public.exchanges` scoped to the demo
org, and (c) `fly logs` shows no traceback.

## Suggestions (untouched)

- **`docs/deploy.md` Troubleshooting** owes two new entries: (i)
  `DuplicateTableError` on first deploy against a previously-used
  Supabase project (drop the stale tables — operator-only, since the
  server cannot know which DB it is colliding with); (ii)
  `DuplicatePreparedStatementError` during follow-up commands — this
  commit fixes the runtime side, but the troubleshooting note still
  helps operators who hit the symptom before pulling and rebuilding.
- **Restrict Supabase anon/authenticated from `orgs` + `api_tokens`**
  as a defense-in-depth CP. Either `REVOKE SELECT, INSERT, UPDATE,
  DELETE FROM anon, authenticated` or RLS-with-`llm_tracker_app`-only
  policy. Either way, no server-side code change needed.
- **`docs/decisions/0022-deployment-platform-fly-supabase.md`** owes a
  one-line "pgbouncer transaction-mode requires `statement_cache_size=0`
  on the asyncpg driver" footnote so future onlookers don't rediscover
  this.
