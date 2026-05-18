# Deploying the central server (Fly.io + Supabase)

This is the step-by-step guide the operator follows to ship the central
`llm_tracker_server` to Fly.io against a Supabase Postgres database. It
covers **Phase 3c CP13-b** (the user-executed half of CP13); CP13-a wrote
the in-repo artefacts (`Dockerfile`, `.dockerignore`, `fly.toml`).

Architecture decisions referenced below:

- ADR-0017 — central-server pivot.
- ADR-0018 — per-org RLS on PostgreSQL.
- ADR-0020 — per-org bearer token + Anthropic credential pass-through.
- ADR-0022 — Fly.io for the app, Supabase for Postgres.

Companion files:

- `Dockerfile` — multi-stage build that produces the runtime image.
- `fly.toml` — Fly.io app manifest (no secrets).
- `packages/llm_tracker_server/alembic*` — migrations shipped inside the
  image and run by the Fly release command.

---

## Prerequisites

Before starting CP13-b, the operator should have:

- [ ] **`flyctl` installed** — either of:
      - `brew install flyctl`, or
      - `curl -L https://fly.io/install.sh | sh`
- [ ] **Signed in to Fly.io** — `fly auth login` completed; `fly auth whoami`
      returns the operator's address.
- [ ] **A Supabase project** with a **pooled connection string** ready —
      Supabase dashboard → Settings → Database → Connection pooling →
      *Transaction mode*. The pooled URL is the one used at runtime; the
      direct (non-pooled) URL is used only by `alembic` if migrations open
      multiple sessions in one process. For this deployment the pooled
      URL is sufficient for both (`alembic upgrade head` runs in a
      one-shot Machine).
- [ ] **Supabase IPv4 add-on enabled if needed.** Fly.io egress is IPv4
      while Supabase's free-tier database endpoints default to IPv6-only.
      If `fly deploy` fails the release command with a connection timeout
      to Supabase, enable the IPv4 add-on at Supabase dashboard →
      Settings → Add-ons. (Paid Supabase tiers already include IPv4.)
- [ ] **The CP12 image builds locally** — sanity check before paying
      Fly.io for a remote build:
      ```
      docker build -t llm-tracker-server:local .
      ```

---

## Step-by-step

### 1. Create the Fly.io app (one-time)

```
fly apps create llm-tracker-server
```

The name in `fly.toml` (`app = "llm-tracker-server"`) must match. If the
name is taken, pick another, then update `fly.toml` to match and commit
the change.

### 2. Set secrets (never goes in `fly.toml`)

The single secret the server needs at runtime is the Supabase database
URL. Set it once; Fly stores it encrypted and injects it into every
Machine (including the release-command Machine):

```
fly secrets set \
  LLMTRACK_DATABASE_URL="postgresql+asyncpg://<user>:<password>@<host>:5432/<db>?ssl=require"
```

Verify with `fly secrets list` — the value is redacted, but the key
should appear with a digest and a "Created at" timestamp.

### 3. Deploy

```
fly deploy
```

This runs:

1. A remote `docker build` against the repo (using the local
   `Dockerfile` + `.dockerignore`).
2. The release command — `alembic upgrade head` — in a one-shot
   ephemeral Machine, against the same image and the same secrets. If
   migrations fail here, the rolling deploy is aborted and no traffic
   is shifted.
3. The rolling deploy of the new image to the app Machines.

### 4. Verify the deploy

```
fly status
curl https://llm-tracker-server.fly.dev/healthz
```

Expected:

- `fly status` lists at least one Machine in state `started` and
  `passing` against the health check.
- `curl` returns `HTTP/2 200` and the body `{"status":"ok","version":"0.0.1"}`.

### 5. Issue a demo org + token

The server CLI is shipped inside the runtime image. Invoke it through
`fly ssh console`:

```
fly ssh console -C "llm-tracker-server tokens issue --org demo"
```

Save the printed token — it is shown **once**. This bearer token is what
goes in the client's `ANTHROPIC_BASE_URL` setup (the client sends
`X-LLM-Tracker-Token: <token>` on each request to the proxy; per
ADR-0023, `Authorization` is reserved for the Anthropic credential
pass-through and is never read by the server).

