# ADR-0042 · Self-host the central server + Postgres on the operator box

- **Status**: Accepted
- **Date**: 2026-06-02
- **Author**: Claude Code (with operator)
- **Related**: supersedes ADR-0022 (Fly.io + Supabase); ADR-0017
  (central-server pivot), ADR-0018 (per-org RLS), ADR-0020 (per-org
  bearer token), `docs/deploy-selfhost.md`,
  `docs/worklog/2026-06-02-local-storage-migration.md`

## Context

The storage backend was Supabase Postgres, with the central server and the
signup app running as two Fly.io services that connect to it (ADR-0022).
The operator wants the data to live on the Linux box they already operate,
not in a managed cloud database.

Constraints established with the operator:

- **External participants must still reach the service.** This is the
  load-bearing constraint — *something* has to be exposed to the internet
  either way.
- Existing Supabase data is disposable — **fresh start, schema only**. No
  data migration.
- Code is already backend-agnostic: every storage consumer reads a single
  `LLMTRACK_DATABASE_URL` (standard PostgreSQL). Nothing is bound to
  Supabase APIs at the code level.

## Options considered

1. **Keep both services on Fly.io, point them at a Postgres on the local
   box.** Cons: the database (full L3 prompts + responses) must be exposed
   to the public internet or tunneled to Fly; every query crosses the
   internet from Tokyo to a residential line; a changing home IP breaks the
   server; still pays for Fly. This is the worst of both worlds — cloud
   *and* home-box dependency, plus a raw-Postgres attack surface.

2. **Self-host the whole stack on the local box (server + signup +
   Postgres), expose only the authenticated HTTP services.** Cons: the
   operator runs the box (uptime, backups). Pros: the database never leaves
   the box (localhost-only); the only thing exposed is an HTTP API that
   already has bearer-token auth + per-org RLS (ADR-0018/0020); no Fly
   dependency; no internet round-trip per query.

## Decision

**Pick option 2.** Three reasons:

1. With external participants, exposure is unavoidable. Exposing an
   **authenticated HTTP API** (already designed for this) is far safer than
   exposing **raw Postgres** holding L3 content — option 1's fatal flaw.
2. The code needs **no change** — only `LLMTRACK_DATABASE_URL` is repointed
   at the local database. Self-hosting effort is modest because the Docker
   images already exist and auth is already built.
3. It removes the managed-cloud dependency entirely (no Fly, no Supabase).

Concrete shape: a root `docker-compose.yml` runs `db` (Postgres + pgvector),
a one-shot `migrate` (`alembic upgrade head`), `server` (:8080), and
`signup` (:8000). Service ports bind to `127.0.0.1` only; the public edge is
a **Cloudflare Tunnel** (stable HTTPS hostname without a static IP or port
forwarding). Postgres is never published off the box.

### Extension policy

- **pgvector** is provided by the `pgvector/pgvector` base image so the
  scope_guard migrations (0010/0012) apply cleanly. The extension is
  *present* but scope_guard stays **disabled** via
  `LLMTRACK_PLUGINS_DISABLED=scope_guard` (it remains a paused track).
- **pg_cron** is *not* installed. The retention migrations (0009/0011) are
  already gated on `pg_cron` availability and skip with a `NOTICE`.
  Retention, if wanted, is a host `cron` + `DELETE` follow-up.

## Consequences

- **Enables**: full local ownership of all prompt/response data; zero
  managed-cloud cost; localhost DB latency.
- **Forecloses**: Fly.io's managed uptime/scaling — the operator now owns
  availability, backups (`pg_dump` of the `pgdata` volume), and the tunnel.
- **Reversibility**: high. Because everything keys off
  `LLMTRACK_DATABASE_URL`, returning to a managed Postgres later is a secret
  change + `alembic upgrade head` + redeploy. No code is coupled to this
  decision.

## Open questions

- **Backups**: `pgdata` is a Docker volume on one box. A `pg_dump` cron to
  off-box storage is recommended but out of scope for the initial cutover.
- **Retention**: with pg_cron absent, the 6-month deletion jobs do not run.
  If retention is required, schedule a host-cron `DELETE` (see
  `docs/deploy.md §Data collection & privacy` for the column predicates).
- **DB storage path (deferred)**: data currently lives in the Docker-managed
  named volume `userfriendly_pgdata`
  (`/var/lib/docker/volumes/userfriendly_pgdata/_data`). The operator intends
  to pin it to an explicit fixed path (bind mount, possibly a dedicated data
  disk) but has not chosen the path. Cheapest to switch now while data is
  disposable. Tracked in `docs/worklog/2026-06-02-local-storage-migration.md`.
