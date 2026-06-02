# 2026-06-02 · Migrate storage from Supabase to a local self-hosted box

**Author**: Claude Code
**Session trigger**: User: "프록시 서버에서 supabase로 데이터를 전송하고
supabase에서 데이터를 저장하고 있어. 근데 그 저장소 위치를 현재 사용하고
있는 linux 컴퓨터로 migration 하고 싶어." → after Q&A: topology 1 (full
self-host), pgvector package installed, signup stays externally visible,
existing data disposable, **only the DB connection changes to local**.
**Related docs**: ADR-0042, `docs/deploy-selfhost.md`, supersedes ADR-0022,
`docs/deploy.md`

## Interpretation

Storage was Supabase Postgres; the server + signup ran on Fly.io against
it. The request is to move the data onto the operator's Linux box. The code
is already backend-agnostic (everything reads `LLMTRACK_DATABASE_URL`, a
plain PostgreSQL URL), so this is an infra/topology change, not a code
change.

Decisions confirmed with the user (see ADR-0042 Options):

- **Topology 1** — self-host server + signup + Postgres on this box; expose
  only the authenticated HTTP services. Chosen over "Fly server + local DB"
  because external participants force *some* internet exposure, and
  exposing an auth'd HTTP API beats exposing raw Postgres holding L3
  content.
- **signup stays externally visible**, repointed at the local DB — so it
  also runs locally (localhost DB) and is exposed via a second tunnel
  hostname. This keeps Postgres local-only.
- **Fresh start**, schema only — no Supabase data migration.
- **pgvector present** (via the container image) so migrations apply; **pg_cron
  absent** (retention migrations are already gated and skip). scope_guard
  stays disabled.

No source code is touched — only `LLMTRACK_DATABASE_URL` is repointed.

## What was done

### Checkpoint 1 — decision + infra scaffolding (repo artifacts)

- Created `docs/decisions/0042-self-host-local-postgres.md` — ADR;
  supersedes ADR-0022; records topology, extension policy, reversibility.
- Created `docker-compose.yml` (repo root) — `db` (pgvector/pgvector:pg16),
  one-shot `migrate` (`alembic upgrade head`), `server` (:8080), `signup`
  (:8000). DB port unpublished; service ports bind 127.0.0.1; reuses the
  existing per-service Dockerfiles unchanged.
- Created `selfhost.env.example` — `POSTGRES_PASSWORD`, `PUBLIC_SERVER_URL`.
  `.env` is already gitignored.
- Created `docs/deploy-selfhost.md` — step-by-step: prereqs (Docker,
  cloudflared), `docker compose up`, token issuance, Cloudflare Tunnel
  setup, client repoint, ops (backup/retention/upgrade).

(commit 909e039)

### Checkpoint 2 — live local bring-up + verification (operator box)

Docker Engine 29.5.2 + Compose v5.1.4 installed on the box. Stack brought
up with `docker compose up -d --build` and verified end-to-end against the
local Postgres (no Fly, no Supabase, no tunnel yet):

- All four services healthy; `migrate` exited 0; `alembic_version` ==
  `0023_view_session_id` (head). pgvector migrations (0010/0012) applied via
  the `pgvector/pgvector:pg16` image; pg_cron migrations (0009/0011) ran
  without error (gated → skipped scheduling).
- `llm_tracker_app` RLS role present (self-created by migration 0005).
- `llm-tracker-server tokens issue --org demo` wrote one `orgs` + one
  `api_tokens` row to the local DB → DB writes confirmed.
- Auth: no-token POST /v1/messages → middleware 401 (no forward); valid-token
  POST → `proxy.forward` logged + forwarded to api.anthropic.com, which
  replied 401 "x-api-key header is required" (upstream, not middleware).

Found + fixed two doc errors in `docs/deploy-selfhost.md`: the CLI is
`llm-tracker-server` (not `llm-tracker`), and the auth check's expected
codes/explanation (valid token forwards upstream; distinguish by body/log,
not status code). (commit hash: pending)

## Decisions

- **Self-host everything (topology 1) over keeping Fly + local DB** —
  lifted to ADR-0042 (hard-to-reverse / wide-impact). Core reason: with
  external participants, exposing an authenticated HTTP API is far safer
  than exposing raw Postgres.
- **pgvector via the base image, not a host apt package** — the
  `pgvector/pgvector:pg16` image bundles the extension, so migrations
  0010/0012 apply without touching migration code (surgical). Satisfies the
  "install pgvector" decision within the Docker topology.
- **No code change** — DB repoint is purely `LLMTRACK_DATABASE_URL`. The
  pgbouncer `statement_cache_size=0` connect-arg is left as-is (no-op on
  direct Postgres) per surgical-changes rule.

## Verification

Repo-side only (the box has no docker/postgres/cloudflared yet, so the live
path is not yet exercised):

```
$ python3 -c "import yaml; d=yaml.safe_load(open('docker-compose.yml')); print(list(d['services']))"
['db', 'migrate', 'server', 'signup']
```

- `docker-compose.yml` parses; `.env` confirmed gitignored
  (`.gitignore:16`).
- Confirmed migration 0005 self-creates the `llm_tracker_app` role
  (`CREATE ROLE ... IF NOT EXISTS`) and 0006 grants it `WITH SET` to the
  connecting role — so a greenfield local DB needs no manual role setup,
  only a `CREATE ROLE`-capable connecting role (the container's
  `llm_tracker` superuser qualifies).
- Confirmed retention migrations 0009/0011 are gated on `pg_cron` and skip
  with a NOTICE when absent; migration 0010 does an unconditional
  `CREATE EXTENSION IF NOT EXISTS vector` → requires the pgvector image
  (handled).

**Verified live on the box (CP2)**: `docker compose up` end-to-end, schema
at head against the real local DB, RLS role, token issuance writing to the
local DB, and the auth middleware (reject without token / forward with
token).

**Not yet verified**: tunnel reachability from off-box, and one live
exchange (real Anthropic key) landing a `plugin_analytics` row.

## What's left / known limits

Done (CP2): steps 1–3 below — Docker installed, stack up, schema/auth
verified locally.

Remaining operator-driven steps (need interactive browser auth — see
`docs/deploy-selfhost.md`):

4. `cloudflared tunnel login/create/route` → public hostnames for server
   and signup; set `PUBLIC_SERVER_URL` in `.env`; `docker compose up -d` to
   refresh the signup success-page URL.
5. Repoint a client with `claude-manage setup <TOKEN> --server-url
   https://<host>`; run one real exchange; confirm a `plugin_analytics` row.
6. Tear down the Fly apps + Supabase project once the cutover is confirmed.

Known limits: no off-box backups yet (ADR-0042 open question); retention
not running (pg_cron absent — host-cron DELETE if needed).

## Handoff

The stack is **running and verified locally** on the box (CP2): server
:8080 + signup :8000 + Postgres, schema at head, auth working, demo token
issued. Everything keys off the local DB; no Fly/Supabase involved.

Next single step: **set up the Cloudflare Tunnel** (step 4 — needs an
interactive `cloudflared tunnel login` in a browser) to expose the server
and signup hostnames, then set `PUBLIC_SERVER_URL` and repoint a client to
confirm a live `plugin_analytics` row. See `docs/deploy-selfhost.md §4–5`.

## Suggestions (untouched)

- **Backups**: a `pg_dump` host-cron to off-box storage before this becomes
  the only copy of the data.
- **Retire the Fly/Supabase artifacts**: once the cutover is verified, the
  two `fly.toml` files and `docs/deploy.md` could be archived; left in place
  this session (surgical — no instruction to remove them).