### 6. Verify auth middleware is live

A request without a bearer token must be rejected by the server's auth
middleware (ADR-0020). A request *with* a token must pass middleware and
reach the upstream (and predictably fail upstream with a 400 because the
body is intentionally malformed):

```
curl -X POST https://llm-tracker-server.fly.dev/v1/messages \
  -H "X-LLM-Tracker-Token: <token>" \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'
```

Expected: **HTTP 400** (Anthropic rejecting the empty `messages` array).
A 401/403 here means auth middleware rejected the token; a 502/504 means
the server reached Anthropic but something else failed upstream.

A request **without** the `X-LLM-Tracker-Token` header should be rejected
with 401:

```
curl -i -X POST https://llm-tracker-server.fly.dev/v1/messages \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-opus-4-5","max_tokens":1,"messages":[]}'
```

Expected: **HTTP 401**.

---

## Troubleshooting

### `alembic upgrade head` fails in the release command

- Check `fly secrets list` shows `LLMTRACK_DATABASE_URL`.
- Run `fly logs` to see the alembic traceback. The most common shape is
  `OperationalError: connection ... timed out` (next item) or
  `password authentication failed` (the URL's `<password>` placeholder
  was not substituted).
- Re-run the migration explicitly:
  ```
  fly ssh console -C "alembic upgrade head"
  ```

### Supabase connection times out

Fly's outbound network is IPv4; Supabase's free-tier database endpoint
is IPv6-only by default. Enable the **IPv4 add-on**:

- Supabase dashboard → Settings → Add-ons → *IPv4* → Enable.
- Wait ~1 minute for the DNS to flip.
- Re-run `fly deploy` (or just `fly ssh console -C "alembic upgrade head"`
  if only the migration failed and the app machines are already up).

Paid Supabase tiers include IPv4 by default; this troubleshooting step
applies to the free tier only.

### `/healthz` reports unhealthy after deploy

- `fly logs` — look for startup errors. The boot contract from CP1 is
  that the server attaches no auth-gated routes if no DB is available;
  if `LLMTRACK_DATABASE_URL` is missing, `/healthz` itself still serves
  but downstream routes won't.
- `fly status --all` — confirm a Machine is in state `started`, not
  `crashed` or `pending`.
- `fly ssh console -C "ls -la /app"` — confirm `alembic.ini` and the
  `alembic/` directory shipped into the image; if either is missing
  the release command would have failed earlier, but worth confirming.

### Stale rows in `public.exchanges` from prior test runs

Operators running CP14 smoke tests repeatedly — or revisiting a Supabase
project that was used by an earlier workstream (e.g. the Phase-2
`llm_tracker_plugin_supabase_sink`) — may find that `public.exchanges`
already contains rows before the new run even begins, making it hard to
tell which row the current smoke test wrote. The schema itself is intact;
only the data is stale.

Fix: clear the table via the Supabase dashboard SQL editor or `psql`.

```
-- Drop a specific stale window:
DELETE FROM public.exchanges WHERE started_at < <epoch_ms>;

-- Or wipe the whole table (also resets dependent rows in events,
-- tool_calls, audit_log — all of which carry FK / org-scoped rows):
TRUNCATE TABLE
  public.audit_log,
  public.tool_calls,
  public.events,
  public.exchanges
RESTART IDENTITY;
```

`TRUNCATE` is much faster than `DELETE` for a full wipe and resets any
sequences. The `CASCADE`-equivalent here is the explicit ordered table
list — listing the child tables (`events`, `tool_calls`, `audit_log`)
before `exchanges` avoids FK violations and matches the migration
ownership order.

Notes:

