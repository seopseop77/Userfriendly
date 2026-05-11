# ADR-0022 · Deployment platform: Fly.io for the app, Supabase for Postgres

- **Status**: Accepted
- **Date**: 2026-05-11
- **Author**: Claude Cowork (user-approved; decision made in the
  2026-05-11 Phase-3c kick-off session)
- **Related**: ADR-0017 (central-server pivot), ADR-0018 (per-org RLS
  on Postgres — Supabase satisfies), ADR-0020 (per-request lifecycle
  requires a persistent process), `docs/roadmap.md §Phase 3`,
  `docs/STATUS.md`, `docs/worklog/2026-05-07-supabase-sink.md` (CP4 —
  existing operator Supabase project + RLS posture)

## Context

ADR-0017 moved the deployment surface to a central server operated by
the team. ADR-0018 mandates PostgreSQL with Row-Level Security as the
sole tenancy-enforcement mechanism. ADR-0020 mandates a per-request
lifecycle that holds the user's Anthropic API key in process memory
for the duration of the request and forwards a long-lived SSE stream
upstream. Phase 3c needs a concrete deployment target before the first
server-side code lands.

Two coupled choices:

1. **App host.** Where does the FastAPI proxy run?
2. **Database.** Where does PostgreSQL live?

Both must accommodate:

- **Long-lived SSE streams.** Claude Code requests return Server-Sent
  Events; the server holds the inbound connection open while it
  forwards bytes from `api.anthropic.com` (see
  `packages/llm_tracker/src/llm_tracker/proxy/` — the existing Tee +
  SSE forwarder). Serverless platforms with short function timeouts
  (Vercel's 60–300 s caps, Cloudflare Workers' CPU budgets) cannot
  host this shape without significant rewrites.
- **Stateful in-process components.** `PluginHost` holds plugin
  instances for the lifetime of the process; `EgressGuard` caches
  manifests; the DB connection pool stays warm. Cold-starts on every
  request would break plugin lifecycle hooks and blow the Phase 0
  first-token-latency budget (≤ 50 ms overhead, see
  `docs/roadmap.md §Phase 0`).
- **PostgreSQL with RLS available out of the box.** ADR-0018
  specifies RLS as the sole enforcement primitive. We already use
  Supabase's RLS for the `supabase_sink` plugin (`public.exchanges`,
  CP4 of the supabase-sink workstream), so the operator already has a
  populated project and existing CLI familiarity to carry forward.

## Options considered

### Axis 1 — App host

- **A. Fly.io (chosen).** Persistent containerised processes;
  SSE-friendly; single-file `fly.toml` configuration; multi-region
  option available later; free allowance covers the demo footprint.
- **B. Render / Railway / similar.** Functionally equivalent posture.
  Migration cost is one new config file because the app is
  containerised.
- **C. AWS ECS / Fargate.** Strictly more capable; significantly more
  operational surface (VPC, IAM, ALB) for a one-person operator.
  YAGNI for the demo and the single-org enterprise self-hosted shape.
- **D. Vercel / Cloudflare Workers / similar serverless.** Ruled out
  by the SSE + stateful-in-process requirements above.

### Axis 2 — Database

- **A. Supabase (chosen).** Managed PostgreSQL with RLS; already in
  use for `supabase_sink`; the operator has a populated project and
  Supabase CLI familiarity. Free tier covers the demo footprint.
- **B. Fly Postgres.** Co-located with the app; one fewer vendor.
  Trade-off: no managed RLS UX, none of the existing schema/data
  carries over, and the Phase-2 `supabase_sink` workstream already
  invested in Supabase-specific conventions on the operator's side.
- **C. Self-managed PostgreSQL on a VM.** Strictly more operational
  work; no acquisition-cost advantage given Supabase's free tier.

## Decision

**Axis 1: Fly.io.** A containerised FastAPI process described by
`fly.toml` at the repo root. The container is built from a
`Dockerfile` that installs the `llm_tracker_server` package and runs
`uvicorn`. SSE streams flow through the long-lived process.

**Axis 2: Supabase (managed PostgreSQL).** The connection is one
`DATABASE_URL` environment variable. The server speaks SQL through
SQLAlchemy + `asyncpg`; no Supabase JS/REST SDK is used from the
server. RLS is enabled per ADR-0018 inside the PostgreSQL schema;
Supabase only provides the hosted Postgres + RLS substrate, not
application logic.

**`DATABASE_URL` is the single DB knob.** No Supabase-specific URL
parsing, no PostgREST endpoint hardcoded in the server, no
`supabase-py` SDK import in the server package. This keeps the server
portable to Fly Postgres, Neon, RDS, or any other PostgreSQL in the
future — migration is one env-var change, not a code change.

**Containerised, not platform-locked.** The app is a `Dockerfile`;
Fly is only the orchestrator. Enterprise self-hosted operators
(ADR-0017 §Decision item 1) replace `fly.toml` with their own
deployment config (`docker-compose.yml`, a Helm chart, an ECS task
definition, etc.) without touching server code.

## Consequences

### What this enables

- A concrete deploy target unblocks Phase 3c. CI can build the image,
  Fly can run it, Supabase already holds the demo project.
- ADR-0018's PostgreSQL RLS posture is satisfied without a separate
  DB build-out — Supabase ships RLS.
- The `supabase_sink` schema and the operator's existing RLS posture
  carry over to the new server-side tables (schema shape is the
  same; the use-case is "primary storage" instead of "egress sink").
- Enterprise self-hosted remains structurally open (ADR-0017
  §Decision item 1). Operators replace `fly.toml` and provide their
  own Postgres URL.

### What this constrains

- Two new artefacts to maintain: `Dockerfile` and `fly.toml`. Both
  small; the Dockerfile is mostly `pip install` and `CMD uvicorn`.
- Supabase free-tier limits apply: 500 MB database, 5 GB egress,
  auto-pause after a week of inactivity. Acceptable for the demo;
  the upgrade lever is one paid-tier toggle when scale arrives.
- Anthropic API egress from Fly counts against Fly's network quota.
  Below the free allowance at demo scale; flagged for re-check when
  traffic grows.
- Logs that contain raw user prompts (storage layer, audit log) live
  in Supabase (Postgres) plus whatever Fly retains in its log
  stream. ADR-0020's "never log the Anthropic credential header"
  rule applies to the Fly log stream specifically — not optional.

### What this forecloses

- Edge / serverless deployment patterns (Cloudflare Workers, Vercel
  Edge) for the proxy. Re-opening requires solving SSE +
  stateful-in-process problems that don't have clean answers today.
- Using Supabase's anon-key + PostgREST as the server's data access
  layer. Server speaks SQL directly through `asyncpg`; PostgREST
  remains the `supabase_sink` plugin's transport, not the core
  server's.

### Reversibility

High. `DATABASE_URL` swaps the DB without code changes. The
Dockerfile runs on any Docker host; `fly.toml` is replaced 1:1 by
another orchestrator's manifest. The decision binds two new files at
the repo root, not the source tree.

## Open questions

- **Migration runner location.** Whether `alembic upgrade head` runs
  as a Fly release command, a CI step before deploy, or a one-shot
  process — defer to the Phase 3c containerisation checkpoint.
- **Secrets management.** `DATABASE_URL`, per-org token-issuance
  signing secrets (if any), and infrastructure credentials live in
  Fly's secret store. Specifics defer to the Phase 3c containerisation
  checkpoint.
- **Region selection.** Single-region (Fly's default `iad`) suffices
  for the demo. Multi-region warrants a follow-up ADR if/when
  latency or residency requirements bite.
