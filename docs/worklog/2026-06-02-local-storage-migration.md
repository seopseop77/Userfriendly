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

**Not yet verified (requires the operator's machine):** `docker compose up`
end-to-end, `alembic upgrade head` against the real local DB, tunnel
reachability, and one live exchange landing a `plugin_analytics` row.

## What's left / known limits

Operator-driven steps (need sudo / interactive browser auth — see
`docs/deploy-selfhost.md`):

1. Install Docker Engine + Compose plugin, and cloudflared.
2. `cp selfhost.env.example .env`; set `POSTGRES_PASSWORD`.
3. `docker compose up -d --build` → verify `/healthz` on :8080 and :8000.
4. `cloudflared tunnel login/create/route` → public hostnames for server
   and signup; set `PUBLIC_SERVER_URL`; `docker compose up -d` to refresh.
5. Issue a token; repoint a client with `claude-manage setup <TOKEN>
   --server-url https://<host>`; confirm a `plugin_analytics` row.
6. Tear down the Fly apps + Supabase project once the cutover is confirmed.

Known limits: no off-box backups yet (ADR-0042 open question); retention
not running (pg_cron absent — host-cron DELETE if needed).

## Handoff

Repo scaffolding (ADR-0042 + compose + env example + deploy guide) is in
place and committed. The next session — or the operator — executes the
six steps above starting with **installing Docker + cloudflared on the
box**, then `docker compose up -d --build`. Nothing further can be verified
in-repo; the remaining work is on the machine.

## Suggestions (untouched)

- **Backups**: a `pg_dump` host-cron to off-box storage before this becomes
  the only copy of the data.
- **Retire the Fly/Supabase artifacts**: once the cutover is verified, the
  two `fly.toml` files and `docs/deploy.md` could be archived; left in place
  this session (surgical — no instruction to remove them).