- If the schema *itself* is incompatible (different column names, an
  older sink's `exchange_id` PK, etc.) rather than the data being stale,
  the symptom is a `DuplicateTableError` at `fly deploy` time, not stale
  rows. Drop the colliding table(s) instead — see ADR-0017 history for
  context on the closed `supabase_sink` plugin schema.
- `public.orgs` and `public.api_tokens` are *not* test artefacts and
  should be left alone unless you also want to invalidate every bearer
  token issued so far.

### `DuplicatePreparedStatementError` against the Supabase pooler

Symptom: any DB-touching command or HTTP route — `fly ssh console -C
"alembic current"`, an authenticated `POST /v1/messages`, the `tokens
issue` CLI — fails intermittently with a traceback whose final line is:

```
asyncpg.exceptions.DuplicatePreparedStatementError: prepared statement
"__asyncpg_stmt_1__" already exists
```

The first deploy may even appear healthy; the failure surfaces the
moment two sessions try to use the same pooled backend connection.

Cause: Supabase's **Transaction-mode pooler** (the default "pooled
connection string" exposed on port 6543) routes each transaction to
whichever backend connection is free, and does **not** preserve named
prepared statements across pooled sessions. asyncpg caches statements
by name by default, so the second pooled session that lands on the same
backend collides on `__asyncpg_stmt_N__`.

Two fixes, either is sufficient:

1. **Switch to Supabase's Session-mode pooler.** In the Supabase
   dashboard → Settings → Database → Connection pooling, copy the
   *Session mode* connection string instead of the *Transaction mode*
   one, then update the Fly secret:

   ```
   fly secrets set LLMTRACK_DATABASE_URL="postgresql+asyncpg://<user>:<password>@<host>:<port>/<db>?ssl=require"
   ```

   Session mode pins each client to one backend for the lifetime of the
   client connection, preserving prepared statement names. Trade-off:
   slightly fewer concurrent clients per pool slot than Transaction
   mode.

2. **Disable the prepared-statement cache via the connection URL.**
   Append `prepared_statement_cache_size=0` to the existing pooled URL
   (no pooler change needed):

   ```
   fly secrets set LLMTRACK_DATABASE_URL="postgresql+asyncpg://<user>:<password>@<host>:6543/<db>?ssl=require&prepared_statement_cache_size=0"
   ```

   The SQLAlchemy asyncpg dialect reads `prepared_statement_cache_size`
   from the URL query string and passes it through; setting it to `0`
   disables the cache that pgbouncer cannot keep coherent.

The server's `make_engine()` (and `alembic/env.py`) already pass
`statement_cache_size=0` on the connection-level driver, so a current
build is robust against this without either change above — the
workarounds matter when an operator is running a stock build (no rebuild
permitted) or has overridden the engine factory.

### PG16+ membership `WITH SET` qualifier

Postgres 16 split role membership into three orthogonal options
(`admin_option`, `inherit_option`, `set_option`). The CP14 roundtrip
surfaced this on Supabase: the platform auto-grants the connecting
role (e.g. `postgres`) membership of every freshly created role, but
only with `inherit_option=true`. The very first statement
`AuthMiddleware` issues on each request is `SET LOCAL ROLE
llm_tracker_app`, which needs `set_option=true` and fails on a
PG16-only-`inherit` grant with:

```
asyncpg.exceptions.InsufficientPrivilegeError:
    permission denied to set role "llm_tracker_app"
```

Migration `0006_grant_app_role_set` ships the fix and runs on every
deploy. It branches on `server_version_num`:

- **PG16+** (`>= 160000`): `GRANT llm_tracker_app TO CURRENT_USER
  WITH SET TRUE`.
- **PG15**: plain `GRANT llm_tracker_app TO CURRENT_USER` (the
  `WITH SET TRUE` qualifier is PG16+ only and would syntax-error
  against an older server).

`CURRENT_USER` (not a hardcoded role name) keeps the migration
portable across deploy environments where the connecting role may be
named differently. The `DO $$ ... END $$` block is idempotent — a
re-run after stamping is a no-op. Any future PG16+ managed deploy
(RDS, Cloud SQL, Neon) that hits the same trap is already covered on
first `alembic upgrade head`; no operator action is needed.

### A subsequent deploy needs a fresh secret

`fly secrets set ...` triggers a new deploy by default. To stage
multiple changes (`LLMTRACK_DATABASE_URL` plus an env update plus a
code change), pass `--stage` and then `fly deploy` once:

```
fly secrets set --stage LLMTRACK_DATABASE_URL="..."
fly deploy
```

---

## Data collection & privacy

The central server stores one row per request in `public.exchanges`, and
the bundled `analytics_sink` plugin writes one row per request to
`public.plugin_analytics` carrying the parsed request body
(`messages_json`) and the faithfully reassembled response
(`response_json`, per ADR-0028). The operator should treat the database
as containing the full prompts and responses that flow through the
server.

Privacy posture (ADR-0029):

- **Storage is L3 by default.** The full request body and full response
  reassembly are persisted so the analyses the project exists to enable
  (drift, latency, scope-guard evaluation) have the data they need.
- **Plugin-visible content is scrubbed at the SDK accessor.** Every
  plugin that reads `HookContext.request_text()` /
  `HookContext.response_content_json()` receives content with `sk-…` and
  `lts_…` tokens, `Bearer <value>` mentions, and email addresses
  replaced by `[REDACTED:…]` tags. The canonical bytes in the database
  remain unscrubbed for operator incident response.
- **Retention is 6 months.** Rows older than 6 months are deleted by
  two `pg_cron` jobs that run daily at 03:00 UTC, scheduled by
  migration `0009_retention_deletion_job`:
  `llm-tracker-retention-exchanges` removes from `public.exchanges`
  where `started_at` (unix ms) is older than 6 months;
  `llm-tracker-retention-plugin-analytics` removes from
  `public.plugin_analytics` where `created_at` is older than 6 months.
  The migration is gated on `pg_cron` availability — environments
  without the extension log a `NOTICE` and skip the scheduler, leaving
  the operator the same manual-DELETE fallback that pre-dated this
  job. Inspect the scheduled jobs with `SELECT jobname, schedule,
  command FROM cron.job WHERE jobname LIKE 'llm-tracker-retention-%'`.
- **Deletion requests are operator-handled today.** When an external
  user requests removal of their data, run `DELETE FROM
  public.exchanges WHERE org_id = $1` and `DELETE FROM
  public.plugin_analytics WHERE org_id = $1` through the Supabase MCP
  `execute_sql` path. A typed deletion endpoint is queued behind the
  fix that populates `session_id` for real (currently hardcoded
  `"server"`).
- **The plugin off-switch is `LLMTRACK_PLUGINS_DISABLED`.** Setting
  this to `analytics_sink` stops the per-exchange write to
  `plugin_analytics`; the per-request audit row in `public.exchanges`
  is unaffected. The same switch turns off `scope_guard` (set to
  `scope_guard`, or comma-separate to disable both).
- **When `scope_guard` is enabled** (ADR-0030, Phase 1c), the most
  recent user-initiated turns from each exchange are sent to OpenAI's
  embedding API (`text-embedding-3-small`); ambiguous-band requests
  additionally trigger a `gpt-4o-mini` Chat Completions call.
  Assistant responses and tool-result contents are not sent. OpenAI's
  standard API ToS applies; the operator should configure
  [zero data retention](https://platform.openai.com/docs/guides/your-data)
  on the API key used. The plugin writes one row per evaluation to
  `public.scope_alerts` (org_id, stage, flagged, max_similarity,
  matched_chunk_id, stage2_verdict, stage2_reason); the operator-side
  CLI `process-scope-document <org_id> <file>` registers the
  per-org corpus the alerts are scored against.

External (non-team) testing of the server requires that this disclosure
reach the end user before their traffic is routed through it. Team /
operator use stays unblocked.

---

## What lands after CP13-b

- The server is live at `https://llm-tracker-server.fly.dev` (or the
  operator's chosen app name).
- The Supabase schema has been migrated by the release command.
- One demo org + bearer token exists in `public.api_tokens`.

**Next**: CP14 — operator-only end-to-end smoke. Send one real
`/v1/messages` request through the deployed server with a valid
Anthropic API key in the `x-api-key` header and verify (a) the
response stream returns to the client unchanged, (b) one row lands
in `public.exchanges` scoped to the demo org, and (c) Fly logs show
no traceback. The operator-only flavour of CP14 has **no Phase-3a
dependency**; external-tester flavours of CP14 require ADR-#2 (consent
+ data handling) to be settled first.
