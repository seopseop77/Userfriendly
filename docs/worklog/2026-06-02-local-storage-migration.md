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

### Checkpoint 3 — pre-stage what doesn't need the domain (operator box)

Operator deferred buying the domain; pre-staged the domain-independent work:

- Installed `cloudflared` 2026.5.2 to `~/.local/bin` (official GitHub
  binary, no sudo). `cloudflared tunnel login/create/route` remain blocked
  on having a Cloudflare-managed domain.
- Added `restart: unless-stopped` to `db`/`server`/`signup` in
  `docker-compose.yml` (migrate stays `no`); recreated. The Docker daemon is
  already `systemctl enabled`, so the stack now survives a host reboot.
  (commit 4473b3c)

### Checkpoint 4 — Cloudflare Tunnel live + persistent (operator box)

Operator created a Cloudflare account and bought the domain
**`userfriendly.win`**. Brought the public edge up (step 4):

- `cloudflared tunnel login` (browser, operator) → `~/.cloudflared/cert.pem`.
- `cloudflared tunnel create llm-tracker` → tunnel id
  `694232c8-b020-469a-bdb7-dd6135c4f801` + credentials JSON.
- Wrote `~/.cloudflared/config.yml` ingress (subdomain split):
  `llm-tracker.userfriendly.win` → `127.0.0.1:8080` (server),
  `signup.userfriendly.win` → `127.0.0.1:8000` (signup), else 404.
- `cloudflared tunnel route dns` added both CNAMEs.
- Set `PUBLIC_SERVER_URL=https://llm-tracker.userfriendly.win` in `.env`;
  `docker compose up -d` recreated signup with the real URL.
- **Persistence**: copied the binary to `/usr/local/bin/cloudflared` and
  `config.yml`+credentials to `/etc/cloudflared/` (credentials-file path
  rewritten to `/etc/cloudflared/`), then `cloudflared service install` +
  `systemctl enable --now cloudflared`. Service is `active` + `enabled` →
  survives reboot alongside the Docker stack.

Verified off-box through the tunnel: `GET /healthz` 200 on both hostnames;
`POST /v1/messages` with no token → middleware 401
(`missing X-LLM-Tracker-Token header`), proving the auth path is reachable
end-to-end (edge → server → auth). Single cloudflared process (the service);
the temporary foreground tunnel used for the first check was stopped.

(no repo commit for the tunnel itself — config + credentials live outside
the repo under `~/.cloudflared` and `/etc/cloudflared`; `.env` is gitignored)

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

**Verified live through the tunnel (CP4)**: both hostnames answer
`/healthz` 200 off-box; no-token `POST /v1/messages` → middleware 401. The
cloudflared systemd service is `active`+`enabled`.

**Not yet verified**: one live exchange (real Anthropic key, via a repointed
`claude-manage` client) landing a `plugin_analytics` row (step 5).

## What's left / known limits

Done (CP2): steps 1–3 — Docker installed, stack up, schema/auth verified
locally. Done (CP4): step 4 — tunnel live on `userfriendly.win`, persistent
via systemd, verified off-box.

Remaining:

5. Repoint a client with `claude-manage setup <TOKEN> --server-url
   https://llm-tracker.userfriendly.win`; run one real exchange; confirm a
   `plugin_analytics` row. (Issue a real-org token first:
   `docker compose exec server llm-tracker-server tokens issue --org <org>`.)
6. Tear down the Fly apps + Supabase project once the cutover is confirmed.

Known limits: no off-box backups yet (ADR-0042 open question); retention
not running (pg_cron absent — host-cron DELETE if needed).

**Deferred decision — DB storage path.** The Postgres data currently lives
in the Docker-managed named volume `userfriendly_pgdata`
(`/var/lib/docker/volumes/userfriendly_pgdata/_data`, on the NVMe root
`/dev/nvme0n1p2`). The operator wants to switch to an **explicit fixed
path** (bind mount, e.g. a dedicated data disk or `~/llm-tracker-data`) but
has not chosen the path yet. Easiest to do *now* while data is disposable
(fresh-start) — swap the `pgdata` named volume for a bind mount in
`docker-compose.yml` and re-run `docker compose up`. Revisit when the target
path/disk is decided. Capacity is not a concern (see CP-note below).

**Capacity (asked 2026-06-02, no action taken)** — for a handful of research
participants this box is wildly over-provisioned: Fly ran the same stack on
512MB/1 shared vCPU (scaled to zero); this box is 24 cores / 60GB, idle
usage ~157MB / 0.1% CPU. `exchanges` stores metadata only; `plugin_analytics`
stores per-turn deltas (not full history), so disk grows slowly (~10s–100s
of MB/day even at 30 heavy users; bounded further if retention is enabled).
The only real-world pinch at peak concurrency is home upstream bandwidth,
not CPU/RAM/disk.

## Handoff

The full stack is **live and publicly reachable** (CP4): server :8080 +
signup :8000 + Postgres on the box, fronted by a Cloudflare Tunnel on
`userfriendly.win` (`llm-tracker.` → server, `signup.` → signup). The
cloudflared systemd service and the Docker stack both auto-start on reboot.
Off-box `/healthz` 200 on both hosts; proxy auth (401 without token) verified
through the tunnel. No Fly/Supabase involved.

Next single step: **client cutover (step 5)** — issue a real-org token
(`docker compose exec server llm-tracker-server tokens issue --org <org>`),
then on a participant PC `claude-manage setup <TOKEN> --server-url
https://llm-tracker.userfriendly.win`, run one real exchange, and confirm a
`plugin_analytics` row lands (`docker compose exec db psql -U llm_tracker -d
llm_tracker -c "SELECT count(*) FROM plugin_analytics;"`). Then step 6: tear
down Fly + Supabase. See `docs/deploy-selfhost.md §5`.

## Suggestions (untouched)

- **Backups**: a `pg_dump` host-cron to off-box storage before this becomes
  the only copy of the data.
- **Retire the Fly/Supabase artifacts**: once the cutover is verified, the
  two `fly.toml` files and `docs/deploy.md` could be archived; left in place
  this session (surgical — no instruction to remove them).
